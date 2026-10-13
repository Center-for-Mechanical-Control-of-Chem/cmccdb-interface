const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {parse, compileTemplate} = require('@vue/compiler-sfc');

const file = path.resolve(__dirname, '../src/components/DevMaintenanceSuite.vue');
const {descriptor} = parse(fs.readFileSync(file, 'utf8'));
const context = {module: {exports: {}}, URLSearchParams};
vm.runInNewContext(descriptor.script.content.replace('export default', 'module.exports ='), context);
const component = context.module.exports;

function instance() {
  const state = component.data();
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state);
  for (const [name, getter] of Object.entries(component.computed))
    Object.defineProperty(state, name, {get: getter.bind(state)});
  const calls = [];
  state.authenticate = async () => calls.push({action: 'authenticate'});
  state.request = async (action, database, body, extra) => {
    calls.push({action, database, body, extra});
    if (action === 'backup') return {id: database + '-snapshot'};
    if (action === 'restore') return {snapshot_id: extra.id, database: 'cmccdb_restore_' + database, verified: true};
    if (action === 'migration' && body === undefined) return {fingerprint: 'current'};
    return {updated: true};
  };
  return {state, calls};
}

test('Vue template compiles with migration and restore guards', () => {
  const compiled = compileTemplate({source: descriptor.template.content, filename: file, id: 'maintenance'});
  assert.deepEqual(compiled.errors, []);
  assert.match(descriptor.template.content, /running \|\| !backupsVerified/);
});

test('tracked-schema backup does not try to bootstrap a new baseline', async () => {
  const {state, calls} = instance();
  await state.run('backup');
  const backups = calls.filter(c => c.action === 'backup');
  assert.equal(backups.length, 2);
  assert.deepEqual(backups.map(c => c.database), ['staging', 'cmcc']);
  assert.equal(backups.every(c => Object.keys(c.body).length === 0), true);
  assert.equal(state.backupsPresent, true);
  assert.equal(state.backupsVerified, false);
});

test('migration never calls the API without verified current backups for both databases', async () => {
  const {state, calls} = instance();
  state.backups.staging = 'staging-snapshot';
  state.results.push({action: 'restore', database: 'staging', result: {snapshot_id: 'staging-snapshot', verified: true}});
  await state.run('migration');
  assert.equal(calls.length, 0);
  assert.match(state.error, /restore-verify/);
  assert.equal(state.running, false);
});

test('both restored snapshots permit migration and changing either backup invalidates the proof', async () => {
  const {state, calls} = instance();
  await state.run('backup');
  await state.run('restore');
  assert.equal(state.backupsVerified, true);
  calls.length = 0;
  await state.run('migration');
  assert.deepEqual(calls.filter(c => c.action === 'migration' && c.body).map(c => c.database), ['staging', 'cmcc']);
  state.backups.cmcc = 'replacement-snapshot';
  assert.equal(state.backupsVerified, false);
  calls.length = 0;
  await state.run('migration');
  assert.equal(calls.length, 0);
});

test('rehearsal targets restored databases rather than source databases', async () => {
  const {state, calls} = instance();
  await state.run('backup');
  await state.run('restore');
  calls.length = 0;
  await state.run('restored_migration');
  assert.deepEqual(calls.filter(c => c.action === 'migration' && c.body).map(c => c.database),
    ['cmccdb_restore_staging', 'cmccdb_restore_cmcc']);
});

test('a backup cannot be accepted as a restore proof', async () => {
  const {state, calls} = instance();
  await state.run('backup');
  state.results.push({action: 'restore', database: 'staging', result: {snapshot_id: state.backups.staging, verified: false}});
  state.results.push({action: 'restore', database: 'cmcc', result: {snapshot_id: 'stale-snapshot', verified: true}});
  assert.equal(state.backupsVerified, false);
  calls.length = 0;
  await state.run('restored_migration');
  assert.equal(calls.length, 0);
});
