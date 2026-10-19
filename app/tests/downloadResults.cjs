const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { parse, compileTemplate } = require('@vue/compiler-sfc');

const file = path.resolve(__dirname, '../src/components/DownloadResults.vue');
const { descriptor } = parse(fs.readFileSync(file, 'utf8'));

function fixture(database = 'staging', saved = 'pb.gz') {
  const requests = [], links = [], revoked = [], commits = [];
  class XMLHttpRequest {
    constructor() { requests.push(this); this.headers = {}; }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(name, value) { this.headers[name] = value; }
    send(body) { this.body = body; }
  }
  const context = {
    module: { exports: {} }, FloatingModal: {}, URLSearchParams, XMLHttpRequest,
    URL: { createObjectURL: () => 'blob:export', revokeObjectURL: url => revoked.push(url) },
    document: { createElement: () => {
      const link = { clicked: false, removed: false,
        click() { this.clicked = true; }, remove() { this.removed = true; } };
      links.push(link); return link;
    } },
    setTimeout: fn => fn(),
  };
  const source = descriptor.script.content.replace(/^import FloatingModal.*$/m, '')
    .replace('export default', 'module.exports =');
  vm.runInNewContext(source, context);
  const component = context.module.exports;
  const state = { ...component.data(), reactionIds: ['cmcc-first', 'cmcc-second'],
    $route: { query: { database } },
    $store: { state: { downloadFileType: saved }, commit: (...args) => commits.push(args) } };
  for (const [key, method] of Object.entries(component.methods)) state[key] = method.bind(state);
  component.mounted.call(state);
  return { state, component, requests, links, revoked };
}

test('the Pug/Vue template compiles and enables protobuf text and CSV downloads', () => {
  const compiled = compileTemplate({ source: descriptor.template.content, filename: file,
    id: 'downloads', preprocessLang: 'pug' });
  assert.deepEqual(compiled.errors, []);
  assert.match(descriptor.template.content, /option\(value="pbtxt"\) pbtxt/);
  assert.match(descriptor.template.content, /option\(value="csv"\) csv/);
});

test('format and active database reach the existing download API', () => {
  const { state, requests } = fixture();
  state.fileType = 'pbtxt';
  state.downloadResults();
  const request = requests[0];
  const params = new URLSearchParams(request.url.split('?')[1]);
  assert.equal(request.method, 'POST');
  assert.equal(params.get('format'), 'pbtxt');
  assert.equal(params.get('database'), 'staging');
  assert.equal(request.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(request.body), [{ 'Reaction ID': 'cmcc-first' }, { 'Reaction ID': 'cmcc-second' }]);
});

test('the downloaded extension matches the request even if selection changes while pending', async () => {
  const { state, requests, links, revoked } = fixture();
  state.fileType = 'pbtxt';
  state.downloadResults();
  state.downloadResults();
  assert.equal(requests.length, 1);
  state.fileType = 'pb.gz';
  const request = requests[0];
  request.status = 200; request.response = {};
  await request.onload(); request.onloadend();
  assert.equal(links[0].download, 'cmccdb_search_results.pbtxt');
  assert.equal(links[0].clicked, true);
  assert.equal(links[0].removed, true);
  assert.deepEqual(revoked, ['blob:export']);
  assert.equal(state.downloading, false);
});

test('binary gzip remains the default and stale unsupported selections fall back to it', () => {
  const { state, requests } = fixture(undefined, 'xlsx');
  assert.equal(state.fileType, 'pb.gz');
  state.downloadResults();
  assert.equal(new URLSearchParams(requests[0].url.split('?')[1]).get('format'), 'pb.gz');
});

test('CSV selection is remembered and downloads with the CSV extension', async () => {
  const { state, requests, links } = fixture('cmcc', 'csv');
  assert.equal(state.fileType, 'csv');
  state.downloadResults();
  const request = requests[0];
  assert.equal(new URLSearchParams(request.url.split('?')[1]).get('format'), 'csv');
  request.status = 200; request.response = {};
  await request.onload(); request.onloadend();
  assert.equal(links[0].download, 'cmccdb_search_results.csv');
});

test('HTTP errors show an explanation and do not download an error page', async () => {
  const { state, requests, links } = fixture();
  state.downloadResults();
  const request = requests[0];
  request.status = 400;
  request.response = { text: async () => JSON.stringify({ message: 'The selected reactions are unavailable.' }) };
  await request.onload(); request.onloadend();
  assert.equal(state.downloadError, 'The selected reactions are unavailable.');
  assert.equal(state.downloading, false);
  assert.equal(links.length, 0);
});

test('non-JSON and network failures provide a readable fallback', async () => {
  const { state, requests } = fixture();
  state.downloadResults();
  requests[0].status = 500;
  requests[0].response = { text: async () => '<html>Server error</html>' };
  await requests[0].onload(); requests[0].onloadend();
  assert.match(state.downloadError, /Download failed/);
  state.downloadResults();
  requests[1].onerror(); requests[1].onloadend();
  assert.match(state.downloadError, /Could not connect/);
  assert.equal(state.downloading, false);
});
