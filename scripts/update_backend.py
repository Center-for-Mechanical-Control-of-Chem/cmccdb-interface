#!/usr/bin/env python3
"""Archive, rehearse, migrate and release main/preview backends; never dev.

Run locally on the deployment host as the same rootless container-engine user.
The old database image/container/volume are preserved. No git pull, image prune,
database reset, arbitrary migration SQL, or destructive automatic rollback.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TARGETS = {'main': ('docker-compose.yml','web','database','production'),
           'preview': ('docker-compose-preview.yml','web_preview','database_preview','preview')}
SOURCE_ROOTS = ('/app/cmccdb-interface', '/app/cmccdb-schema', '/app/dev-src')
OFF = {'CMCCDB_DEV_BACKEND':'false','CMCCDB_DEV_FRONTEND':'false',
       'CMCCDB_DEV_FRONTEND_PROXY':'false','CMCCDB_LAUNCH_DEV_INTERFACE':'false',
       'CMCCDB_DEV_ENDPOINTS':'false','PYTHONPATH':'/app/cmccdb-interface:/app/cmccdb-schema'}


class UpdateError(RuntimeError):
    pass


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('w') as file:
        os.chmod(temporary, 0o600)
        json.dump(value, file, indent=2, sort_keys=True)
        file.flush(); os.fsync(file.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as file:
        for data in iter(lambda:file.read(1024*1024), b''):
            result.update(data)
    return result.hexdigest()


def env_dict(info):
    return dict(item.split('=',1) for item in info['Config'].get('Env',[]) if '=' in item)


def label(info, key):
    values = info['Config'].get('Labels') or {}
    return values.get('com.docker.compose.'+key) or values.get('io.podman.compose.'+key)


def dev(info):
    identity = ' '.join(str(v) for v in [label(info,'project'),label(info,'service'),info.get('Name','')]).lower()
    return 'dev' in identity or any(env_dict(info).get(k,'').lower() in {'1','true','yes','on'}
        for k in ['CMCCDB_DEV_BACKEND','CMCCDB_DEV_FRONTEND','CMCCDB_DEV_FRONTEND_PROXY'])


def source_mount(destination):
    return any(destination==root or destination.startswith(root+'/') for root in SOURCE_ROOTS)


def same_image(a,b):return a.removeprefix('sha256:')==b.removeprefix('sha256:')


def literal_config(value):
    """Resolved values must not undergo Compose dollar interpolation a second time."""
    if isinstance(value,str):return value.replace('$','$$')
    if isinstance(value,list):return [literal_config(v) for v in value]
    if isinstance(value,dict):return {k:literal_config(v) for k,v in value.items()}
    return value


def frozen_config(config, target, image, project):
    """Write one complete Compose model, avoiding provider-specific merge/reset tags."""
    result = copy.deepcopy(config)
    result['name'] = project
    web = result['services'][TARGETS[target][1]]
    web['image'] = image
    web.pop('build',None)
    web['pull_policy'] = 'never'
    web['environment'] = {**web.get('environment',{}), **OFF}
    web['volumes'] = [v for v in web.get('volumes',[]) if not source_mount(v['target'])]
    web.pop('profiles',None)
    # No dev services can be carried into the generated release file.
    if any('dev' in name.lower() for name in result['services']):
        raise UpdateError('Development services are present in the resolved deployment')
    return result


class Runner:
    def __init__(self, logfile=None): self.logfile=logfile

    def run(self, arguments, data=None, output=None, timeout=3600, check=True):
        try:
            result = subprocess.run(list(map(str,arguments)), input=data,
                stdout=output or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpdateError('Could not complete '+str(arguments[0])+' '+str(arguments[1])) from error
        if self.logfile:
            with self.logfile.open('ab') as log:
                log.write(result.stdout or b''); log.write(result.stderr)
        if check and result.returncode:
            raise UpdateError('Command failed; see private update.log: '+str(arguments[0])+' '+str(arguments[1]))
        return result


class Release:
    def __init__(self, args, runner=None):
        self.args=args; self.repo=args.source_root.resolve(); self.workspace=self.repo.parent
        self.engine=args.engine; self.runner=runner or Runner()
        self.archive_root=(args.archive_root or self.workspace/'archives').resolve()
        self.worker=(Path(__file__).parent/'backend_update_worker.py').read_bytes()
        self.compose_file=self.repo/'cmccdb_interface'/TARGETS[args.target][0]
        self.web_service, self.db_service=TARGETS[args.target][1:3]
        self.folder=None; self.web_stopped=False; self.data_started=False
        if args.project_name:self.project=args.project_name

    def command(self,*arguments,**kwargs):return self.runner.run([self.engine,*arguments],**kwargs)

    def compose(self,*arguments,file=None,**kwargs):
        prefix=['compose','--file',str(file or self.compose_file)]
        if hasattr(self,'project'):prefix += ['--project-name',self.project]
        return self.command(*prefix,*arguments,**kwargs)

    def inspect(self, identifier):
        return json.loads(self.command('container','inspect',identifier).stdout)[0]

    def discover(self):
        if self.args.target not in TARGETS or self.engine not in {'podman','docker'}:
            raise UpdateError('Only main/preview with podman/docker are supported')
        if not self.compose_file.is_file():raise UpdateError('Deployment compose file is missing')
        information=json.loads(self.command('info','--format','{{json .}}').stdout)
        rootless=(information.get('host',information.get('Host',{})).get('security',information.get('Host',{}).get('Security',{})).get('rootless',False)
                  if self.engine=='podman' else any('rootless' in s for s in information.get('SecurityOptions',[])))
        self.tool_user=[] if rootless or os.getuid()==0 else ['--user',str(os.getuid())+':'+str(os.getgid())]
        identifiers=[]
        for service in [self.web_service,self.db_service]:
            values=self.compose('ps','--quiet',service).stdout.decode().split()
            if len(values)!=1:raise UpdateError('Expected exactly one running '+service+' container')
            identifiers.append(values[0])
        self.web_id,self.db_id=identifiers
        self.web,self.db=self.inspect(self.web_id),self.inspect(self.db_id)
        for info, service in [(self.web,self.web_service),(self.db,self.db_service)]:
            if dev(info) or label(info,'service') != service or not info['State']['Running']:
                raise UpdateError('Refusing development, stopped, or mismatched '+service+' container')
        self.project=label(self.web,'project')
        if not self.project or self.project!=label(self.db,'project'):
            raise UpdateError('Web and database are not in the same Compose project')
        if self.args.project_name and self.args.project_name!=self.project:
            raise UpdateError('Compose provider returned a different project than requested')
        self.pg_env=env_dict(self.web)
        if any(k not in self.pg_env for k in ['POSTGRES_HOST','POSTGRES_USER','POSTGRES_PASSWORD']):
            raise UpdateError('The running backend lacks explicit PostgreSQL connection settings')
        if self.pg_env.get('POSTGRES_DATABASE','cmcc') not in {'cmcc','staging'}:
            raise UpdateError('The backend points to a non-production logical database')
        networks=self.db.get('NetworkSettings',{}).get('Networks',{})
        common=set(networks)&set(self.web.get('NetworkSettings',{}).get('Networks',{}))
        host=self.pg_env['POSTGRES_HOST']
        choices=[(name,networks[name]) for name in sorted(common)
                 if host in (networks[name].get('Aliases') or []) or host==networks[name].get('IPAddress')]
        if not choices:raise UpdateError('Cannot prove POSTGRES_HOST points to the selected database container')
        self.network, connection=choices[0]
        self.database_ip=connection.get('IPAddress')
        if not self.database_ip:raise UpdateError('Selected database network has no routable address')
        # Reject shared persistence with any other running database, especially dev.
        pgdata=env_dict(self.db).get('PGDATA','/var/lib/postgresql/data')
        self.db_mounts=[m for m in self.db.get('Mounts',[]) if pgdata==m['Destination'] or pgdata.startswith(m['Destination']+'/')]
        if not self.db_mounts:raise UpdateError('Database persistence cannot be identified')
        running=self.command('ps','--quiet').stdout.decode().split()
        if running:
            for other in json.loads(self.command('container','inspect',*running).stdout):
                if other['Id']==self.db['Id']:continue
                if 'PGDATA' not in env_dict(other):continue
                for old in self.db_mounts:
                    for mount in other.get('Mounts',[]):
                        a,b=old.get('Source'),mount.get('Source')
                        if a and b and os.path.commonpath([a,b]) in {a,b}:
                            raise UpdateError('Selected database shares persistence with another database; refusing update')
        user=env_dict(self.db).get('POSTGRES_USER','postgres')
        self.cluster=self.command('exec',self.db_id,'psql','-U',user,'-d','postgres','-Atc',
            'SELECT system_identifier FROM pg_control_system()').stdout.decode().strip()
        if not self.cluster.isdigit():raise UpdateError('Cannot identify PostgreSQL cluster')
        self.databases=self.command('exec',self.db_id,'psql','-U',user,'-d','postgres','-Atc',
            "SELECT datname FROM pg_database WHERE datname IN ('cmcc','staging') ORDER BY datname").stdout.decode().split()
        if 'cmcc' not in self.databases:raise UpdateError('The selected production cluster has no cmcc database')
        raw=self.compose('config','--format','json',check=False)
        if raw.returncode==0:
            self.config=json.loads(raw.stdout)
        else:
            try: import yaml
            except ImportError as error:
                raise UpdateError('Compose provider needs either config --format json or host PyYAML') from error
            self.config=yaml.safe_load(self.compose('config').stdout)
        # Canonicalize older podman-compose YAML models too.
        for service in self.config['services'].values():
            environment=service.get('environment',{})
            if isinstance(environment,list):environment=dict(x.split('=',1) for x in environment)
            service['environment']={k:str(v) for k,v in environment.items() if v is not None}
            mounts=[]
            for value in service.get('volumes',[]):
                if isinstance(value,str):
                    pieces=value.split(':')
                    if len(pieces)<2:raise UpdateError('Anonymous/ambiguous source mount in Compose config')
                    source,destination=pieces[:2]
                    value={'type':'bind' if source.startswith(('/','.')) else 'volume','source':source,'target':destination}
                    if value['type']=='bind':value['source']=str((self.compose_file.parent/source).resolve())
                    if len(pieces)>2:
                        flags=pieces[2].split(',')
                        value['read_only']='ro' in flags
                        if 'z' in flags or 'Z' in flags:value['bind']={'selinux':'Z' if 'Z' in flags else 'z'}
                mounts.append(value)
            service['volumes']=mounts
        if any('dev' in service.lower() for service in self.config['services']):
            raise UpdateError('Development services are not allowed')
        # Preserve the running session/OAuth/database settings, even if the invoking
        # shell's variables differ from the ones used for the previous deployment.
        existing={k:v for k,v in self.pg_env.items() if k.startswith('POSTGRES_') or k in
                  {'GITHUB_CLIENT_ID','GITHUB_CLIENT_SECRET','CMCCDB_SESSION_KEY','CMCCDB_MAINTENANCE_API'}}
        self.config['services'][self.web_service]['environment'].update(existing)
        self.old_image=self.web['Image']; self.db_image=self.db['Image']
        sizes=[int(json.loads(self.command('image','inspect',image).stdout)[0].get('Size',0))
               for image in [self.old_image,self.db_image]]
        database_bytes=int(self.command('exec',self.db_id,'psql','-U',user,'-d','postgres','-Atc',
            "SELECT coalesce(sum(pg_database_size(datname)),0) FROM pg_database WHERE datname IN ('cmcc','staging')").stdout.decode().strip())
        self.archive_minimum=sum(sizes)+2*database_bytes+256*1024*1024
        # Verify actual old image prerequisites with old, effective source.
        for database in self.databases:self.old_worker('probe',database)
        return {'target':self.args.target,'project':self.project,'web_container':self.web_id,
            'database_container':self.db_id,'cluster':self.cluster,'old_web_image':self.old_image,
            'old_database_image':self.db_image,'build_target':self.args.build_target or TARGETS[self.args.target][3],
            'databases':self.databases,'archives':str(self.archive_root),'estimated_minimum_archive_bytes':self.archive_minimum}

    def old_worker(self,action,database):
        result=self.command('exec','--interactive','--env','CMCCDB_RELEASE_TARGET='+self.args.target,
            '--env','CMCCDB_EXPECTED_CLUSTER='+self.cluster,self.web_id,'/opt/venv/bin/python','-',action,database,data=self.worker)
        return self.result(result)

    @staticmethod
    def result(result):
        values=[line.removeprefix('CMCCDB_RELEASE_RESULT=') for line in result.stdout.decode().splitlines()
                if line.startswith('CMCCDB_RELEASE_RESULT=')]
        if len(values)!=1:raise UpdateError('Maintenance worker did not return one structured result')
        return json.loads(values[0])

    def state(self,phase,**values):
        self.journal.update(phase=phase,**values)
        write_json(self.folder/'release.json',self.journal)
        print(phase.replace('_',' '),flush=True)

    def snapshot_source(self):
        destination=self.folder/'candidate-source'
        manifests={}
        for repository in ['cmccdb-interface','cmccdb-schema']:
            source=self.workspace/repository
            ref=self.args.interface_ref if repository=='cmccdb-interface' else self.args.schema_ref
            if ref:
                target=destination/repository; target.mkdir(parents=True,exist_ok=True)
                archive=self.folder/(repository+'-candidate-git.tar')
                commit=self.runner.run(['git','-C',source,'rev-parse','--verify','--end-of-options',ref+'^{commit}']).stdout.decode().strip()
                if not commit or any(c not in '0123456789abcdef' for c in commit):
                    raise UpdateError('Candidate Git ref did not resolve to a commit')
                with archive.open('wb') as file:
                    self.runner.run(['git','-C',source,'archive','--format=tar',commit],output=file)
                with tarfile.open(archive) as bundle:
                    for member in bundle:
                        output=target/member.name
                        if not output.resolve().is_relative_to(target.resolve()) or not (member.isdir() or member.isfile()):
                            raise UpdateError('Git source archive contains an unsafe path or link')
                        if member.isdir():output.mkdir(parents=True,exist_ok=True)
                        else:
                            output.parent.mkdir(parents=True,exist_ok=True)
                            with bundle.extractfile(member) as body, output.open('wb') as file:shutil.copyfileobj(body,file)
                            output.chmod(member.mode & 0o777)
                manifests[repository]={str(p.relative_to(target)):digest(p) for p in target.rglob('*') if p.is_file()}
                manifests[repository]['git_head']=commit
                continue
            names=set(p.decode() for p in self.runner.run(['git','-C',source,'ls-files','--cached','--others','--exclude-standard','-z']).stdout.split(b'\0') if p)
            # Generated wrappers can be ignored by Git and still be needed in the image.
            if repository=='cmccdb-schema':
                names.update(str(p.relative_to(source)) for p in (source/'cmccdb_schema/proto').glob('*_pb2.*'))
            manifests[repository]={}
            for name in sorted(names):
                path=source/name
                if not path.is_file():raise UpdateError('Tracked source file is missing: '+str(path))
                if path.is_symlink():raise UpdateError('Source symlinks need a separately reviewed build context: '+str(path))
                target=destination/repository/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)
                manifests[repository][name]=digest(target)
            manifests[repository]['git_head']=self.runner.run(['git','-C',source,'rev-parse','HEAD']).stdout.decode().strip()
        write_json(self.folder/'candidate-source-sha256.json',manifests)
        return destination

    def new_worker(self,action,database,baseline=None):
        args=['run','--rm',*self.tool_user,'--interactive','--network',self.network,'--env-file',str(self.folder/'worker.private.env'),
            '--volume',str(self.folder/'snapshots')+':/app/backups:z','--entrypoint','/opt/venv/bin/python',self.candidate_image,'-',action,database]
        if baseline:args += ['--baseline','/app/backups/'+baseline]
        return self.result(self.command(*args,data=self.worker))

    def immutable_database(self):
        current=self.inspect(self.db_id)
        if not same_image(current['Image'],self.db_image) or current.get('Mounts')!=self.db.get('Mounts') or not current['State']['Running']:
            raise UpdateError('Database container changed during backend update')

    def execute(self):
        plan=self.discover()
        if self.args.plan:
            print(json.dumps(plan,indent=2)); return plan
        self.archive_root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if shutil.disk_usage(self.archive_root).free<self.archive_minimum:
            raise UpdateError('Insufficient archive disk space for images and database backups')
        locks=self.archive_root/'.locks'; locks.mkdir(mode=0o700,exist_ok=True)
        with (locks/(self.cluster+'.lock')).open('a') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise UpdateError('Another update owns this PostgreSQL cluster') from error
            stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
            self.folder=self.archive_root/(stamp+'-'+self.args.target+'-'+uuid.uuid4().hex[:8])
            self.folder.mkdir(mode=0o700)
            self.runner.logfile=self.folder/'update.log'
            self.journal={**plan,'phase':'preflight','created_at':datetime.now(timezone.utc).isoformat(),
                          'archive':str(self.folder),'data_started':False}
            self.state('archiving')
            try:
                return self.update()
            except BaseException:
                # After any live migration attempt, an interrupted transaction may
                # have committed. Hold the backend stopped; never restore over data.
                try:
                    if self.data_started:
                        self.compose('stop',self.web_service,file=self.folder/'release-compose.private.json',check=False)
                    elif self.web_stopped:
                        self.command('start',self.web_id,check=False)
                except UpdateError:
                    print('Recovery command failed; inspect the saved journal and container state',file=sys.stderr)
                self.state('failed',data_started=self.data_started,
                    recovery='Backend stop requested; inspect journal/backups before recovery' if self.data_started
                    else 'Original backend restart requested if it had been stopped')
                raise

    def update(self):
        write_json(self.folder/'old-compose.private.json',literal_config(self.config))
        for image,name in [(self.db_image,'old-database-image.tar'),(self.old_image,'old-backend-image.tar')]:
            self.command('image','save','--output',str(self.folder/name),image)
            if not (self.folder/name).stat().st_size:raise UpdateError('Image archive is empty')
        with (self.folder/'old-source.tar.gz').open('wb') as output:
            self.command('exec',self.web_id,'tar','--exclude=node_modules','--exclude=__pycache__',
                '--exclude=.snapshots','--exclude=.pg-tools','-czf','-','-C','/app','cmccdb-interface','cmccdb-schema',output=output)
        with tarfile.open(self.folder/'old-source.tar.gz') as source_archive:
            for member in source_archive:
                path=Path(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                    raise UpdateError('Old source archive contains a link or unsafe path; inspect it before updating')
        context=self.snapshot_source()
        # Recheck the old schema after freezing the candidate source.
        for database in self.databases:self.old_worker('probe',database)
        build_target=self.args.build_target or TARGETS[self.args.target][3]
        self.candidate_image='localhost/cmccdb-release:'+self.folder.name.lower()
        self.state('building_candidate',candidate_image=self.candidate_image)
        build=['build','--target',build_target,'--tag',self.candidate_image,
               '--file',str(context/'cmccdb-interface/cmccdb_interface/Dockerfile')]
        if self.engine=='podman':build += ['--ignorefile',str(context/'cmccdb-interface/cmccdb_interface/Dockerfile.dockerignore')]
        self.command(*build,str(context),timeout=7200)
        self.candidate_id=json.loads(self.command('image','inspect',self.candidate_image).stdout)[0]['Id']
        release_config=frozen_config(self.config,self.args.target,self.candidate_image,self.project)
        release_config['services'][self.db_service]['image']=self.db_image
        write_json(self.folder/'release-compose.private.json',literal_config(release_config))
        (self.folder/'snapshots').mkdir(mode=0o700)
        private_env={k:self.pg_env[k] for k in ['POSTGRES_USER','POSTGRES_PASSWORD']}
        private_env.update(POSTGRES_HOST=self.database_ip,POSTGRES_PORT=self.pg_env.get('POSTGRES_PORT','5432'),
            CMCCDB_RELEASE_TARGET=self.args.target,CMCCDB_EXPECTED_CLUSTER=self.cluster,
            CMCCDB_SNAPSHOT_DIR='/app/backups',CMCCDB_POSTGRES_RDKIT=self.pg_env.get('CMCCDB_POSTGRES_RDKIT','1'),**OFF)
        if any('\n' in value or '\r' in value for value in private_env.values()):
            raise UpdateError('Multiline connection settings are not supported by container env files')
        (self.folder/'worker.private.env').write_text(''.join(k+'='+v+'\n' for k,v in private_env.items()))
        self.immutable_database()
        self.state('stopping_backend',candidate_image_id=self.candidate_id)
        self.web_stopped=True
        self.command('stop','--time','60',self.web_id)
        self.baselines={}
        for database in self.databases:
            self.state('backing_up_'+database)
            # A stopped container cannot exec; use a maintenance-only copy of the
            # OLD image with its archived effective source and original environment.
            self.baselines[database]=self.backup_old(database)
        for database,data in self.baselines.items():
            self.state('rehearsing_'+database)
            result=self.new_worker('rehearse',data['restore_verification']['database'],'baseline-'+database+'.json')
            write_json(self.folder/('rehearsal-'+database+'.json'),result)
        self.immutable_database()
        for database in self.databases:
            self.data_started=True
            self.state('migrating_'+database,data_started=True)
            result=self.new_worker('apply',database,'baseline-'+database+'.json')
            write_json(self.folder/('migration-'+database+'.json'),result)
        self.immutable_database()
        self.state('publishing_backups')
        self.publish_backups(release_config)
        write_json(self.folder/'release-compose.private.json',literal_config(release_config))
        self.state('starting_candidate')
        self.compose('up','--detach','--no-deps','--no-build','--force-recreate',self.web_service,
            file=self.folder/'release-compose.private.json')
        values=self.compose('ps','--quiet',self.web_service,file=self.folder/'release-compose.private.json').stdout.decode().split()
        if len(values)!=1 or not same_image(self.inspect(values[0])['Image'],self.candidate_id):
            raise UpdateError('Compose did not start the expected immutable backend image')
        new_web=values[0]
        self.state('checking_backend',new_web_container=new_web)
        deadline=time.monotonic()+self.args.health_timeout
        for database in self.databases:
            while True:
                try:
                    result=self.result(self.command('exec','--interactive','--env','CMCCDB_RELEASE_TARGET='+self.args.target,
                        '--env','CMCCDB_EXPECTED_CLUSTER='+self.cluster,new_web,'/opt/venv/bin/python','-','http',database,data=self.worker))
                    write_json(self.folder/('health-'+database+'.json'),result);break
                except UpdateError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(2)
        self.immutable_database()
        checksums={str(p.relative_to(self.folder)):digest(p) for p in self.folder.rglob('*') if p.is_file()
                   and p.name not in {'release.json','update.log','CHECKSUMS.json'}}
        write_json(self.folder/'CHECKSUMS.json',checksums)
        self.state('complete',data_started=True,database_container_preserved=True)
        write_json(self.archive_root/('current-'+self.args.target+'.json'),self.journal)
        print('Release and recovery files: '+str(self.folder),flush=True)
        return self.journal

    def backup_old(self,database):
        # Extract trusted, self-created source archive to the private release folder.
        # GNU tar inside an image avoids host extraction of symlinks/untrusted paths.
        old_source=self.folder/'old-source';old_source.mkdir(exist_ok=True)
        self.command('run','--rm',*self.tool_user,'--volume',str(self.folder)+':/release:z','--entrypoint','tar',self.old_image,
            '--no-same-owner','--no-same-permissions','-xzf','/release/old-source.tar.gz','-C','/release/old-source')
        args=['run','--rm',*self.tool_user,'--interactive','--network',self.network,'--env-file',str(self.folder/'worker.private.env'),
              '--volume',str(self.folder/'snapshots')+':/app/backups:z',
              '--volume',str(old_source/'cmccdb-interface')+':/app/cmccdb-interface:ro,z',
              '--volume',str(old_source/'cmccdb-schema')+':/app/cmccdb-schema:ro,z',
              '--entrypoint','/opt/venv/bin/python',self.old_image,'-','backup',database]
        data=self.result(self.command(*args,data=self.worker))
        write_json(self.folder/'snapshots'/('baseline-'+database+'.json'),data)
        write_json(self.folder/('baseline-'+database+'.json'),data)
        return data

    def publish_backups(self,release_config):
        # Keep API snapshot IDs discoverable across releases, while retaining
        # complete offline copies under this date-stamped archive.
        name=self.project+'-'+self.args.target+'-release-backups'
        self.command('volume','create',name)
        code="""from pathlib import Path
