<script>
import { collectAuxiliaryData, dataPresentation } from "@/utils/auxiliaryData"

export default {
  props: { reaction: Object, reactionId: String, database: String },
  data() { return { failedImages: {} } },
  computed: {
    entries() {
      return collectAuxiliaryData(this.reaction).map(entry => dataPresentation(entry, this.reactionId, this.database))
    },
  },
}
</script>

<template lang="pug">
.auxiliary-grid
  article.auxiliary-card(v-for='entry in entries' :key='entry.id')
    .card-heading
      h3 {{entry.label}}
      span.format(v-if='entry.data.format') {{entry.data.format}}
    p.source(v-if='entry.context') {{entry.context}}
    p.description(v-if='entry.data.description') {{entry.data.description}}
    a.image-link(v-if='entry.isImage && entry.href && !failedImages[entry.id + entry.href]' :href='entry.href' target='_blank' rel='noopener noreferrer')
      img(:src='entry.href' :alt='entry.data.description || entry.label' loading='lazy' @error='failedImages[entry.id + entry.href] = true')
    p.preview-error(v-if='entry.isImage && failedImages[entry.id + entry.href]' role='status') This image could not be previewed. Open the file to view it.
    pre.data-value(v-if='entry.value !== undefined') {{entry.value === "" ? "Empty string" : entry.value}}
    p.preview-error(v-if='entry.data.url && !entry.href') File link unavailable: {{entry.data.url}}
    .file-action(v-if='entry.href')
      a(:href='entry.href' target='_blank' rel='noopener noreferrer' :download='entry.data.bytesValue ? entry.downloadName : null') {{entry.isImage ? "Open full-size image" : "Open / download file"}}
</template>

<style lang="sass" scoped>
@import '@/styles/vars'
.auxiliary-grid
  display: grid
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr))
  gap: 1rem
  min-width: 0
  .auxiliary-card
    min-width: 0
    border: 1px solid $medgrey
    border-radius: 0.5rem
    padding: 1rem
    overflow-wrap: anywhere
  .card-heading
    display: flex
    align-items: baseline
    justify-content: space-between
    gap: 0.5rem
    h3
      margin: 0
      font-size: 1.1rem
    .format
      font-size: 0.75rem
      color: $darkgrey
      text-transform: uppercase
  .source
    font-size: 0.8rem
    color: $darkgrey
    margin: 0.35rem 0 0.75rem
  .description
    white-space: pre-wrap
    line-height: 1.5
  .image-link
    display: block
    background: $lightgrey
    border-radius: 0.25rem
    img
      display: block
      width: 100%
      max-height: 24rem
      object-fit: contain
  .data-value
    white-space: pre-wrap
    overflow-wrap: anywhere
    font-family: inherit
    margin: 0.75rem 0
    max-height: 24rem
    overflow: auto
  .preview-error
    padding: 0.75rem
    background: $lightgrey
    color: $darkgrey
  .file-action
    margin-top: 0.75rem
  a
    color: $bg-primary
    &:focus-visible
      outline: 2px solid $bg-primary
      outline-offset: 3px
</style>
