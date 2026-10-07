"""Deployment-order and failure tests; no real container commands are executed."""
import copy
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch
import pytest

spec=importlib.util.spec_from_file_location('backend_release',Path(__file__).with_name('update_backend.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class FakeEngine:
    def __init__(self,target='main',failure=None):
        self.target=target;self.failure=failure;self.calls=[];self.logfile=None;self.started=False
        _,web,db,_=release.TARGETS[target]
        env=['POSTGRES_HOST='+db,'POSTGRES_USER=postgres','POSTGRES_PASSWORD=p$word','POSTGRES_DATABASE=cmcc']
        labels=lambda service:{'com.docker.compose.project':'cmccdb_interface','com.docker.compose.service':service}
        self.web={'Id':'web-old','Name':'web-old','Image':'oldweb','Config':{'Env':env,'Labels':labels(web)},
                  'State':{'Running':True},'Mounts':[], 'NetworkSettings':{'Networks':{'net':{}}}}
        self.db={'Id':'db','Name':'db','Image':'olddb','Config':{'Env':['PGDATA=/data'],'Labels':labels(db)},
                 'State':{'Running':True},'Mounts':[{'Destination':'/data','Source':'/database/main','Type':'bind'}],
                 'NetworkSettings':{'Networks':{'net':{'Aliases':[db],'IPAddress':'10.0.0.2'}}}}
        self.new=copy.deepcopy(self.web);self.new.update(Id='web-new',Image='sha256:candidate')
        self.extra=[]
        self.config={'name':'cmccdb_interface','services':{
            web:{'environment':{'POSTGRES_PASSWORD':'wrong shell value'},'image':'floating',
                 'volumes':[{'type':'bind','source':'/live/schema','target':'/app/cmccdb-schema/cmccdb_schema'},
                            {'type':'bind','source':'/credentials','target':'/app/credentials'}]},
            db:{'image':'floatingdb','environment':{},'volumes':[]}},'networks':{'default':{}},'volumes':{}}

    def run(self,args,data=None,output=None,timeout=None,check=True):
        args=list(map(str,args));self.calls.append(args);body=b''
        if args[0]=='git':
            body=b'file.txt\0' if 'ls-files' in args else b'0123456789abcdef\n'
        elif 'info' in args:body=json.dumps({'host':{'security':{'rootless':True}},'SecurityOptions':['name=rootless']}).encode()
        elif 'config' in args:body=json.dumps(self.config).encode()
        elif args[1:3]==['ps','--quiet']:body=('web-old\ndb\n'+''.join(i['Id']+'\n' for i in self.extra)).encode()
        elif 'ps' in args:body=(b'web-new\n' if self.started else (b'db\n' if args[-1].startswith('database') else b'web-old\n'))
        elif args[1:3]==['container','inspect']:
            values={'web-old':self.web,'db':self.db,'web-new':self.new}
            values.update({i['Id']:i for i in self.extra})
            body=json.dumps([values[v] for v in args[3:]]).encode()
        elif args[1:3]==['image','inspect']:body=json.dumps([{'Id':'sha256:candidate','Size':100}]).encode()
        elif args[1:3]==['image','save']:Path(args[args.index('--output')+1]).write_bytes(b'image archive')
        elif 'psql' in args:
            query=args[-1]
            body=b'42\n' if 'system_identifier' in query else (b'cmcc\nstaging\n' if 'SELECT datname' in query else b'100\n')
        elif args[1]=='exec' and 'tar' in args:
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w:gz') as z:
                info=tarfile.TarInfo('cmccdb-schema/file.txt');info.size=3;z.addfile(info,io.BytesIO(b'old'))
            body=buffer.getvalue()
        elif data:
            action=next(a for a in ['probe','backup','rehearse','apply','http',
                'initial_prepare','legacy_backup','replay','coverage','promote'] if a in args)
            if self.failure==action:raise release.UpdateError('Injected '+action+' failure')
            result={'required':False,'compatible':True,'snapshot_id':None}
            if action in {'initial_prepare','replay','coverage'}:result={'ok':True}
            if action=='promote':result={'promoted':True,'retained_databases':{'cmcc':'retained-cmcc','staging':'retained-staging'}}
            if action=='backup':result={'id':'00000000-0000-0000-0000-000000000001' if args[-1]=='cmcc' else '00000000-0000-0000-0000-000000000002',
                'database':args[-1],'verified':True,'restore_verification':{'verified':True,'database':'cmccdb_restore_'+args[-1]}}
            body=('CMCCDB_RELEASE_RESULT='+json.dumps(result)+'\n').encode()
        elif 'up' in args:self.started=True
        elif 'build' in args and self.failure=='build':raise release.UpdateError('Injected build failure')
        if output:
            output.write(body);body=None
        return subprocess.CompletedProcess(args,0,body,b'')


def fixture(tmp_path,target='main',failure=None,engine='podman'):
    root=tmp_path/'cmccdb-interface';(root/'cmccdb_interface').mkdir(parents=True)
    (root/'cmccdb_interface'/release.TARGETS[target][0]).write_text('services: {}')
    for repo in [root,tmp_path/'cmccdb-schema']:
        repo.mkdir(exist_ok=True);(repo/'file.txt').write_text('candidate')
    args=release.arguments([target,'--source-root',str(root),'--engine',engine,'--archive-root',str(tmp_path/'archives')])
    fake=FakeEngine(target,failure)
    return release.Release(args,fake),fake


@pytest.mark.parametrize('target',['main','preview'])
@pytest.mark.parametrize('engine',['podman','docker'])
def test_complete_update_preserves_database_and_archives_code(tmp_path,target,engine):
    update,fake=fixture(tmp_path,target,engine=engine)
    result=update.execute()
    assert result['phase']=='complete' and result['database_container_preserved']
    assert (update.folder/'old-database-image.tar').is_file()
    assert (update.folder/'old-backend-image.tar').is_file()
    assert (update.folder/'old-source.tar.gz').is_file()
    assert (update.folder/'candidate-source/cmccdb-schema/file.txt').read_text()=='candidate'
    assert (update.archive_root/('current-'+target+'.json')).is_file()
    calls=fake.calls
    # Both backups and both rehearsals precede the first live migration.
    live=next(i for i,c in enumerate(calls) if 'apply' in c)
    assert sum('backup' in c for c in calls[:live])==2
    assert sum('rehearse' in c for c in calls[:live])==2
    assert not any(c[1:3]==['stop','db'] or ('database' in c and 'up' in c) for c in calls)
    ups=[c for c in calls if 'up' in c]
    assert len(ups)==1 and '--no-deps' in ups[0] and '--no-build' in ups[0]
    cfg=json.loads((update.folder/'release-compose.private.json').read_text())
    web=cfg['services'][update.web_service]
    assert web['environment']['POSTGRES_PASSWORD']=='p$$word'
    assert web['environment']['CMCCDB_DEV_ENDPOINTS']=='false'
    assert not any(release.source_mount(v['target']) for v in web['volumes'])


@pytest.mark.parametrize('failure',['backup','rehearse'])
def test_failure_before_live_sql_restarts_old_backend(tmp_path,failure):
    update,fake=fixture(tmp_path,failure=failure)
    with pytest.raises(release.UpdateError):update.execute()
    assert ['podman','start','web-old'] in fake.calls
    assert not any('apply' in c for c in fake.calls)
    assert not update.data_started


def test_unknown_migration_result_holds_backend_stopped(tmp_path):
    update,fake=fixture(tmp_path,failure='apply')
    with pytest.raises(release.UpdateError):update.execute()
    assert update.data_started
    assert ['podman','start','web-old'] not in fake.calls
    assert not any('up' in c for c in fake.calls)
    assert json.loads((update.folder/'release.json').read_text())['phase']=='failed'


def test_preview_image_can_target_main(tmp_path):
    update,fake=fixture(tmp_path)
    update.args.build_target='preview';update.execute()
    assert any('build' in c and c[c.index('--target')+1]=='preview' for c in fake.calls)


def test_plan_is_read_only(tmp_path):
    update,fake=fixture(tmp_path);update.args.plan=True
    update.execute()
    assert not update.archive_root.exists()
    assert not any(c[1] in {'build','run','stop','start','save'} for c in fake.calls)


def test_dev_cli_target_is_refused():
    with pytest.raises(SystemExit):release.arguments(['dev'])


@pytest.mark.parametrize('location',['web','db'])
def test_mislabeled_dev_container_is_refused(tmp_path,location):
    update,fake=fixture(tmp_path)
    getattr(fake,location)['Config']['Labels']['com.docker.compose.project']='cmccdb-dev'
    with pytest.raises(release.UpdateError,match='development'):update.discover()
    assert not any('probe' in c for c in fake.calls)


def test_live_cluster_mutation_is_detected(tmp_path):
    update,fake=fixture(tmp_path);update.discover()
    fake.db['Image']='changed'
    with pytest.raises(release.UpdateError,match='changed'):update.immutable_database()


def test_literal_compose_values_are_not_interpolated_twice():
    assert release.literal_config({'password':'$TOKEN:${value}'})=={'password':'$$TOKEN:$${value}'}


def test_archive_disk_shortage_never_stops_backend(tmp_path):
    update,fake=fixture(tmp_path)
    with patch.object(release.shutil,'disk_usage',return_value=type('Usage',(),{'free':0})()):
        with pytest.raises(release.UpdateError,match='disk'):update.execute()
    assert not any(c[1]=='stop' for c in fake.calls)


def test_image_ids_accept_podman_or_docker_prefix():
    assert release.same_image('sha256:abc','abc')


def test_worker_rejects_dev_before_importing_database_libraries(monkeypatch):
    worker_spec=importlib.util.spec_from_file_location('worker',Path(__file__).with_name('backend_update_worker.py'))
    worker=importlib.util.module_from_spec(worker_spec);worker_spec.loader.exec_module(worker)
    monkeypatch.setenv('CMCCDB_RELEASE_TARGET','dev')
    with pytest.raises(ValueError,match='main or preview'):worker.execute('backup','cmcc')


def test_post_migration_health_failure_stops_candidate_without_restart(tmp_path):
    update,fake=fixture(tmp_path,failure='http');update.args.health_timeout=0
    with pytest.raises(release.UpdateError):update.execute()
    assert fake.started and update.data_started
    assert ['podman','start','web-old'] not in fake.calls
    assert any('compose' in c and 'stop' in c and 'web' in c for c in fake.calls)
    assert (update.folder/'migration-staging.json').exists()


def test_build_failure_keeps_old_backend_running(tmp_path):
    update,fake=fixture(tmp_path,failure='build')
    with pytest.raises(release.UpdateError):update.execute()
    assert not update.web_stopped
    assert not any(c[1]=='stop' for c in fake.calls)
    assert (update.folder/'old-database-image.tar').is_file()


def test_shared_dev_database_volume_is_rejected(tmp_path):
    update,fake=fixture(tmp_path)
    other=copy.deepcopy(fake.db);other.update(Id='dev-db',Name='cmccdb-dev-database')
    other['Config']['Labels']['com.docker.compose.service']='database_dev'
    fake.extra=[other]
    with pytest.raises(release.UpdateError,match='shares persistence'):update.discover()
    assert not any('probe' in c for c in fake.calls)


def test_requested_project_mismatch_is_rejected(tmp_path):
    update,fake=fixture(tmp_path)
    update.args.project_name='another-production-project'
    with pytest.raises(release.UpdateError,match='different project'):update.discover()
    assert not any('probe' in c for c in fake.calls)


def committed_sources(tmp_path):
    update,_=fixture(tmp_path)
    runner=release.Runner()
    for name in ['cmccdb-interface','cmccdb-schema']:
        repository=tmp_path/name
        runner.run(['git','-c','init.templateDir=','init','--quiet',repository])
        runner.run(['git','-C',repository,'add','.'])
        runner.run(['git','-C',repository,'-c','user.name=CMCCDB test',
            '-c','user.email=cmccdb-test@example.invalid','-c','commit.gpgsign=false',
            'commit','--quiet','-m','Frozen candidate fixture'])
    update.args.interface_ref=update.args.schema_ref='HEAD'
    update.runner=runner
    update.folder=tmp_path/'release';update.folder.mkdir()
    return update


def test_git_refs_build_committed_sources_without_changing_live_checkouts(tmp_path):
    update=committed_sources(tmp_path)
    for name in ['cmccdb-interface','cmccdb-schema']:
        (tmp_path/name/'file.txt').write_text('still-live source')
        (tmp_path/name/'uncommitted.txt').write_text('local file')
    context=update.snapshot_source()
    for name in ['cmccdb-interface','cmccdb-schema']:
        assert (context/name/'file.txt').read_text()=='candidate'
        assert not (context/name/'uncommitted.txt').exists()
        assert (tmp_path/name/'file.txt').read_text()=='still-live source'


def test_git_source_archive_rejects_symlinks(tmp_path):
    update=committed_sources(tmp_path)
    repository=tmp_path/'cmccdb-interface'
    (repository/'linked.txt').symlink_to('file.txt')
    update.runner.run(['git','-C',repository,'add','linked.txt'])
    update.runner.run(['git','-C',repository,'-c','user.name=CMCCDB test',
        '-c','user.email=cmccdb-test@example.invalid','-c','commit.gpgsign=false',
        'commit','--quiet','-m','Symlink fixture'])
    with pytest.raises(release.UpdateError,match='unsafe path or link'):update.snapshot_source()


def replay_fixture(tmp_path,target='main',failure=None):
    update,fake=fixture(tmp_path,target=target,failure=failure)
    for database in ['cmcc','staging']:
        folder=tmp_path/'incoming'/database;folder.mkdir(parents=True)
        (folder/'contribution.xlsx').write_bytes(b'placeholder for orchestration')
        setattr(update.args,'resubmit_folder' if database=='cmcc' else 'staging_resubmit_folder',folder)
    update.args.uploader_name='Migration Test';update.args.uploader_email='migration@example.invalid'
    update.replay_mode=True
    return update,fake


@pytest.mark.parametrize('target',['main','preview'])
def test_initial_replay_does_not_need_old_backend_helpers(tmp_path,target):
    update,fake=replay_fixture(tmp_path,target=target,failure='probe')
    result=update.execute()
    assert result['phase']=='complete' and result['migration_mode']=='xlsx_replay'
    assert not any('probe' in c or 'apply' in c for c in fake.calls)
    assert sum('replay' in c for c in fake.calls)==2
    stop=next(i for i,c in enumerate(fake.calls) if c[1]=='stop')
    assert sum('replay' in c for c in fake.calls[:stop])==2
    promote=next(i for i,c in enumerate(fake.calls) if 'promote' in c)
    assert sum('legacy_backup' in c for c in fake.calls[:promote])==2
    assert any('coverage' in c for c in fake.calls[:promote])
    assert (update.folder/'replay/inputs/cmcc/contribution.xlsx').exists()
    assert result['retained_databases']['cmcc']=='retained-cmcc'


@pytest.mark.parametrize('failure',['replay','legacy_backup','coverage'])
def test_initial_failures_leave_legacy_database_selected(tmp_path,failure):
    update,fake=replay_fixture(tmp_path,failure=failure)
    with pytest.raises(release.UpdateError):update.execute()
    assert not update.data_started
    assert not any('promote' in c for c in fake.calls)
    assert not any('up' in c for c in fake.calls)
    if update.web_stopped:assert ['podman','start','web-old'] in fake.calls


def test_unknown_promotion_result_holds_backend_stopped(tmp_path):
    update,fake=replay_fixture(tmp_path,failure='promote')
    with pytest.raises(release.UpdateError):update.execute()
    assert update.data_started
    assert ['podman','start','web-old'] not in fake.calls
    assert not any('up' in c for c in fake.calls)


def test_nonempty_staging_requires_its_own_replay_folder(tmp_path):
    update,fake=replay_fixture(tmp_path)
    update.args.staging_resubmit_folder=None
    with pytest.raises(release.UpdateError,match='Nonempty staging'):update.discover()
    assert not any(c[1] in {'build','stop'} for c in fake.calls)


def test_resume_after_promotion_attempt_is_refused(tmp_path):
    update,fake=replay_fixture(tmp_path,failure='promote')
    with pytest.raises(release.UpdateError):update.execute()
    previous=update.folder
    second,_=replay_fixture(tmp_path/'retry')
    second.args.resume_import=previous
    with pytest.raises(release.UpdateError,match='pre-promotion'):second.execute()


def test_replay_cli_requires_uploader_attribution():
    with pytest.raises(SystemExit):release.arguments(['preview','--resubmit-folder','incoming'])
