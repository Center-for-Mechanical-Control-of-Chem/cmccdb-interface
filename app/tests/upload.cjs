// Exercise the real component methods, including the multipart payload and stale selections.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const source = fs.readFileSync(path.resolve(__dirname, '../src/views/contribute/UploadView.vue'), 'utf8')
const requests = []
const alerts = []
const window = { location: { search: '?database=staging', href: '/contribute', toString: () => 'http://localhost/contribute' } }
class FormData {
  constructor() { this.entries = [] }
  append(...entry) { this.entries.push(entry) }
}
class XMLHttpRequest {
  constructor() { requests.push(this) }
  open(method, url) { this.method = method; this.url = url }
  send(payload) { this.payload = payload }
}
const context = { module: { exports: {} }, URLSearchParams, window, FormData, XMLHttpRequest, alert: message => alerts.push(message), console: { log() {} } }
vm.runInNewContext(source.match(/<script>([\s\S]*?)<\/script>/)[1].replace('export default', 'module.exports ='), context)
const component = context.module.exports
const instance = () => {
  const state = component.data()
  for (const [key, method] of Object.entries(component.methods)) state[key] = method.bind(state)
  return state
}
const file = (name, size = 32) => ({ name, size })
const event = files => ({ target: { files, value: 'selected' } })
const state = instance()
state.setAuxFiles(event([file('plot.png'), file('spectrum.csv')]))
assert.equal(state.auxFiles.length, 2)
state.removeAuxFile(0)
assert.equal(state.auxFiles[0].name, 'spectrum.csv')
for (const rejected of [Array.from({ length: 6 }, (_, i) => file(`file${i}`)), [file('big.png', state.maxFileSize + 1)], [file('same'), file('same')]]) {
  state.setAuxFiles(event([file('old.png')]))
  const selection = event(rejected)
  state.setAuxFiles(selection)
  assert.equal(state.auxFiles.length, 0, 'A rejected selection must not send stale attachments')
  assert.ok(state.fileError)
  assert.equal(selection.target.value, '')
}
state.setAuxFiles(event([file('plot.png', state.maxFileSize)]))
assert.equal(state.auxFiles.length, 1)
assert.equal(state.fileError, null)
state.setAuxFiles(event([]))
assert.equal(state.auxFiles.length, 0)
state.setFile(event([file('dataset.pbtxt')]))
state.setFile(event([file('too-big.pbtxt', state.maxFileSize + 1)]))
assert.equal(state.uploadFile.file, null)
state.setFile(event([file('dataset.pbtxt')]))
state.setAuxFiles(event([file('plot.png'), file('spectrum.csv')]))
state.submitUpload()
assert.equal(requests.length, 0, 'Authentication is required')
state.user.ghAuthenticated = true
state.user.cmccMember = false
state.user.name = 'Contributor Name'
state.user.email = 'contributor@example.org'
state.submitUpload()
assert.equal(requests.length, 1, 'Nonmembers can contribute to staging')
const request = requests[0]
assert.deepEqual(request.payload.entries.map(entry => entry[0]), ['uploadFile', 'auxFile0', 'auxFile1'])
assert.equal(request.payload.entries[1][2], 'plot.png')
assert.equal(new URLSearchParams(request.url.split('?')[1]).get('name'), 'Contributor Name')
state.submitUpload()
assert.equal(requests.length, 1, 'An upload cannot be submitted twice while pending')
request.status = 413
request.response = '<html>too large</html>'
request.onload()
assert.equal(state.inUpload, false)
assert.match(state.traceback, /HTTP 413/)
window.location.search = '?database=cmcc'
state.submitUpload()
assert.equal(requests.length, 1, 'Nonmembers cannot upload to primary')
assert.ok(alerts.length)
console.log('Upload component checks passed (selection limits, stale files, removals, multipart, access and errors).')
