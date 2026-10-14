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
import LoadingSpinner from '@/components/LoadingSpinner'
import conditionUtil from '@/utils/conditions'
import outcomesUtil from '@/utils/outcomes'
import reaction_pb from 'cmccdb-schema'
import CopyButton from '@/components/CopyButton'
import { summaryOutcome, preferredIdentifier, productYield, formatPercentage, reactionIdentifier } from '@/utils/reactionSummary'

export default {
  props: {
    reaction: Object,
    isSelected: Boolean,
    isSelectable: Boolean
  },
  components: {
    LoadingSpinner,
    CopyButton
  },
  data() {
    return {
      formattedResults: [],
      selectedReactions: [],
      reactionTable: null
    }
  },
  computed: {
    reactionId() { return reactionIdentifier(this.reaction) },
    reactionData() { return this.reaction?.data || {} },
    summary() { return summaryOutcome(this.reactionData) },
    products() { return this.summary.productsList || [] },
    creator() { return this.reactionData.provenance?.recordCreated?.person || {} },
    uploadDate() {
      const value = this.reactionData.provenance?.recordCreated?.time?.value
      const date = value ? new Date(value) : null
      return date && !isNaN(date.valueOf()) ? date.toLocaleDateString() : 'Not listed'
    },
    provenance() { return this.reactionData.provenance || {} },
  },
  methods: {
    getSearchParams() {
      const urlParams = new URLSearchParams(window.location.search)
      return urlParams
    },
    getDBQuery() {
      const searchParams = this.getSearchParams();
      const db = searchParams.get("database");
      const queryString=(db !== null && db.length) ? `?database=${db}` : "";
      return queryString
    },
    getDBName() {
      const searchParams = this.getSearchParams();
      const db = searchParams.get("database");
      const queryString=(db !== null && db.length) ? `${db}` : "cmcc";
      return queryString
    },
    getReactionTable() {
      const queryString = this.getDBQuery()
      fetch(`/api/render/${this.reactionId}${queryString}`)
        .then(response => {
          if (!response.ok) throw new Error('Reaction rendering failed')
          return response.json()
        })
        .then(responseData => { this.reactionTable = responseData })
        .catch(() => { this.reactionTable = '[Reaction cannot be displayed]' })
    },
    preferredIdentifier,
    productYield,
    getConversion() { return formatPercentage(this.summary.conversion) },
    conditionsAndDuration(reaction) {
      const details = []
      const conditions = reaction?.conditions || {}
      // get temp
      const tempSetPoint = conditionUtil.tempSetPoint(conditions.temperature?.setpoint)
      if (tempSetPoint !== "None")
        details.push(`at ${tempSetPoint}`)

      // get Pressure
      const pressureSetPoint = conditionUtil.pressureSetPoint(conditions.pressure?.setpoint)
      if (pressureSetPoint !== "None")
        details.push(`under ${pressureSetPoint}`)

      // get duration
      const formattedTime = outcomesUtil.formattedTime(this.summary.reactionTime)
      if (formattedTime && formattedTime !== "None" && formattedTime !== undefined)
        details.push(`for ${formattedTime}`)

      // get stir
      const stirType = conditionUtil.stirType(conditions.stirring?.type)
      if (stirType && stirType !== "None" && stirType !== undefined)
        details.push(`under ${stirType}`)

      // get mechano
      const mechType = conditionUtil.mechType(conditions.mechanochemistry?.type)
      if (mechType && mechType !== "None" && mechType !== undefined)
        details.push(`with ${mechType}`)

      return details
    },
    productIdentifier(identifier) {
      const identifierTypes = reaction_pb.CompoundIdentifier.CompoundIdentifierType
      const identifierType = Object.keys(identifierTypes).find(key => identifierTypes[key] == identifier.type)
      return `${identifierType || "Identifier"}: ${identifier.value}`
    },
    updateSelectedReactions(event) {
      if (event.target.checked) {
        this.selectedReactions.push(event.target.value)
      } else {
        let idx = this.selectedReactions.indexOf(event.target.value)
        if (idx !== -1) {
          this.selectedReactions.splice(idx, 1)
        }
      }
    },
  },
  async mounted() {
    this.getReactionTable()
  },
}
</script>

<template lang="pug">
.reaction-container
  .row(:class='isSelected ? "selected" : ""')
    .select(v-if='isSelectable')
      input(
        type="checkbox"
        :id='"select_"+reactionId'
        :value='reactionId'
        :checked='isSelected'
        @change='$emit("clickedSelect", $event)'
      )
      label(:for='"select_"+reactionId') Select reaction
    .reaction-table(
      v-html='reactionTable'
      v-if='reactionTable'
    )
    LoadingSpinner(v-else)
    .info
      .col.full
        router-link(
          :to='{ name: "reaction-view", params: {reactionId: reactionId}, query:{database:getDBName()}}'
        ) 
          button View Full Details
      .col
        .conversion Conversion: {{getConversion()}}
        .conditions Conditions: {{conditionsAndDuration(reactionData).join("; ") || "Not Listed"}}
        template(v-if='products.length')
          .product(v-for='(product, idx) in products' :key='idx')
            .yield Yield{{products.length > 1 ? ` (product ${idx + 1})` : ""}}: {{productYield(product)}}
            .smile(v-if='preferredIdentifier(product)')
              CopyButton(:textToCopy='preferredIdentifier(product).value')
              .value Product {{productIdentifier(preferredIdentifier(product))}}
        .yield(v-else) Yield: Not listed
      .col
        .creator Uploaded by {{creator.name || "Not listed"}}{{creator.organization ? `, ${creator.organization}` : ""}}
        .date Uploaded on {{uploadDate}}
        .doi DOI: {{provenance.doi || "Not listed"}}
        .publication(v-if='provenance.publicationUrl')
          a(
            :href='provenance.publicationUrl'
            target="_blank"
          ) Publication URL
        .dataset Dataset: {{reaction.dataset_id}}
</template>

<style lang="sass" scoped>
@import '@/styles/vars.sass'
.reaction-container
  text-decoration: none
  .row
    background-color: white
    border-radius: 0.25rem
    padding: 0.75rem
    margin-bottom: 1rem
    transition: 0.25s
    border: 4px solid white
    &:hover
      box-shadow: 0 0 5px $darkgrey
    .select
      input, label
        cursor: pointer
    .reaction-table
      color: black
      max-width: 100%
      overflow-x: auto
    .info
      display: grid
      grid-template-columns: repeat(2, minmax(0, 1fr))
      row-gap: 0.5rem
      column-gap: 1rem
      margin-top: 1rem
      .col.full
        grid-column: 1/3
        button
          font-size: 1.2rem
      .col
        min-width: 0
        overflow-wrap: anywhere
        *
          margin-top: 0.5rem
      .smile
        display: flex
        column-gap: 0.5rem
        align-items: center
        margin-top: 0.25rem
        .value
          min-width: 0
          flex: 1
          white-space: nowrap
          overflow: hidden
          text-overflow: ellipsis
    &.selected
      border-color: $bg-primary
</style>
