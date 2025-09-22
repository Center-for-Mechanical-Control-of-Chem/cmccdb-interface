

<script>
export default {
    props:{
        field: String,
        index: Number,
        data: Object,
        types: Object,
        labeled: Boolean,
        vectorType: Boolean,
        path: Array,
        closed: Boolean
    },
    emits: ["updateValue", "addField", "removeField"],
    data() {
        // console.log(this.field, this.index, this.data, this.types);
        let rt = this.vectorType === true ? this.types[this.field] : this.types[this.field];
        let props = [];
        if (typeof rt === "object") {
          let baseProps = [];
          let containerProps = [];
          let rawProps = [];
          for (const [key, val] of Object.entries(rt)) {
            if (["Type", "KindCase"].includes(key)) {
              baseProps.push(key);
            } else if (this.isContainerType(val)) {
              containerProps.push(key);
            } else {
              rawProps.push(key);
            }
          }
          props = [...baseProps, ...containerProps, ...rawProps];
        }
        return {
            realType: rt,
            subprops: props,
            mutData: (
                typeof this.data === "undefined" ? {} : (
                    this.vectorType === true ? this.data[this.index] : this.data[this.field]
                )
            ),
            modelData: (
                typeof this.data === "undefined" ? "" : (
                    this.vectorType === true ? this.data[this.index] : this.data[this.field]
                )
            ),
            kindToggle: 0,
            kindValue: "N/A",
            displayBody: (this.isContainerType(rt) && this.closed) ? false : true,
            fieldLabel: this.prepFieldName(this.field)
        }
    },
    methods: {
        toggleDisplay() { 
          this.displayBody = !this.displayBody
        },
        updateValue() {
          this.$emit('updateValue', {"path":this.path, "value":this.modelData})
        },
        addField() {
          this.$emit('addField', {"path":this.path})
        },
        removeField() {
          this.$emit('removeField', {"path":this.path})
        },
        bubbleValue(subdata) {
          this.$emit('updateValue', subdata);
        },
        bubbleAdd(subdata) {
          this.$emit('addField', subdata);
        },
        bubbleRemove(subdata) {
          this.$emit('removeField', subdata);
        },
        setKindToggle(subdata) {
          this.kindValue = "N/A";
          this.kindToggle = subdata["value"];
          this.kindValue = this.getKindValue();
          this.bubbleValue(subdata);
        },
        getKindValue() {
          for (const [key, value] of Object.entries(this.realType["KindCase"]["allowedValues"])) {
            if (value === this.kindToggle) {
              return key.split("_").map(
                (s)=>s.charAt(0) + s.slice(1, s.length).toLowerCase()
              ).join("")
            }
          }
          return "MissingValue"
        },
        isContainerType(realType) {
          return (
            typeof realType !== "string" 
            && typeof realType["allowedValues"] === "undefined"
          )
        },
        prepFieldName(field) {
          if (field.endsWith("List")) {
            return field.slice(0, -4)
          } else if (field.endsWith("Map")) {
            return field.slice(0, -3)
          } else if (field.endsWith("Id")) {
            return field.slice(0, -2) + "ID"
          } else if (field.endsWith("Url")) {
            return field.slice(0, -3) + "URL"
          } else {
            return field
          }
        },
    }
}
</script>

