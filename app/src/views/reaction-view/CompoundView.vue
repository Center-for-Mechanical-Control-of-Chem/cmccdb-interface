<!--
 Copyright 2023 Open Reaction Database Project Authors

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
-->

<script>
import reaction_pb from "cmccdb-schema"
import FloatingModal from "../../components/FloatingModal"
import { amountObj, amountStr } from "../../utils/amount"
import CopyButton from "../../components/CopyButton"

export default {
  props: {
    component: Object,
  },
  components: {
    "floating-modal": FloatingModal,
    CopyButton
  },
  watch: {
    component: {
      handler(val) {
        this.getCompoundSVG(val)
      },
      deep: true,
      immediate: true,
    },
  },
  data() {
    return {
      compoundSVG: null,
      renderingRequest: 0,
      showRawData: false,
    }
  },
  computed: {
    compoundName() {
      const identifiers = this.component?.identifiersList || []
      return identifiers.find(identifier => identifier.type === 6)?.value ||
        identifiers.find(identifier => identifier.value)?.value || 'Structure not available'
    },
    smiles() { return this.component?.identifiersList?.find(identifier => identifier.type === 2)?.value || '' },
    representationNote() {
      const features = this.component?.featuresMap
      const representation = Array.isArray(features) ?
        features.find(entry => entry?.[0] === 'structure_representation')?.[1] :
        features?.structure_representation
      return typeof representation?.stringValue === 'string' ? representation.stringValue : ''
    },
    crystalRows() {
      const crystal = this.component?.crystalParameters
      if (!crystal) return []
      const rows = []
      const enums = reaction_pb.CrystalParameters.CrystalStructureType
      if (crystal.type) rows.push({label: 'Crystal system', value: Object.keys(enums).find(key => enums[key] === crystal.type) || crystal.type})
      const identifier = crystal.databaseIdentifier
      if (identifier?.value) rows.push({label: identifier.type === 2 ? 'CSD' : 'Crystal database identifier', value: identifier.value})
      for (const field of ['a', 'b', 'c', 'alpha', 'beta', 'gamma']) {
        const quantity = crystal[field]
        if (quantity?.value == null) continue
        const units = field.length === 1 ? reaction_pb.Length.LengthUnit : reaction_pb.Angle.AngleUnit
        const unit = Object.keys(units).find(key => units[key] === quantity.units)
        const display = number => Number.isFinite(number) ? Number(number.toPrecision(7)) : number
        rows.push({label: field, value: `${display(quantity.value)}${quantity.precision == null ? '' : ` ± ${display(quantity.precision)}`} ${unit === 'ANGSTROM' ? 'Å' : unit || 'unit not listed'}`})
      }
      if (crystal.details) rows.push({label: 'Details', value: crystal.details})
      return rows
    },
    compoundAmountObj () {
      return amountObj(this.component?.amount)
    },
    compoundAmount () {
      return amountStr(this.compoundAmountObj)
    },
    compoundRole () {
      const role = this.component?.reactionRole
      const types = reaction_pb.ReactionRole.ReactionRoleType
      return Object.keys(types).find(key => types[key] == role) || (this.component?.measurementsList ? "product" : "Not listed")
    },
    rawData () {
      const returnObj = {}
      // set identifiers
      const idTypes = reaction_pb.CompoundIdentifier.CompoundIdentifierType
      returnObj["identifiers"] = this.component?.identifiersList?.map((identifier) => {
        return {
          type: Object.keys(idTypes).find(key => idTypes[key] == identifier.type),
          value: identifier.value
        }
      })
      // set amount
      if (this.component?.amount) {
        returnObj["amount"] = {
          [this.compoundAmountObj.unitCategory]: {
            value: this.compoundAmountObj.unitAmount,
            units: this.compoundAmountObj.unitType,
          }
        }
      }
      // set preparations
      if (this.component?.preparationsList?.length) {
        const prepTypes = reaction_pb.CompoundPreparation.CompoundPreparationType
        returnObj["preparations"] = this.component.preparationsList.map(prep => {
          return {
            type: Object.keys(prepTypes).find(key => prepTypes[key] == prep.type),
            details: prep.details,
          }
        })
      }
      if (this.component?.isDesiredProduct) {
        returnObj["is_desired_product"] = this.component.isDesiredProduct
      }
      if (this.component?.isolatedColor) {
        returnObj["isolated_color"] = this.component.isolatedColor
      }
      if (this.component?.texture) {
        const textureTypes = reaction_pb.Texture.TextureType
        const textureType = Object.keys(textureTypes).find(key => textureTypes[key] == this.component.texture.type)
        const textureObj = {type: textureType}
        if (this.component.texture.details)
          textureObj.details = this.component.texture.details
        returnObj["texture"] = textureObj
      }
      returnObj["reaction_role"] = this.compoundRole
      if (this.component?.crystalParameters) returnObj.crystal_parameters = this.component.crystalParameters
      return returnObj
    },
    gridColumns () {
      return `1fr repeat(${this.component?.amount ? 3 : 2}, auto)`
    }
  },
  methods: {
    async getCompoundSVG(component) {
      const request = ++this.renderingRequest
      this.compoundSVG = null
      const smiles = component?.identifiersList?.find(identifier => identifier.type === 2 && identifier.value)
      if (!smiles) return
      const compound = new reaction_pb.Compound()
      const identifier = compound.addIdentifiers()
      identifier.setValue(smiles.value)
      identifier.setType(reaction_pb.CompoundIdentifier.CompoundIdentifierType.SMILES)
      try {
        const response = await fetch('/api/render/compound/svg', {
          method: 'POST', body: compound.serializeBinary(),
          headers: {'Content-Type': 'application/octet-stream'},
        })
        if (!response.ok) return
        const svg = await response.json()
        if (request === this.renderingRequest && typeof svg === 'string' && svg.includes('<svg')) this.compoundSVG = svg
      } catch (_) {
        // The source identifier stays visible when rendering is unavailable.
      }
    },
  },
}
</script>

