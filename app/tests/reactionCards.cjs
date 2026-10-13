const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const appRequire = createRequire(path.resolve(__dirname, '../package.json'))
const babel = appRequire('@babel/core')
const vue = appRequire('vue')
const { renderToString } = appRequire('@vue/server-renderer')
const { compile } = appRequire('@vue/compiler-dom')
const pug = appRequire('pug')
const cache = {}
function loadUtility(name) {
  if (cache[name]) return cache[name]
  const filename = path.resolve(__dirname, `../src/utils/${name}.js`)
  const module = { exports: {} }
  const { code } = babel.transformSync(fs.readFileSync(filename, 'utf8'), {
    filename, babelrc: false, configFile: false,
    plugins: [appRequire.resolve('@babel/plugin-transform-modules-commonjs')],
  })
  new Function('require', 'module', 'exports', code)(
    id => id.startsWith('./') ? loadUtility(id.slice(2)) : appRequire(id), module, module.exports)
  return cache[name] = module.exports
}
function component(filename) {
  const source = fs.readFileSync(path.resolve(__dirname, '../src', filename), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]
  const module = { exports: {} }
  const { code } = babel.transformSync(script, {
    babelrc: false, configFile: false,
    plugins: [appRequire.resolve('@babel/plugin-transform-modules-commonjs')],
  })
  const stub = { template: '<span><slot/></span>' }
  new Function('require', 'module', 'exports', code)(id => {
    if (id.includes('/utils/')) return loadUtility(id.split('/').pop())
    if (id.includes('components/') || id.startsWith('./') || id.includes('FloatingModal')) return stub
    return appRequire(id)
  }, module, module.exports)
  const value = module.exports.default
  const html = pug.render(source.match(/<template lang="pug">([\s\S]*?)<\/template>/)[1], {doctype: 'html'})
  value.render = new Function('Vue', compile(html, { mode: 'function', prefixIdentifiers: true }).code)(vue)
  return value
}
async function render(Component, props) {
  const app = vue.createSSRApp(Component, props)
  const { createRouter, createMemoryHistory } = appRequire('vue-router')
  const router = createRouter({ history: createMemoryHistory(), routes: [
    {path: '/', component: {template: '<div/>'}},
    {path: '/id/:reactionId', name: 'reaction-view', component: {template: '<div/>'}},
  ] })
  app.use(router)
  await router.push('/')
  await router.isReady()
  return renderToString(app)
}
global.window = { location: { search: '?database=staging' } }
const pb = appRequire('cmccdb-schema')
async function main() {
  const Card = component('components/ReactionCard.vue')
  const Outcomes = component('views/reaction-view/OutcomesView.vue')
  const Compound = component('views/reaction-view/CompoundView.vue')
  // Reproduce the actual data shape that crashed: an analysis-only first outcome.
  const reaction = new pb.Reaction()
  const analysisOnly = new pb.ReactionOutcome()
  analysisOnly.getAnalysesMap().set('PXRD', new pb.Analysis().setType(21).setDetails('Measured diffraction pattern'))
  reaction.addOutcomes(analysisOnly)
  const final = new pb.ReactionOutcome()
  const product = new pb.ProductCompound()
  product.addIdentifiers(new pb.CompoundIdentifier().setType(6).setValue('ethanol'))
  product.addIdentifiers(new pb.CompoundIdentifier().setType(2).setValue('CCO'))
  product.addMeasurements(new pb.ProductMeasurement().setType(3).setPercentage(new pb.Percentage().setValue(14.2)))
  final.addProducts(product)
  final.setConversion(new pb.Percentage().setValue(0))
  reaction.addOutcomes(final)
  const data = pb.Reaction.deserializeBinary(reaction.serializeBinary()).toObject()
  let html = await render(Card, { reaction: { reaction_id: 'cmcc-test', dataset_id: 'test', data } })
  assert(html.includes('Product SMILES: CCO'))
  assert(html.includes('/id/cmcc-test?database=staging'))
  assert(html.includes('Yield: 14.2%'))
  assert(html.includes('Conversion: 0%'))
  html = await render(Card, { reaction: { row_id: 'cmcc-test', data: { outcomesList: [analysisOnly.toObject()] } } })
  assert(html.includes('Yield: Not listed'))
  assert(html.includes('/id/cmcc-test?database=staging'))
  html = await render(Card, { reaction: { reaction_id: 'cmcc-test', data: {} } })
  assert(html.includes('Uploaded by Not listed'))
  html = await render(Outcomes, { outcome: analysisOnly.toObject() })
  assert(html.includes('No identified products reported'))
  assert(html.includes('Measured diffraction pattern'))
  html = await render(Compound, { component: { identifiersList: [{ type: 6, value: '<b>sample</b>' }] } })
  assert(html.includes('&lt;b&gt;sample&lt;/b&gt;'))
  assert(!html.includes('<b>sample</b>'))
  html = await render(Compound, { component: { identifiersList: [{ type: 5, value: 'other identifier' }], crystalParameters: {
    type: 2, databaseIdentifier: {type: 2, value: '1234567'},
    a: {value: 0.0000005, units: 2}, alpha: {value: 90, units: 1},
    details: 'Original cell source retained',
  } } })
  assert(html.includes('other identifier'))
  assert(html.includes('CSD'))
  assert(html.includes('1234567'))
  assert(html.includes('Original cell source retained'))
  // Exercise the generated new proto through real binary decoding, including
  // product CrystalParameters and the compatible new ANGSTROM enum.
  assert.equal(pb.Length.LengthUnit.ANGSTROM, 6)
  const crystalProduct = new pb.ProductCompound()
  crystalProduct.addIdentifiers(new pb.CompoundIdentifier().setType(2).setValue('[Na+].[Cl-]'))
  crystalProduct.setCrystalParameters(new pb.CrystalParameters()
    .setType(pb.CrystalParameters.CrystalStructureType.CUBIC)
    .setDatabaseIdentifier(new pb.CrystalStructureDatabaseIdentifier().setType(2).setValue('source-reported-reference'))
    .setA(new pb.Length().setValue(5.4).setUnits(pb.Length.LengthUnit.ANGSTROM)))
  const restored = pb.ProductCompound.deserializeBinary(crystalProduct.serializeBinary()).toObject()
  html = await render(Compound, { component: restored })
  assert(html.includes('SMILES'))
  assert(html.includes('[Na+].[Cl-]'))
  assert(html.includes('Å'))
  assert(html.includes('source-reported-reference'))
  // The real protobuf map becomes tuple entries after binary decoding. Display
  // the source representation limits alongside an inorganic formula-unit token.
  const limitedProduct = new pb.ProductCompound()
  limitedProduct.addIdentifiers(new pb.CompoundIdentifier().setType(2).setValue('[Cd+2].[S-2]'))
  const representationNote = 'Nominal CdS formula unit only; no lattice connectivity or independently measured free ions.'
  limitedProduct.getFeaturesMap().set('structure_representation', new pb.Data().setStringValue(representationNote))
  const decodedLimitedProduct = pb.ProductCompound.deserializeBinary(limitedProduct.serializeBinary()).toObject()
  html = await render(Compound, { component: decodedLimitedProduct })
  assert(html.includes('[Cd+2].[S-2]'))
  assert(html.includes('Representation limits'))
  assert(html.includes(representationNote))
  assert(html.indexOf('class="raw"') < html.indexOf('class="structure-details'),
    'The Raw button must occupy its header column before full-width structure rows')
  html = await render(Compound, { component: { featuresMap: {
    structure_representation: {stringValue: '<b>Composition only</b>'},
  } } })
  assert(html.includes('&lt;b&gt;Composition only&lt;/b&gt;'))
  assert(!html.includes('<b>Composition only</b>'))
  html = await render(Compound, { component: { identifiersList: [{type: 2, value: 'CCO'}] } })
  assert(!html.includes('Representation limits'), 'Exact graphs without a supplied note must not gain an invented caveat')
  const { productYield } = loadUtility('reactionSummary')
  assert.equal(productYield({ measurementsList: [{ type: 3, percentage: { value: 0 } }] }), '0%')
  assert.equal(productYield({ measurementsList: [{ type: 1, percentage: { value: 80 } }] }), 'Not listed')
  console.log('Actual Vue templates passed: analysis-only first outcomes, later products, SMILES preference, zero yields/conversion, absent provenance, escaped names/representation limits, formula-unit notes, Raw placement and crystal display.')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