<template lang="pug">
template(
    v-if='typeof realType !== "undefined" && path.length < 15'
)
  template(
    v-if='Array.isArray(mutData)'
    )
    .suboptions-section.block
      .suboptions-title(v-if='labeled' @click='toggleDisplay' :class='displayBody ? "" : "closed"') {{fieldLabel}} 
        i.material-icons expand_less
      template(v-if="displayBody")
        .suboptions-list(:class='labeled ? "bordered":""')
          .suboptions-list-options
            .suboptions-list-item(v-for='(subVal, subIdx) of mutData')
              AdvancedSearchInput(
                :index='subIdx'
                :field='field'
                :data='mutData'
                :types='types'
                :labeled='false'
                :vectorType='true'
                :path='[...path, subIdx]'
                @updateValue='bubbleValue'
                @addField='bubbleAdd'
                @removeField='bubbleRemove'
                )
          button.addsub-list-item(
            @click='addField'
            ) +
          button.addsub-list-item(
            @click='removeField'
            ) -
    
  template(
    v-else-if='typeof realType["KindCase"] !== "undefined"'
    )
    .suboptions-section.block
      .suboptions-title(v-if='labeled' @click='toggleDisplay' :class='displayBody ? "" : "closed"') {{fieldLabel}} 
        i.material-icons expand_less
      template(v-if="displayBody")
        AdvancedSearchInput(
          :field='"KindCase"'
          :data='mutData'
          :types='realType'
          :labeled='false'
          :path='[...path, "KindCase"]'
          @updateValue='setKindToggle'
        )
        AdvancedSearchInput(
          v-if='kindValue !== "N/A" && kindValue !== "KindNotSet"'
          :field='kindValue'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, kindValue]'
          @updateValue='bubbleValue'
          @addField='bubbleAdd'
          @removeField='bubbleRemove'
        )
    
  template(
    v-else-if='(typeof realType["Value"] !== "undefined") && (typeof realType["Precision"] !== "undefined") && (typeof realType["Units"] !== "undefined")'
    )
    .suboptions-section.block
      .suboptions-title(v-if='labeled' @click='toggleDisplay' :class='displayBody ? "" : "closed"') {{fieldLabel}} 
        i.material-icons expand_less
      template(v-if="displayBody")
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
          @addField='bubbleAdd'
          @removeField='bubbleRemove'
          )
        AdvancedSearchInput(
          :field='"Precision"'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :path='[...path, "Precision"]'
          @updateValue='bubbleValue'
        )
  template(
    v-else-if='field === "allowedValues"'
    )
    select(
      v-model='modelData'
      @change='updateValue'
    )
      option(
        v-for='(optVal, optName) in realType'
        :value='optVal'
      ) {{optName}}
  .suboptions-section(
    v-else 
    :class='isContainerType(realType) ? "" : "flex"'
  )
    template(v-if='labeled')
      .suboptions-title(v-if='isContainerType(realType)' @click="toggleDisplay" :class='displayBody ? "" : "closed"') {{fieldLabel}}
        i.material-icons expand_less
      .suboptions-label(v-else) {{fieldLabel}}:
    template(v-if='displayBody')
      input.string-value(
        v-if='realType === "string"'
        v-model='modelData'
        @input='updateValue'
      )
      input.string-value(
        v-else-if='realType === "Concrete Type:string"'
        v-model='modelData'
        @input='updateValue'
      )
      input.number-value(
        v-else-if='realType === "Concrete Type:number"'
        v-model='modelData'
        @input='updateValue'
      )
      input.boolean-value(
        v-else-if='realType === "Concrete Type:boolean"'
        type='checkbox'
        v-model='modelData'
        @input='updateValue'
      )
      .div(
        v-else-if='typeof realType === "string"'
      ) {{realType}}
      template(
        v-else
        v-for='subsubfield of subprops'
      )
        AdvancedSearchInput(
          :field='subsubfield'
          :data='mutData'
          :types='realType'
          :labeled='true'
          :closed='true'
          :path='[...path, subsubfield]'
          @updateValue='bubbleValue'
          @addField='bubbleAdd'
          @removeField='bubbleRemove'
          )
template(v-else)
   p() ERROR INTERPRETING: {{fieldLabel}} {{realType}}

</template>

<style lang="sass" scoped>
@import '@/styles/vars'
@import '@/styles/transition'
@import '@/styles/tabs'
.search-options
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
    width: 100%
    min-width: 50rem
    display: block
    margin-left: 0.25rem
  .suboptions-section .flex
      display: flex
  .suboptions-title
    display: block
    color: white
    background: $bg-primary
    font-weight: 700
    padding:0.2rem
    padding-left:0.5rem
    margin-bottom: 0.1rem
    border-top-right-radius: 0.25rem
    border-top-left-radius: 0.25rem
    &.closed
      border-radius: 0.25rem
      i
        transform: rotate(180deg)
  .suboptions-label
    display: flex
    color: $bg-primary
  .suboptions-list
    display: block
    width: 100%
    .bordered
      border-bottom-left-radius: 0.25rem
      border-bottom-right-radius: 0.25rem
      border: 1px solid $medgrey
  .suboptions-list-item:not(:last-child)
    border-bottom: 1px solid $bg-primary
  input.string-value
    display: flex
  button.addsub-list-item
    width: 100px
    margin:.1rem
    margin-left: 0.5rem
    text-align: center
</style>