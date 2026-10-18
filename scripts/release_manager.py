#!/usr/bin/env python3
"""Freeze preview, commit accepted data, prepare an isolated main and switch routing.

Run on the deployment host, using its existing rootless Podman/Docker account.
No source checkout is changed, no live database is overwritten, and Git push is separate.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
from pathlib import Path

from update_backend import OFF, UpdateError, dev, digest, env_dict, label, literal_config, source_mount, write_json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def coverage(main, candidate):
    result = {}
    for database in main:
        if database not in candidate:
            raise UpdateError('Preview is missing main database ' + database)
        old, new = main[database], candidate[database]
        result[database] = {}
        for kind in ('datasets', 'reactions'):
            missing = sorted(set(old[kind]) - set(new[kind]))
            if missing:
                raise UpdateError('Preview is missing main ' + database + ' ' + kind + ': ' + ', '.join(missing[:20]))
            result[database][kind] = {'added': sorted(set(new[kind]) - set(old[kind])),
                'changed': {key: {'main': old[kind][key], 'candidate': new[kind][key]}
                            for key in sorted(old[kind]) if old[kind][key] != new[kind][key]}}
    return result


def route_config(original, old_upstream, new_upstream):
    """Change only exact old-main proxy_pass directives, preserving preview routing."""
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+:[0-9]{1,5}', old_upstream):
        raise UpdateError('Invalid old upstream')
    if not re.fullmatch(r'cmccdb-release-[a-f0-9]{12}-web:80', new_upstream):
        raise UpdateError('Invalid candidate upstream')
    pattern = r'(?m)^(\s*proxy_pass\s+)http://' + re.escape(old_upstream) + r'(\s*;)'
    updated, count = re.subn(pattern, lambda m: m[1] + 'http://' + new_upstream + m[2], original)
    if count == 0:
        raise UpdateError('No exact main upstream found; proxy configuration needs review')
    return updated


def checked_files(root, manifest):
    root = Path(root).resolve()
    for name, expected in manifest.items():
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise UpdateError('Unsafe release file path')
        if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
            raise UpdateError('Missing, linked or escaping release file: ' + name)
        if digest(path) != expected:
            raise UpdateError('Release file changed: ' + name)


def input_members(archive):
    """Validate our own input archive before extracting; never follow archive links."""
    result = {}
    with tarfile.open(archive, 'r:gz') as source:
        for member in source:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in {'cmccdb-data', 'tmp'}:
                raise UpdateError('Unexpected input archive path')
            if not member.isdir() and not member.isfile():
                raise UpdateError('Input archive contains a symlink or special file; review it before promotion')
            if member.isfile():
                if member.name in result:
                    raise UpdateError('Duplicate input archive member')
                hasher = hashlib.sha256()
                with source.extractfile(member) as stream:
                    for body in iter(lambda: stream.read(1024 * 1024), b''):
                        hasher.update(body)
                result[member.name] = hasher.hexdigest()
    return result


def checked_export(release, frozen):
    expected = {name for name in frozen if name.startswith('data-export/')}
    actual = set()
    for path in (release / 'data-export').rglob('*'):
        if path.is_symlink():
            raise UpdateError('Public data export contains a symlink')
        if path.is_file():
            actual.add(str(path.relative_to(release)))
    if actual != expected:
        raise UpdateError('Public data export has unexpected or missing files')
    checked_files(release, {name: frozen[name] for name in expected})


def merge_inputs(archives, release):
    files = {}
    for archive in archives:
        manifest = input_members(archive)
        with tarfile.open(archive, 'r:gz') as source:
            for member in source:
                if not member.isfile():
                    continue
                parts = Path(member.name).parts
                name = str(Path('runtime-data' if parts[0] == 'cmccdb-data' else 'tmp', *parts[1:]))
                if name in files:
                    if files[name] != manifest[member.name]:
                        raise UpdateError('Main/preview input file conflict: ' + member.name)
                    continue
                target = release / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with source.extractfile(member) as stream, target.open('xb') as output:
                    shutil.copyfileobj(stream, output)
                files[name] = manifest[member.name]
    return files


@contextlib.contextmanager
def release_lock(root):
    root = Path(root).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / '.release-manager.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError('Another release-manager operation is running') from error
        yield


class Manager:
    def __init__(self, root, engine='podman'):
        self.root = Path(root).resolve()
        self.engine = engine

    def run(self, args, data=None, check=True, timeout=3600, output=None):
        result = subprocess.run([str(x) for x in args], input=data, stdout=output or subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
        if check and result.returncode:
            # Do not print potentially secret environment/Compose output into terminal logs.
            raise UpdateError('Command failed (' + str(result.returncode) + '): ' + str(args[0]) +
                              '; inspect the retained private release files')
        return result

    def command(self, *args, **kwargs):
        return self.run([self.engine, *args], **kwargs)

    def inspect(self, identifier):
        return json.loads(self.command('container', 'inspect', identifier).stdout)[0]

    def lock_clusters(self, *clusters):
        locks = self.root / '.locks'
        locks.mkdir(mode=0o700, exist_ok=True)
        for cluster in sorted(set(clusters)):
            if not str(cluster).isdigit():
                raise UpdateError('Invalid cluster lock identity')
            lock = self.locks.enter_context((locks / (cluster + '.lock')).open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise UpdateError('A backend update or release already owns this cluster') from error

    def deployment(self, web_id, database_id):
        web, db = self.inspect(web_id), self.inspect(database_id)
        if any(dev(item) or not item['State']['Running'] for item in (web, db)):
            raise UpdateError('Expected running main/preview containers without development switches')
        if not label(web, 'project') or label(web, 'project') != label(db, 'project'):
            raise UpdateError('Web and database must belong to the same Compose project')
        if label(web, 'service') not in {'web', 'web_preview'} or label(db, 'service') not in {'database', 'database_preview'}:
            raise UpdateError('Unexpected web/database service identity')
        env = env_dict(web)
        if not all(env.get(key) for key in ('POSTGRES_HOST', 'POSTGRES_USER', 'POSTGRES_PASSWORD')):
            raise UpdateError('Explicit PostgreSQL connection settings are required')
        if env.get('POSTGRES_DATABASE', 'cmcc') != 'cmcc':
            raise UpdateError('Expected the cmcc application database')
        if env.get('CMCCDB_AUXILIARY_DIR', '/app/cmccdb-data/aux') != '/app/cmccdb-data/aux':
            raise UpdateError('Custom auxiliary file locations need an explicit migration plan')
        networks = db.get('NetworkSettings', {}).get('Networks', {})
        common = set(networks) & set(web.get('NetworkSettings', {}).get('Networks', {}))
        matched = [(name, networks[name]) for name in sorted(common)
                   if env['POSTGRES_HOST'] in (networks[name].get('Aliases') or [])
                   or env['POSTGRES_HOST'] == networks[name].get('IPAddress')]
        if not matched:
            raise UpdateError('Cannot prove which PostgreSQL container the web uses')
        network, connection = matched[0]
        pgdata = env_dict(db).get('PGDATA', '/var/lib/postgresql/data')
        mounts = [m for m in db.get('Mounts', [])
                  if pgdata == m['Destination'] or pgdata.startswith(m['Destination'] + '/')]
        if not mounts or not connection.get('IPAddress'):
            raise UpdateError('Database persistence or network identity is ambiguous')
        user = env_dict(db).get('POSTGRES_USER', 'postgres')
        cluster = self.command('exec', db['Id'], 'psql', '-U', user, '-d', 'postgres', '-Atc',
            'SELECT system_identifier FROM pg_control_system()').stdout.decode().strip()
        if not cluster.isdigit():
            raise UpdateError('Cannot prove PostgreSQL cluster identity')
        databases = self.command('exec', db['Id'], 'psql', '-U', user, '-d', 'postgres', '-Atc',
            "SELECT datname FROM pg_database WHERE datname IN ('cmcc','staging') ORDER BY datname").stdout.decode().split()
        if 'cmcc' not in databases:
            raise UpdateError('Main/preview has no cmcc database')
        running = self.command('ps', '--quiet').stdout.decode().split()
        if running:
            for other in json.loads(self.command('container', 'inspect', *running).stdout):
                if other['Id'] == db['Id'] or 'PGDATA' not in env_dict(other):
                    continue
                for left in mounts:
                    for right in other.get('Mounts', []):
                        a, b = left.get('Source'), right.get('Source')
                        if a and b and os.path.commonpath([a, b]) in {a, b}:
                            raise UpdateError('Database persistence is shared with another running cluster')
        return {'web': web['Id'], 'database': db['Id'], 'image': web['Image'], 'database_image': db['Image'],
            'network': network, 'host': connection['IPAddress'], 'cluster': cluster, 'databases': databases,
            'pg': {key: env[key] for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD')}, 'mounts': mounts,
            'rdkit': env.get('CMCCDB_POSTGRES_RDKIT', '1')}

    def worker(self, release, deployment, action, database, *extra):
        env = dict(deployment['pg'], POSTGRES_HOST=deployment['host'], POSTGRES_PORT='5432',
                   CMCCDB_EXPECTED_CLUSTER=deployment['cluster'], CMCCDB_SNAPSHOT_DIR='/release/snapshots',
                   CMCCDB_POSTGRES_RDKIT=deployment.get('rdkit', self.state['preview'].get('rdkit', '1')),
                   CMCCDB_DISABLE_GITHUB_BACKUPS='true', **OFF)
        if any('\n' in value or '\r' in value for value in env.values()):
            raise UpdateError('Multiline container environment values are unsupported')
        path = release / 'worker.private.env'
        path.write_text(''.join(key + '=' + value + '\n' for key, value in env.items()))
        path.chmod(0o600)
        mounts = []
        for name, target in (('runtime-data', '/app/cmccdb-data'), ('tmp', '/app/tmp')):
            if (release / name).is_dir():
                mounts += ['--volume', str(release / name) + ':' + target + ':ro,z']
        result = self.command('run', '--rm', '--network', deployment['network'],
            '--env-file', str(path), '--volume', str(release) + ':/release:z', *mounts,
            '--entrypoint', '/opt/venv/bin/python', self.state['image'],
            '-m', 'cmccdb_interface.database.release_data', action, database, *extra)
        lines = [line for line in result.stdout.decode().splitlines() if line.startswith('CMCCDB_RELEASE_RESULT=')]
        if len(lines) != 1:
            raise UpdateError('Worker did not return a single release receipt')
        return json.loads(lines[0].split('=', 1)[1])

    def archive_inputs(self, deployment, destination):
        with destination.open('wb') as output:
            self.command('run', '--rm', '--volumes-from', deployment['web'] + ':ro',
                '--entrypoint', 'tar', self.state['image'], '--exclude=.git', '-czf', '-',
                '-C', '/app', 'cmccdb-data', 'tmp', output=output)
        return input_members(destination)

    def save(self, release, phase, **values):
        self.state.update(values, phase=phase)
        write_json(release / 'release.private.json', self.state)

    def compose(self, release, *args):
        return self.command('compose', '--project-name', self.state['project'],
            '--file', str(release / 'compose.private.json'), *args)

    def candidate(self, release):
        db = self.inspect(self.state['candidate_database'])
        if db['Image'] != self.state['database_image'] or db.get('Mounts') != self.state['candidate_mounts']:
            raise UpdateError('Candidate database image or persistence changed')
        networks = db['NetworkSettings']['Networks']
        network = self.state['candidate_network']
        return {'pg': self.state['candidate_pg'], 'cluster': self.state['candidate_cluster'],
                'network': network, 'host': networks[network]['IPAddress']}

    def load(self, release):
        if Path(release).is_symlink():
            raise UpdateError('Release directory cannot be a symlink')
        release = Path(release).resolve()
        if release.parent != self.root or release.is_symlink():
            raise UpdateError('Release must be a direct child of the archive root')
        self.state = json.loads((release / 'release.private.json').read_text())
        if self.state['engine'] != self.engine:
            raise UpdateError('Use the same container engine as preparation')
        return release

    def prepare(self, args):
        preview_release = Path(args.preview_release).resolve()
        checked_files(preview_release, json.loads((preview_release / 'CHECKSUMS.json').read_text()))
        previous = json.loads((preview_release / 'release.json').read_text())
        if previous['phase'] != 'complete' or previous['target'] != 'preview':
            raise UpdateError('A completed immutable preview release is required')
        if Path(previous['archives']).resolve() != self.root:
            raise UpdateError('Use the same archive root as update_backend.sh so cluster locks are shared')
        preview = self.deployment(previous['new_web_container'], previous['database_container'])
        main = self.deployment(args.main_web, args.main_database)
        self.lock_clusters(main['cluster'], preview['cluster'])
        for key in ('cluster', 'database'):
            if preview[key] == main[key]:
                raise UpdateError('Main and preview are the same database cluster')
        for left in preview['mounts']:
            for right in main['mounts']:
                a, b = left['Source'], right['Source']
                if os.path.commonpath([a, b]) in {a, b}:
                    raise UpdateError('Main and preview share database persistence')
        web = self.inspect(preview['web'])
        if preview['image'] != previous['candidate_image_id']:
            raise UpdateError('Preview image changed since its completed release')
        if any(source_mount(m['Destination']) for m in web.get('Mounts', [])):
            raise UpdateError('Preview still mounts live source; use update_backend.sh first')
        if any(env_dict(web).get(key) != value for key, value in OFF.items()):
            raise UpdateError('Preview is not running a frozen production interface')
        proxy = self.inspect(args.proxy_container)
        if not proxy['State']['Running'] or label(proxy, 'service') != 'proxy':
            raise UpdateError('Expected the running Nginx proxy service')
        proxy_configs = [m for m in proxy.get('Mounts', []) if m['Destination'] == '/etc/nginx/nginx.conf']
        if len(proxy_configs) != 1 or proxy_configs[0].get('Type') != 'bind' or not proxy_configs[0].get('RW'):
            raise UpdateError('Proxy needs a persistent writable nginx.conf bind mount; see RELEASE_MANAGER.md')
        if args.proxy_network not in proxy['NetworkSettings']['Networks']:
            raise UpdateError('Proxy is not attached to the requested network')
        if self.engine == 'podman':
            net = json.loads(self.command('network', 'inspect', args.proxy_network).stdout)[0]
            if not net.get('dns_enabled'):
                raise UpdateError('Proxy network needs container DNS for candidate routing')
        original = self.command('exec', proxy['Id'], 'cat', '/etc/nginx/nginx.conf').stdout.decode()
        identity = uuid.uuid4().hex[:12]
        name = 'cmccdb-release-' + identity
        updated = route_config(original, args.old_upstream, name + '-web:80')
        if not 1024 <= args.port <= 65535:
            raise UpdateError('Candidate port must be between 1024 and 65535')
        release = self.root / name
        release.mkdir(mode=0o700)
        self.state = {'format': 1, 'id': identity, 'engine': self.engine, 'project': name,
            'image': preview['image'], 'database_image': preview['database_image'],
            'main': main, 'preview': preview, 'preview_release': str(preview_release),
            'proxy': proxy['Id'], 'proxy_image': proxy['Image'], 'port': args.port,
            'public_url': args.public_url.rstrip('/'), 'preview_stopped': False}
        (release / 'snapshots').mkdir(mode=0o700)
        (release / 'control').mkdir(mode=0o700)
        (release / 'control/read-only').write_text('Prepared release: writes disabled\n')
        (release / 'proxy-old.conf').write_text(original)
        (release / 'proxy-new.conf').write_text(updated)
        self.save(release, 'preparing')
        try:
            # Save software images before stopping preview. A failed prepare retains all artifacts.
            for image, output in ((self.state['image'], 'interface-image.tar'),
                                  (self.state['database_image'], 'database-image.tar')):
                self.command('image', 'save', '--output', str(release / output), image)
            shutil.copy2(preview_release / 'candidate-source-sha256.json', release / 'source-provenance.json')
            self.state['main_baseline'] = {db: self.worker(release, main, 'inventory', db)
                                           for db in main['databases']}
            self.state['main_inputs'] = self.archive_inputs(main, release / 'main-inputs.private.tar.gz')
            self.save(release, 'freezing_preview', preview_stopped=True)
            self.command('stop', '--time', '60', preview['web'])
            # Preserve originals/rejected inputs privately, separate from accepted public data.
            self.archive_inputs(preview, release / 'original-inputs.private.tar.gz')
            self.state['input_files'] = merge_inputs([release / 'main-inputs.private.tar.gz',
                release / 'original-inputs.private.tar.gz'], release)
            snapshots = {}
            for database in preview['databases']:
                snapshots[database] = self.worker(release, preview, 'snapshot', database)
            self.state['snapshots'] = snapshots
            self.command('start', preview['web'])
            self.save(release, 'restoring_candidate', preview_stopped=False)
            self.start_candidate(release, args.proxy_network)
            candidate = self.candidate(release)
            candidate_inventories = {}
            for database in snapshots:
                self.worker(release, candidate, 'restore', database, '--snapshot', snapshots[database]['id'])
                self.worker(release, candidate, 'verify', database)
                candidate_inventories[database] = self.worker(release, candidate, 'inventory', database, '--quiet')
            # Export exactly the accepted cmcc data. Original XLSX files stay in input archives.
            exported = self.worker(release, candidate, 'export', 'cmcc', '--output', '/release/data-export')
            review = {'id': identity, 'image': self.state['image'], 'database_image': self.state['database_image'],
                'main_fingerprint': fingerprint(self.state['main_baseline']),
                'candidate_fingerprint': fingerprint(candidate_inventories),
                'changes': coverage(self.state['main_baseline'], candidate_inventories),
                'data_export': exported, 'source_provenance_sha256': digest(release / 'source-provenance.json'),
                'snapshots': {db: {'id': item['id'], 'dump_sha256': item['dump_sha256']}
                              for db, item in snapshots.items()},
                'original_inputs_sha256': digest(release / 'original-inputs.private.tar.gz'),
                'proxy_config_sha256': digest(release / 'proxy-new.conf')}
            write_json(release / 'review.json', review)
            self.state.update(candidate_inventories=candidate_inventories, review_sha256=digest(release / 'review.json'))
            self.compose(release, 'up', '--detach', '--no-build', '--no-deps', 'web')
            ids = self.compose(release, 'ps', '--quiet', 'web').stdout.decode().split()
            if len(ids) != 1 or self.inspect(ids[0])['Image'] != self.state['image']:
                raise UpdateError('Candidate did not start the exact tested image')
            self.state['candidate_web'] = ids[0]
            self.health(release, candidate=True)
            files = {str(p.relative_to(release)): digest(p) for p in release.rglob('*') if p.is_file()
                     and p.name != 'release.private.json' and not str(p.relative_to(release)).startswith(('tmp/', 'runtime-data/', 'control/'))}
            self.save(release, 'prepared', frozen_files=files)
        except BaseException:
            if self.state.get('preview_stopped'):
                result = self.command('start', preview['web'], check=False)
                self.state['preview_restart_requested'] = result.returncode == 0
            self.save(release, 'prepare_failed')
            raise
        print(json.dumps({'release': str(release), 'review_sha256': self.state['review_sha256'],
                          'test_url': 'http://127.0.0.1:' + str(args.port)}, indent=2))

    def start_candidate(self, release, proxy_network):
        password = secrets.token_urlsafe(32)
        self.state['candidate_pg'] = {'POSTGRES_USER': 'postgres', 'POSTGRES_PASSWORD': password}
        main_env = env_dict(self.inspect(self.state['main']['web']))
        env = {key: value for key, value in main_env.items()
               if key in {'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET', 'CMCCDB_SESSION_KEY'}}
        env.update(self.state['candidate_pg'], POSTGRES_HOST='database', POSTGRES_DATABASE='cmcc',
            POSTGRES_PORT='5432', CMCCDB_DISABLE_GITHUB_BACKUPS='true', CMCCDB_MAINTENANCE_API='false',
            CMCCDB_POSTGRES_RDKIT=self.state['preview']['rdkit'],
            CMCCDB_SNAPSHOT_DIR='/app/backups', CMCCDB_RELEASE_CONTROL='/app/release-control',
            CMCCDB_RELEASE_ID=self.state['id'], **OFF)
        for name in ('runtime-data', 'tmp'):
            (release / name).mkdir(mode=0o700, exist_ok=True)
        bind = lambda name, target: {'type': 'bind', 'source': str(release / name), 'target': target,
                                    'bind': {'selinux': 'z'}}
        config = {'name': self.state['project'], 'services': {
            'database': {'image': self.state['database_image'], 'pull_policy': 'never',
                'environment': dict(self.state['candidate_pg'], PGDATA='/data'),
                'volumes': ['database:/data'], 'networks': ['default']},
            'web': {'image': self.state['image'], 'pull_policy': 'never',
                'container_name': self.state['project'] + '-web', 'environment': env,
                'ports': [{'target': 80, 'published': str(self.state['port']), 'host_ip': '127.0.0.1'}],
                'volumes': [bind('runtime-data', '/app/cmccdb-data'), bind('tmp', '/app/tmp'),
                    bind('control', '/app/release-control'), bind('snapshots', '/app/backups')],
                'networks': ['default', 'public-proxy']}}, 'volumes': {'database': {}},
            'networks': {'default': {}, 'public-proxy': {'external': True, 'name': proxy_network}}}
        # Preserve credential-file authentication when the deployment has no session env key.
        for mount in self.inspect(self.state['main']['web']).get('Mounts', []):
            if mount['Destination'] == '/app/credentials':
                config['services']['web']['volumes'].append({'type': 'bind', 'source': mount['Source'],
                    'target': '/app/credentials', 'read_only': True, 'bind': {'selinux': 'z'}})
        write_json(release / 'compose.private.json', literal_config(config))
        self.compose(release, 'up', '--detach', '--no-build', 'database')
        ids = self.compose(release, 'ps', '--quiet', 'database').stdout.decode().split()
        if len(ids) != 1:
            raise UpdateError('Expected one fresh candidate database container')
        db_id = ids[0]
        deadline = time.monotonic() + 180
        while True:
            result = self.command('exec', db_id, 'psql', '-U', 'postgres', '-d', 'postgres', '-Atc',
                'SELECT system_identifier FROM pg_control_system()', check=False)
            if result.returncode == 0 and result.stdout.decode().strip().isdigit():
                break
            if time.monotonic() > deadline:
                raise UpdateError('Candidate PostgreSQL did not become ready')
            time.sleep(2)
        db = self.inspect(db_id)
        if db['Image'] != self.state['database_image']:
            raise UpdateError('Candidate uses a different PostgreSQL image')
        networks = db.get('NetworkSettings', {}).get('Networks', {})
        if len(networks) != 1:
            raise UpdateError('Candidate database should have exactly one isolated network')
        network = next(iter(networks))
        self.state.update(candidate_database=db_id, candidate_cluster=result.stdout.decode().strip(),
                          candidate_mounts=db.get('Mounts'), candidate_network=network)
        if self.state['candidate_cluster'] in {self.state['main']['cluster'], self.state['preview']['cluster']}:
            raise UpdateError('Candidate is not an isolated PostgreSQL cluster')
        self.save(release, 'candidate_database_ready')

    def health(self, release, candidate=False):
        base = ('http://127.0.0.1:' + str(self.state['port'])) if candidate else self.state['public_url']
        deadline = time.monotonic() + 120
        while True:
            try:
                with urllib.request.urlopen(base + '/api/release', timeout=10) as response:
                    info = json.load(response)
                if info != {'release': self.state['id'], 'read_only': True}:
                    raise UpdateError('Route did not serve the frozen candidate release')
                for database in self.state['snapshots']:
                    with urllib.request.urlopen(base + '/api/fetch_datasets?database=' + database, timeout=20) as response:
                        data = json.load(response)
                    if not isinstance(data, list) and data != {'response': 'No datasets found for database ' + database}:
                        raise UpdateError('Dataset API did not return a list')
                with urllib.request.urlopen(base + '/', timeout=10) as response:
                    if response.status != 200 or b'<html' not in response.read().lower():
                        raise UpdateError('Built frontend did not load')
                return
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)

    def commit_data(self, args):
        release = self.load(args.release)
        if self.state['phase'] != 'prepared':
            raise UpdateError('Only an uncommitted prepared release can create its data commit')
        checked_files(release, self.state['frozen_files'])
        checked_export(release, self.state['frozen_files'])
        checkout = release / 'data-git'
        if checkout.exists():
            raise UpdateError('A prior data checkout exists; inspect it rather than overwriting it')
        repository = Path(args.data_repo).resolve()
        if not repository.is_dir() or not (repository / '.git').exists():
            raise UpdateError('Use an existing local cmccdb-data Git repository')
        self.run(['git', 'clone', '--no-hardlinks', '--no-local', '--no-checkout', str(repository), str(checkout)])
        self.run(['git', '-C', checkout, 'checkout', '-b', 'release/' + self.state['id'], 'HEAD'])
        destination = checkout / 'releases' / self.state['id']
        if destination.parent.is_symlink():
            raise UpdateError('Data repository releases directory cannot be a symlink')
        destination.parent.mkdir(exist_ok=True)
        shutil.copytree(release / 'data-export', destination)
        self.run(['git', '-C', checkout, 'add', '--', 'releases/' + self.state['id']])
        result = self.run(['git', '-C', checkout, '-c', 'user.name=' + args.name,
                         '-c', 'user.email=' + args.email, 'commit', '-m', args.message])
        commit = self.run(['git', '-C', checkout, 'rev-parse', 'HEAD']).stdout.decode().strip()
        self.save(release, 'data_committed', data_commit=commit, data_checkout=str(checkout))
        print(json.dumps({'commit': commit, 'checkout': str(checkout), 'pushed': False}, indent=2))

    def proxy_install(self, release, filename):
        body = (release / filename).read_bytes()
        # Fixed path and fixed command: config bytes go over stdin, never through shell interpolation.
        self.command('exec', '--interactive', self.state['proxy'], 'sh', '-c',
                     'cat > /etc/nginx/nginx.conf', data=body)
        self.command('exec', self.state['proxy'], 'nginx', '-t')
        self.command('exec', self.state['proxy'], 'nginx', '-s', 'reload')

    def promote(self, args):
        release = self.load(args.release)
        if self.state['phase'] != 'data_committed':
            raise UpdateError('Promotion requires a prepared release and its local data commit')
        checked_files(release, self.state['frozen_files'])
        if args.approve != self.state['review_sha256'] or digest(release / 'review.json') != args.approve:
            raise UpdateError('Review approval does not match this prepared release')
        checkout = Path(self.state['data_checkout'])
        if self.run(['git', '-C', checkout, 'rev-parse', 'HEAD']).stdout.decode().strip() != self.state['data_commit']:
            raise UpdateError('Data commit changed')
        main = self.deployment(self.state['main']['web'], self.state['main']['database'])
        self.lock_clusters(main['cluster'], self.state['candidate_cluster'])
        if main != self.state['main']:
            raise UpdateError('Main deployment identity or connection settings changed')
        proxy = self.inspect(self.state['proxy'])
        original = self.command('exec', self.state['proxy'], 'cat', '/etc/nginx/nginx.conf').stdout
        if proxy['Image'] != self.state['proxy_image'] or original != (release / 'proxy-old.conf').read_bytes():
            raise UpdateError('Proxy changed after preparation')
        candidate = self.candidate(release)
        checked_files(release, self.state['input_files'])
        if not (release / 'control/read-only').is_file():
            raise UpdateError('Candidate has already been made writable; automatic promotion is unsafe')
        if (release / 'control/writable').exists():
            raise UpdateError('Candidate activation was already attempted; inspect its control files')
        candidate_web = self.inspect(self.state['candidate_web'])
        if candidate_web['Image'] != self.state['image'] or not candidate_web['State']['Running']:
            raise UpdateError('Candidate image changed or stopped')
        stopped, route_attempted, activation_attempted = False, False, False
        try:
            self.save(release, 'draining')
            stopped = True
            self.command('stop', '--time', '60', self.state['candidate_web'])
            self.command('stop', '--time', '60', main['web'])
            for database, baseline in self.state['main_baseline'].items():
                current = self.worker(release, main, 'inventory', database, '--quiet')
                if current != baseline:
                    raise UpdateError('Main changed after preparation; rebuild/reconcile this candidate')
            if self.archive_inputs(main, release / 'main-cutover-inputs.private.tar.gz') != self.state['main_inputs']:
                raise UpdateError('Main contribution files changed after preparation; reconcile a new candidate')
            for database, baseline in self.state['candidate_inventories'].items():
                current = self.worker(release, candidate, 'inventory', database, '--quiet')
                if current != baseline:
                    raise UpdateError('Candidate changed after its data export; prepare a new release')
            self.command('start', self.state['candidate_web'])
            self.health(release, candidate=True)
            route_attempted = True
            self.save(release, 'switching_route')
            self.proxy_install(release, 'proxy-new.conf')
            self.health(release)
            # All pre-activation failures can route back while candidate writes are still gated.
            activation_attempted = True
            self.save(release, 'enabling_writes', recovery='Do not revert routing without checking new writes')
            write_json(release / 'control/writable', {'release': self.state['id']})
            (release / 'control/read-only').unlink()
            directory = os.open(release / 'control', os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.save(release, 'active')
            write_json(self.root / 'current-main.private.json', {'release': str(release), 'id': self.state['id']})
        except BaseException:
            if activation_attempted:
                self.save(release, 'activation_uncertain', recovery='Keep routing; inspect write gate and new contributions')
            else:
                # No candidate writes have been accepted. Original main/database remain paired.
                recovered = True
                if stopped:
                    recovered = self.command('start', main['web'], check=False).returncode == 0
                if route_attempted:
                    try:
                        self.proxy_install(release, 'proxy-old.conf')
                    except BaseException:
                        recovered = False
                self.save(release, 'promotion_failed', old_main_restart_requested=stopped,
                          recovery='Old route restored' if recovered else 'Inspect proxy and container state')
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='One stable private local archive root for all operations')
    parser.add_argument('--engine', choices=['podman', 'docker'], default='podman')
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--preview-release', required=True)
    prepare.add_argument('--main-web', required=True)
    prepare.add_argument('--main-database', required=True)
    prepare.add_argument('--proxy-container', required=True)
    prepare.add_argument('--proxy-network', required=True)
    prepare.add_argument('--old-upstream', default='host.containers.internal:85')
    prepare.add_argument('--public-url', required=True)
    prepare.add_argument('--port', type=int, default=9086)
    commit = sub.add_parser('commit-data')
    commit.add_argument('release')
    commit.add_argument('--data-repo', required=True)
    commit.add_argument('--name', required=True)
    commit.add_argument('--email', required=True)
    commit.add_argument('--message', required=True)
    promote = sub.add_parser('promote')
    promote.add_argument('release')
    promote.add_argument('--approve', required=True, help='SHA-256 of the reviewed review.json')
    status = sub.add_parser('status')
    status.add_argument('release')
    args = parser.parse_args(argv)
    os.umask(0o077)
    manager = Manager(args.root, args.engine)
    try:
        if args.action == 'status':
            manager.load(args.release)
            print(json.dumps({key: manager.state[key] for key in ('id', 'phase', 'image', 'port',
                'review_sha256', 'data_commit', 'recovery') if key in manager.state}, indent=2))
        else:
            with release_lock(manager.root), contextlib.ExitStack() as stack:
                manager.locks = stack
                getattr(manager, args.action.replace('-', '_'))(args)
    except (UpdateError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
