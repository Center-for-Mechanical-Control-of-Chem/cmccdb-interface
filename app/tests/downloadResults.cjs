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
    getResponseHeader(name) { return (this.responseHeaders || {})[name] || null; }
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
  assert.match(descriptor.template.content, /option\(value="csv"\) CSV \+ attachments \(\.zip\)/);
  assert.match(descriptor.template.content, /Download CSV bundle \(\.zip\)/);
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

test('CSV selection is remembered and downloads a ZIP with the right extension', async () => {
  const { state, requests, links } = fixture('cmcc', 'csv');
  assert.equal(state.fileType, 'csv');
  state.downloadResults();
  const request = requests[0];
  assert.equal(new URLSearchParams(request.url.split('?')[1]).get('format'), 'csv');
  request.status = 200; request.response = {};
  await request.onload(); request.onloadend();
  assert.equal(links[0].download, 'cmccdb_search_results.zip');
});

test('HTTP errors show an explanation and do not download an error page', async () => {
  const { state, requests, links } = fixture();
  state.downloadResults();
  const request = requests[0];
  request.status = 400;
  request.response = { text: async () => JSON.stringify({ message: 'The selected reactions are unavailable.' }) };
  await request.onload(); request.onloadend();
  assert.match(state.downloadError, /HTTP 400/);
  assert.match(state.downloadError, /The selected reactions are unavailable\./);
  assert.equal(state.downloading, false);
  assert.equal(links.length, 0);
});

test('non-JSON and network failures provide a readable fallback', async () => {
  const { state, requests } = fixture();
  state.downloadResults();
  requests[0].status = 500;
  requests[0].response = { text: async () => '<html>Server error</html>' };
  await requests[0].onload(); requests[0].onloadend();
  assert.match(state.downloadError, /download failed \(HTTP 500\)/);
  assert.match(state.downloadError, /HTML error page/);
  state.downloadResults();
  requests[1].onerror(); requests[1].onloadend();
  assert.match(state.downloadError, /could not connect/);
  assert.equal(state.downloading, false);
});

test('CSV validation details and the reference ID reach the user', async () => {
  const { state, requests, links } = fixture('staging', 'csv');
  state.downloadResults();
  requests[0].status = 422;
  requests[0].statusText = 'Unprocessable Entity';
  requests[0].response = { text: async () => JSON.stringify({
    message: 'CSV export could not complete: field larger than field limit (131072).',
    request_id: 'csv-reference-123',
  }) };
  await requests[0].onload(); requests[0].onloadend();
  assert.match(state.downloadError, /CSV download failed \(HTTP 422 Unprocessable Entity\)/);
  assert.match(state.downloadError, /field larger than field limit \(131072\)/);
  assert.match(state.downloadError, /Reference: csv-reference-123/);
  assert.equal(links.length, 0);
});

test('HTML proxy errors retain status and header reference without showing markup', async () => {
  const { state, requests } = fixture('cmcc', 'csv');
  state.downloadResults();
  requests[0].status = 502; requests[0].statusText = 'Bad Gateway';
  requests[0].responseHeaders = { 'X-Request-ID': 'proxy-reference' };
  requests[0].response = { text: async () => '<html><script>private content</script></html>' };
  await requests[0].onload(); requests[0].onloadend();
  assert.match(state.downloadError, /HTTP 502 Bad Gateway/);
  assert.match(state.downloadError, /HTML error page/);
  assert.match(state.downloadError, /proxy-reference/);
  assert.doesNotMatch(state.downloadError, /<script>|private content/);
});

test('plain-text and empty errors retain HTTP context', async () => {
  for (const text of ['upstream timed out', '']) {
    const { state, requests } = fixture();
    state.downloadResults();
    requests[0].status = 504;
    requests[0].response = { text: async () => text };
    await requests[0].onload(); requests[0].onloadend();
    assert.match(state.downloadError, /HTTP 504/);
    assert.match(state.downloadError, text ? /upstream timed out/ : /empty error response/);
  }
});
