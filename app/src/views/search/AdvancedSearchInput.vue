

<script>
export default {
    props:{
        field: String,
        index: Number,
        data: Object,
        types: Object,
        labeled: Boolean,
        vectorType: Boolean,
        path: Array
    },
    emits: ["updateValue"],
    data() {
        console.log(this.field, this.data, this.types);
        return {
            realType: this.vectorType === true ? this.types : this.types[this.field],
            mutData: (
                typeof this.data === "undefined" ? {} : (
                    this.vectorType === true ? this.data : this.data[this.field]
                )
            ),
            modelData: (
                typeof this.data === "undefined" ? "" : (
                    this.vectorType === true ? this.data : this.data[this.field]
                )
            ),
            kindToggle: ""
        }
    },
    methods: {
        emitUpdateValue() {
            this.$emit('updateValue', {"path":this.path, "value":this.modelData})
        },
        bubbleValue(subdata) {
            if (this.path.length < 2) {
                this.$emit('updateValue', subdata)
            } else {
                this.$emit('bubbleValue', subdata)
            }
        }
    }
}
</script>

<template lang="pug">
template(
    v-if="path.length < 8"
)
    template(
      v-if='Array.isArray(data)'
      v-for='(subVal, subIdx) of data'
      )
      AdvancedSearchInput(
        :index='subIdx'
        :data='subVal'
        :types='types'
        :labeled='true'
        :vectorType='true'
        :path='[...path, subIdx]'
        @updateValue='bubbleValue'
        )
    template(
      v-else-if='realType.hasOwnProperty("KindCase")'
      )
      p() {{field}} {{realType}}
    template(
      v-else-if='realType.hasOwnProperty("Value") && realType.hasOwnProperty("Precision") && realType.hasOwnProperty("Units")'
      )
       AdvancedSearchInput(
          :field='"Units"'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, "Units"]'
          @updateValue='bubbleValue'
          )
        AdvancedSearchInput(
          :field='"Value"'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, "Value"]'
          @updateValue='bubbleValue'
          )
        AdvancedSearchInput(
          :field='"Precision"'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, "Precision"]'
          @updateValue='bubbleValue'
          )
    .suboptions-section(v-else)
      template(v-if='labeled')
        .suboptions-title(v-if='typeof types !== "string"') {{field}}
        .suboptions-label(v-else) {{field}}:
      input(
        v-if='realType === "string"'
        v-model='modelData'
        @input='updateValue'
      )
      input(
        v-else-if='realType === "Concrete Type:string"'
        v-model='modelData'
        @input='updateValue'
      )
      input(
        v-else-if='realType === "Concrete Type:number"'
        v-model='modelData'
        @input='updateValue'
      )
      input(
        v-else-if='realType === "Concrete Type:boolean"'
        type='checkbox'
        v-model='modelData'
        @input='updateValue'
      )
      .div(
        v-else-if='typeof realType === "string"'
      ) {{realType}}
      .subsection(
        v-else
        v-for='(subsubvals, subsubfield) in realType'
      )
       AdvancedSearchInput(
          :field='subsubfield'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, subsubfield]'
          @updateValue='bubbleValue'
          )
template(v-else)
   p() {{realType}}

</template>

<style lang="sass" scoped>
@import '@/styles/vars'
@import '@/styles/transition'
@import '@/styles/tabs'
.search-options
  min-height: 90vh
  .options-title
    font-size: 1.5rem
    font-weight: 700
    cursor: pointer
    padding: 0.5rem 1rem
    border-top-left-radius: 0.25rem
    border-top-right-radius: 0.25rem
    margin-top: 1rem
    color: white
    background-color: $bg-primary
    display: flex
    align-content: center
    justify-content: space-between
    width: 100%
    box-sizing: border-box
    transition: 0.25s
    i
      font-size: 2rem
      transition: 0.25s
    &.closed
      border-radius: 0.25rem
      i
        transform: rotate(180deg)
    &:first-child
      margin-top: 0
    &#searchParameters
      cursor: default
  .options-container
    background-color: white
    border-bottom-left-radius: 0.25rem
    border-bottom-right-radius: 0.25rem
    padding: 1rem
    margin-bottom: 1rem
    display: grid
    row-gap: 1rem
    border: 1px solid $medgrey
    .subtitle
      font-size: 1.25rem
      font-weight: 700
      margin-bottom: 0.5rem
    .options
      margin-left: 1rem
    button
      display: flex
      align-items: center
      i
        font-size: 1.1rem
    input, select
      font-size: 1rem
    .search-button
      grid-column: 1 / 2
      margin-top: 1rem
      button
        font-size: 1.2rem
        padding: 0.5rem 1rem
  .suboptions-section
    padding: 1rem
  .suboptions-title
    display: block
    color: $bg-primary
  .suboptions-title
    display: flex
    color: $bg-primary
</style>