import shutil,uuid
source=Path('/release');destination=Path('/app/backups')
for directory in source.iterdir():
    if not directory.is_dir():continue
    uuid.UUID(directory.name)
    if (destination/directory.name).exists():raise ValueError('Snapshot ID already exists')
    shutil.copytree(directory,destination/directory.name)
"""
        # This helper uses the app image's normal user to own the API store.
        self.command('run','--rm','--volume',str(self.folder/'snapshots')+':/release:ro,z',
            '--volume',name+':/app/backups','--entrypoint','/opt/venv/bin/python',self.candidate_image,'-c',code)
        release_config.setdefault('volumes',{})['release-backups']={'external':True,'name':name}
        web=release_config['services'][self.web_service]
        web['volumes']=[v for v in web.get('volumes',[]) if v['target']!='/app/backups']
        web['volumes'].append({'type':'volume','source':'release-backups','target':'/app/backups'})
        web['environment']['CMCCDB_SNAPSHOT_DIR']='/app/backups'
        self.journal['backup_volume']=name


def arguments(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',choices=sorted(TARGETS))
    parser.add_argument('--engine',choices=['podman','docker'],default=os.getenv('CONTAINER_ENGINE','podman'))
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1],help='cmccdb-interface checkout; cmccdb-schema must be its sibling')
    parser.add_argument('--archive-root',type=Path,default=Path(os.environ['CMCCDB_ARCHIVES']) if os.getenv('CMCCDB_ARCHIVES') else None)
    parser.add_argument('--build-target',choices=['production','preview'],help='Use preview to test the same image build against either stack')
    parser.add_argument('--project-name',help='Existing Compose project name, if it differs from the compose-file default')
    parser.add_argument('--interface-ref',help='Build this existing Git ref without modifying the live checkout')
    parser.add_argument('--schema-ref',help='Build this existing Git ref without modifying the live checkout')
    parser.add_argument('--plan',action='store_true',help='Read-only deployment/schema checks; no archives, build, stop or migrations')
    parser.add_argument('--health-timeout',type=int,default=180)
    return parser.parse_args(argv)


def main(argv=None):
    if sys.version_info<(3,11):raise SystemExit('Use Python 3.11 or newer')
    os.umask(0o077)
    instance=None
    try:
        instance=Release(arguments(argv));instance.execute()
    except (UpdateError,ValueError,KeyError,OSError) as error:
        print(str(error),file=sys.stderr)
        if instance and instance.folder:print('Recovery files: '+str(instance.folder),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':sys.exit(main())