<template lang="pug">
.compound-view(
  :style='{gridTemplateColumns: gridColumns}'
)
  .label Compound
  .label(v-if='component?.amount') Amount
  .label Role
  .label Raw
  .svg(v-if='compoundSVG' v-html='compoundSVG')
  .svg(v-else) {{compoundName}}
  .amount(v-if='component?.amount') {{compoundAmount}}
  .role {{compoundRole.toLowerCase()}}
  .raw
    .button(@click='showRawData=true') &lt;>
  .structure-details.smiles(v-if='smiles')
    .label SMILES
    .value {{smiles}}
    CopyButton(:textToCopy='smiles')
  .structure-details(v-if='representationNote')
    .label Representation limits
    .value {{representationNote}}
  .structure-details(v-if='crystalRows.length')
    template(v-for='row in crystalRows' :key='row.label')
      .label {{row.label}}
      .value {{row.value}}
  floating-modal(
    v-if='showRawData'
    title="Raw Data"
    @closeModal='showRawData=false'
  )
    .data
      pre(v-for='identifier in rawData.identifiers') identifiers: {{identifier}}
      pre(v-if='rawData.amount') amount: {{rawData.amount}}
      pre(v-if='rawData.crystal_parameters') crystal_parameters: {{rawData.crystal_parameters}}
      pre reaction_role: {{rawData.reaction_role}}
      pre(v-if='rawData.is_desired_product') is_desired_product: {{rawData.is_desired_product}}
      pre(v-if='rawData.isolated_color') isolated_color: {{rawData.isolated_color}}
      pre(v-if='rawData.texture') texture: {{rawData.texture}}
      pre(v-for='prep in rawData.preparations') preparations: {{prep}}
</template>

<style lang="sass" scoped>
@import '@/styles/vars.sass'
.compound-view
  display: grid
  // padding: 1rem
  align-items: center
  *
    padding: 0.5rem
  .label
    font-weight: 700
    border-bottom: 1px solid #000
  .raw
    .button
      padding: 0.5rem
      background-color: $darkgrey
      color: white
      border-radius: 0.25rem
      cursor: pointer
  .data
    width: 100%
    height: 100%
    overflow-x: auto
</style>
<style lang="sass" scoped>
.structure-details
  grid-column: 1 / -1
  display: grid
  grid-template-columns: auto minmax(0, 1fr)
  gap: 0.5rem
  overflow-wrap: anywhere
  &.smiles
    grid-template-columns: auto minmax(0, 1fr) auto
</style>
