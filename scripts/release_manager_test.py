"""Offline failure-injection tests. No deployed containers, databases or remote Git."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_manager as rm


def completed(body=b'', code=0):
    return subprocess.CompletedProcess([], code, body, b'')


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('CMCCDB_TEST_TMP'))
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


class GuardTests(Files):
    def test_coverage_retains_main_and_reports_changes(self):
        old = {'cmcc': {'datasets': {'a': 'old'}, 'reactions': {'r': 'same'}}}
        new = {'cmcc': {'datasets': {'a': 'new', 'b': 'added'}, 'reactions': {'r': 'same', 's': 'new'}}}
        result = rm.coverage(old, new)['cmcc']
        self.assertEqual(result['datasets']['changed']['a'], {'main': 'old', 'candidate': 'new'})
        self.assertEqual(result['reactions']['added'], ['s'])

    def test_missing_main_dataset_blocks(self):
        with self.assertRaisesRegex(rm.UpdateError, 'missing main cmcc datasets'):
            rm.coverage({'cmcc': {'datasets': {'a': 'x'}, 'reactions': {}}},
                        {'cmcc': {'datasets': {}, 'reactions': {}}})

    def test_missing_main_reaction_blocks(self):
        with self.assertRaisesRegex(rm.UpdateError, 'missing main cmcc reactions'):
            rm.coverage({'cmcc': {'datasets': {}, 'reactions': {'r': 'x'}}},
                        {'cmcc': {'datasets': {}, 'reactions': {}}})

    def test_missing_staging_blocks(self):
        with self.assertRaisesRegex(rm.UpdateError, 'missing main database staging'):
            rm.coverage({'staging': {}}, {})

    def test_proxy_preserves_preview_and_matches_exact_port(self):
        old = 'proxy_pass http://host.containers.internal:85;\nproxy_pass http://host.containers.internal:90;\n'
        new = rm.route_config(old, 'host.containers.internal:85', 'cmccdb-release-012345abcdef-web:80')
        self.assertIn('cmccdb-release-012345abcdef-web:80;', new)
        self.assertIn('host.containers.internal:90;', new)
        self.assertNotIn('host.containers.internal:85;', new)

    def test_proxy_refuses_unrecognized_configuration(self):
        with self.assertRaises(rm.UpdateError):
            rm.route_config('proxy_pass http://different:85;', 'host.containers.internal:85',
                            'cmccdb-release-012345abcdef-web:80')

    def test_proxy_rejects_injected_upstream(self):
        with self.assertRaises(rm.UpdateError):
            rm.route_config('', 'host:85; return 200', 'cmccdb-release-012345abcdef-web:80')

    def test_file_hashes_detect_modified_data(self):
        file = self.root / 'data.pb'
        file.write_bytes(b'accepted data')
        hashes = {'data.pb': rm.digest(file)}
        rm.checked_files(self.root, hashes)
        file.write_bytes(b'changed')
        with self.assertRaisesRegex(rm.UpdateError, 'changed'):
            rm.checked_files(self.root, hashes)

    def test_file_manifest_rejects_traversal(self):
        with self.assertRaises(rm.UpdateError):
            rm.checked_files(self.root, {'../outside': 'x'})

    def test_file_manifest_rejects_symlinks(self):
        (self.root / 'actual').write_bytes(b'a')
        (self.root / 'link').symlink_to(self.root / 'actual')
        with self.assertRaises(rm.UpdateError):
            rm.checked_files(self.root, {'link': rm.digest(self.root / 'actual')})

    def test_public_export_rejects_unexpected_private_file(self):
        directory = self.root / 'data-export'
        directory.mkdir()
        (directory / 'accepted.pb').write_bytes(b'accepted')
        frozen = {'data-export/accepted.pb': rm.digest(directory / 'accepted.pb')}
        rm.checked_export(self.root, frozen)
        (directory / 'private-staging.json').write_bytes(b'private')
        with self.assertRaisesRegex(rm.UpdateError, 'unexpected'):
            rm.checked_export(self.root, frozen)

    def test_release_lock_excludes_another_operation(self):
        with rm.release_lock(self.root):
            with self.assertRaisesRegex(rm.UpdateError, 'Another release'):
                with rm.release_lock(self.root):
                    pass

    def test_cluster_lock_excludes_backend_updater(self):
        manager = rm.Manager(self.root)
        (self.root / '.locks').mkdir()
        with (self.root / '.locks/123.lock').open('a') as lock:
            rm.fcntl.flock(lock, rm.fcntl.LOCK_EX | rm.fcntl.LOCK_NB)
            with contextlib.ExitStack() as manager.locks:
                with self.assertRaisesRegex(rm.UpdateError, 'already owns'):
                    manager.lock_clusters('123')

    def test_load_refuses_symlink_directory(self):
        actual = self.root / 'actual'
        actual.mkdir()
        link = self.root / 'link'
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(rm.UpdateError):
            rm.Manager(self.root).load(link)

    def test_success_with_stderr_does_not_fail(self):
        with patch.object(rm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'ok', b'warning')):
            self.assertEqual(rm.Manager(self.root).run(['git', 'commit']).returncode, 0)

    def test_failure_without_stderr_fails(self):
        with patch.object(rm.subprocess, 'run', return_value=completed(code=1)):
            with self.assertRaises(rm.UpdateError):
                rm.Manager(self.root).run(['git', 'commit'])

    def make_archive(self, name, member, body=b'input bytes', symlink=False):
        path = self.root / name
        with tarfile.open(path, 'w:gz') as archive:
            info = tarfile.TarInfo(member)
            if symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = '/outside'
                archive.addfile(info)
            else:
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        return path

    def test_original_inputs_are_merged_without_losing_paths(self):
        first = self.make_archive('main.tgz', 'cmccdb-data/alice/spectrum.csv')
        second = self.make_archive('preview.tgz', 'tmp/bob/paper.xlsx')
        destination = self.root / 'release'
        destination.mkdir()
        result = rm.merge_inputs([first, second], destination)
        self.assertIn('runtime-data/alice/spectrum.csv', result)
        self.assertEqual((destination / 'tmp/bob/paper.xlsx').read_bytes(), b'input bytes')

    def test_input_conflicts_block_instead_of_overwriting(self):
        first = self.make_archive('main.tgz', 'cmccdb-data/alice/spectrum.csv', b'old')
        second = self.make_archive('preview.tgz', 'cmccdb-data/alice/spectrum.csv', b'new')
        destination = self.root / 'release'
        destination.mkdir()
        with self.assertRaisesRegex(rm.UpdateError, 'conflict'):
            rm.merge_inputs([first, second], destination)
        self.assertEqual((destination / 'runtime-data/alice/spectrum.csv').read_bytes(), b'old')

    def test_input_archive_refuses_links(self):
        archive = self.make_archive('linked.tgz', 'tmp/link', symlink=True)
        with self.assertRaisesRegex(rm.UpdateError, 'symlink'):
            rm.input_members(archive)

    def test_input_archive_refuses_traversal(self):
        archive = self.make_archive('escape.tgz', 'tmp/../../outside')
        with self.assertRaises(rm.UpdateError):
            rm.input_members(archive)


class FakeManager(rm.Manager):
    """Fault injection at command boundaries; never pretends to run PostgreSQL."""
    def __init__(self, root, fault=None):
        super().__init__(root)
        self.fault = fault
        self.events = []
        self.now_main = None
        self.now_candidate = None

    def lock_clusters(self, *clusters):
        self.events.append(('locks', clusters))

    def deployment(self, web, db):
        return copy.deepcopy(self.state['main'])

    def candidate(self, release):
        return {'cluster': '222'}

    def inspect(self, identifier):
        if identifier == 'proxy':
            return {'Image': 'proxy-image'}
        return {'Image': self.state['image'], 'State': {'Running': True}}

    def run(self, args, **kwargs):
        return completed(b'commit123\n')

    def command(self, *args, **kwargs):
        self.events.append(args)
        if args[:2] == ('exec', 'proxy'):
            return completed((self.root / 'candidate/proxy-old.conf').read_bytes())
        return completed()

    def worker(self, release, deployment, action, database, *args):
        if deployment == self.state['main']:
            return copy.deepcopy(self.now_main or self.state['main_baseline'][database])
        return copy.deepcopy(self.now_candidate or self.state['candidate_inventories'][database])

    def archive_inputs(self, deployment, destination):
        return {'input': 'changed'} if self.fault == 'main-files-drift' else {}

    def health(self, release, candidate=False):
        self.events.append(('health', candidate))
        if self.fault == 'routed-health' and not candidate:
            raise rm.UpdateError('Injected public health failure')

    def proxy_install(self, release, filename):
        self.events.append(('proxy', filename))
        if self.fault == 'proxy-test' and filename == 'proxy-new.conf':
            raise rm.UpdateError('Injected nginx validation failure')

    def save(self, release, phase, **values):
        self.events.append(('phase', phase))
        if self.fault == 'active-journal' and phase == 'active':
            raise OSError('Injected disk failure after write gate removal')
        super().save(release, phase, **values)


class PromotionTests(Files):
    def setUp(self):
        super().setUp()
        self.release = self.root / 'candidate'
        self.release.mkdir()
        (self.release / 'control').mkdir()
        (self.release / 'control/read-only').write_text('frozen')
        (self.release / 'proxy-old.conf').write_text('old config')
        (self.release / 'review.json').write_text('{"accepted":true}')
        self.approval = rm.digest(self.release / 'review.json')
        inventory = {'datasets': {'d': 'x'}, 'reactions': {'r': 'x'}, 'tables': {}, 'oid': 42}
        self.state = {'id': '012345abcdef', 'engine': 'podman', 'phase': 'data_committed',
            'project': 'candidate', 'image': 'exact-image', 'port': 9086,
            'main': {'web': 'old-web', 'database': 'old-db', 'cluster': '111'},
            'candidate_cluster': '222', 'candidate_web': 'candidate-web',
            'main_baseline': {'cmcc': inventory}, 'candidate_inventories': {'cmcc': inventory},
            'data_checkout': str(self.release / 'data-git'), 'data_commit': 'commit123',
            'proxy': 'proxy', 'proxy_image': 'proxy-image', 'review_sha256': self.approval,
            'input_files': {}, 'main_inputs': {},
            'frozen_files': {'review.json': self.approval}}
        rm.write_json(self.release / 'release.private.json', self.state)
        self.args = types.SimpleNamespace(release=self.release, approve=self.approval)

    def manager(self, fault=None):
        return FakeManager(self.root, fault)

    def test_success_enables_writes_after_routed_health(self):
        manager = self.manager()
        manager.promote(self.args)
        self.assertEqual(manager.state['phase'], 'active')
        self.assertFalse((self.release / 'control/read-only').exists())
        self.assertLess(manager.events.index(('health', False)), manager.events.index(('phase', 'enabling_writes')))
        self.assertEqual(json.loads((self.root / 'current-main.private.json').read_text())['id'], self.state['id'])
        self.assertNotIn(('start', 'old-web'), manager.events)

    def test_unapproved_manifest_does_not_stop_services(self):
        self.args.approve = 'wrong'
        manager = self.manager()
        with self.assertRaisesRegex(rm.UpdateError, 'approval'):
            manager.promote(self.args)
        self.assertFalse(any(event[0] == 'stop' for event in manager.events))

    def test_main_drift_aborts_and_restarts_old_web(self):
        manager = self.manager()
        manager.now_main = {'new contribution': True}
        with self.assertRaisesRegex(rm.UpdateError, 'Main changed'):
            manager.promote(self.args)
        self.assertIn(('start', 'old-web'), manager.events)
        self.assertNotIn(('proxy', 'proxy-new.conf'), manager.events)
        self.assertTrue((self.release / 'control/read-only').exists())

    def test_candidate_drift_aborts(self):
        manager = self.manager()
        manager.now_candidate = {'changed candidate': True}
        with self.assertRaisesRegex(rm.UpdateError, 'Candidate changed'):
            manager.promote(self.args)
        self.assertTrue((self.release / 'control/read-only').exists())

    def test_main_original_file_drift_aborts(self):
        manager = self.manager('main-files-drift')
        with self.assertRaisesRegex(rm.UpdateError, 'contribution files changed'):
            manager.promote(self.args)
        self.assertNotIn(('proxy', 'proxy-new.conf'), manager.events)

    def test_nginx_validation_failure_restores_old_route(self):
        manager = self.manager('proxy-test')
        with self.assertRaises(rm.UpdateError):
            manager.promote(self.args)
        self.assertIn(('proxy', 'proxy-old.conf'), manager.events)
        self.assertIn(('start', 'old-web'), manager.events)
        self.assertTrue((self.release / 'control/read-only').exists())

    def test_public_health_failure_restores_old_route(self):
        manager = self.manager('routed-health')
        with self.assertRaises(rm.UpdateError):
            manager.promote(self.args)
        self.assertEqual(manager.state['phase'], 'promotion_failed')
        self.assertIn(('proxy', 'proxy-old.conf'), manager.events)
        self.assertTrue((self.release / 'control/read-only').exists())

    def test_post_activation_journal_failure_does_not_revert_new_writes(self):
        manager = self.manager('active-journal')
        with self.assertRaises(OSError):
            manager.promote(self.args)
        self.assertFalse((self.release / 'control/read-only').exists())
        self.assertEqual(manager.state['phase'], 'activation_uncertain')
        self.assertNotIn(('proxy', 'proxy-old.conf'), manager.events)
        self.assertNotIn(('start', 'old-web'), manager.events)

    def test_changed_data_commit_blocks(self):
        manager = self.manager()
        with patch.object(manager, 'run', return_value=completed(b'different\n')):
            with self.assertRaisesRegex(rm.UpdateError, 'Data commit changed'):
                manager.promote(self.args)
        self.assertFalse(any(event[0] == 'stop' for event in manager.events))

    def test_candidate_already_writable_blocks(self):
        (self.release / 'control/read-only').unlink()
        with self.assertRaisesRegex(rm.UpdateError, 'already been made writable'):
            self.manager().promote(self.args)


class GitTests(Files):
    @unittest.skipUnless(shutil.which('git'), 'Git executable is unavailable')
    def test_batch_commit_uses_private_checkout_and_never_pushes(self):
        source = self.root / 'source-data'
        source.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
        git('init')
        (source / 'existing.txt').write_text('existing accepted data')
        git('add', 'existing.txt')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline')
        before = git('rev-parse', 'HEAD').stdout
        (source / 'uncommitted.txt').write_text('must stay uncommitted')
        release = self.root / 'candidate'
        release.mkdir()
        export = release / 'data-export'
        export.mkdir()
        (export / 'accepted.pb').write_bytes(b'accepted protobuf fixture')
        (release / 'review.json').write_text('{}')
        state = {'id': '012345abcdef', 'engine': 'podman', 'phase': 'prepared',
                 'frozen_files': {'data-export/accepted.pb': rm.digest(export / 'accepted.pb')}}
        rm.write_json(release / 'release.private.json', state)
        manager = rm.Manager(self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            manager.commit_data(types.SimpleNamespace(release=release, data_repo=source,
                name='Fixture', email='fixture@example.invalid', message='Accepted batch'))
        self.assertEqual(git('rev-parse', 'HEAD').stdout, before)
        self.assertIn(b'uncommitted.txt', git('status', '--porcelain').stdout)
        checkout = release / 'data-git'
        self.assertEqual((checkout / 'releases/012345abcdef/accepted.pb').read_bytes(), b'accepted protobuf fixture')
        self.assertFalse((checkout / 'uncommitted.txt').exists())
        history = subprocess.run(['git', '-C', str(checkout), 'log', '--oneline'], capture_output=True, check=True).stdout
        self.assertEqual(len(history.splitlines()), 2)
        self.assertEqual(manager.state['phase'], 'data_committed')


class GateTests(Files):
    def setUp(self):
        super().setUp()
        self.request = types.SimpleNamespace(blueprint='edit', endpoint='edit.upload_dataset')
        fake_flask = types.SimpleNamespace(request=self.request, jsonify=lambda **values: values)
        self.app = types.SimpleNamespace()
        self.hooks, self.routes = [], {}
        self.app.before_request = lambda callback: self.hooks.append(callback) or callback
        self.app.get = lambda route: lambda callback: self.routes.setdefault(route, callback)
        module_path = Path(__file__).parents[1] / 'cmccdb_interface/client/release_control.py'
        spec = importlib.util.spec_from_file_location('release_control_under_test', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'flask': fake_flask}):
            spec.loader.exec_module(module)
        module.install(self.app)
        self.environment = patch.dict(os.environ, {'CMCCDB_RELEASE_CONTROL': str(self.root), 'CMCCDB_RELEASE_ID': 'test'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        (self.root / 'read-only').write_text('freeze')

    def test_upload_is_blocked_while_frozen(self):
        self.assertEqual(self.hooks[0]()[1], 503)

    def test_post_search_is_allowed(self):
        self.request.blueprint = 'api'
        self.request.endpoint = 'api.fetch_reactions'
        self.assertIsNone(self.hooks[0]())

    def test_maintenance_and_unknown_routes_are_blocked(self):
        for blueprint in ('maintenance', None):
            self.request.blueprint = blueprint
            self.request.endpoint = 'unknown'
            self.assertEqual(self.hooks[0]()[1], 503)

    def test_gate_changes_without_restarting_workers(self):
        self.assertEqual(self.hooks[0]()[1], 503)
        (self.root / 'writable').write_text('explicit activation')
        (self.root / 'read-only').unlink()
        self.assertIsNone(self.hooks[0]())

    def test_missing_control_marker_fails_closed(self):
        (self.root / 'read-only').unlink()
        self.assertEqual(self.hooks[0]()[1], 503)

    def test_release_info_identifies_candidate_and_gate(self):
        self.assertEqual(self.routes['/client/api/release'](), {'release': 'test', 'read_only': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
