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
import { conditionRows } from "@/utils/conditionDisplay"

export default {
  props: { conditions: Object, display: String },
  computed: {
    rows() { return conditionRows(this.conditions, this.display) },
  },
}
</script>

<template lang="pug">
.conditions-view
  dl.condition-fields(v-if='rows.length')
    .condition-row(v-for='(row, index) in rows' :key='index')
      dt {{row.label}}
      dd {{row.value}}
  p.empty-state(v-else) No conditions recorded for this category.
</template>

<style lang="sass" scoped>
@import '@/styles/vars'
.conditions-view
  width: 100%
  min-width: 0
  .condition-fields
    margin: 0
    border: 1px solid $medgrey
    border-radius: 0.5rem
    overflow: hidden
  .condition-row
    display: grid
    grid-template-columns: minmax(10rem, 32%) minmax(0, 1fr)
    border-bottom: 1px solid $medgrey
    &:last-child
      border-bottom: none
    dt, dd
      margin: 0
      padding: 0.75rem 1rem
      overflow-wrap: anywhere
      white-space: pre-wrap
    dt
      background-color: $lightgrey
      font-weight: 700
      color: $bg-primary
    dd
      line-height: 1.5
  .empty-state
    color: $darkgrey
    margin: 1rem 0
  @media (max-width: 600px)
    .condition-row
      grid-template-columns: minmax(0, 1fr)
      dt
        padding-bottom: 0.25rem
      dd
        padding-top: 0.25rem
</style>
