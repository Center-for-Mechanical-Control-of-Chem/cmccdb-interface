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
import ModalKetcher from '@/components/ModalKetcher'
// import jspb from "google-protobuf"
import reaction_pb from "cmccdb-schema"
import AdvancedSearchInput from './AdvancedSearchInput'

export default {
  components: {
    AdvancedSearchInput
  },
  emits: ["searchOptions"],
  data() {
    return {
        messageObj: null,
        rootObj: reaction_pb,
        protoTree: {},
        protoSubtrees: {},
        displayedOptions: {},
        displayedFields: {},
        displayedKeys: null,
        queryData: {}
    }
  },
  // mounted() {
  // }
  // computed: {
  //   defaultQuery() {
  //     return this.$route.query
  //   }
  // },
  methods: {

    reflectReturnType(getter) {
      // TODO: make this less of a hack
      let retStr = getter.toString();
      // console.log(retStr);
      const re = /proto\.cmccdb\.[\w.]+/;
      let res = retStr.match(re);
      if (res !== null) {
        res = res[0].split(".", 4)
        if (res.length == 3) {
            retStr = res[res.length-1];
        } else {
            retStr = res[res.length-2] + "." + res[res.length-1];
        }
      } else {
        const tre = /type {.+?}/;
        res = retStr.match(tre);
        if (res !== null) {
          retStr = res[0].split("{")[1].slice(0, -1);
        }
      }
      return retStr;
    },

    reflectFieldNames(root) {
      let fieldTypes = {};
      Object.keys(Object.getPrototypeOf(root)).map( (field) => {
        if (field.startsWith('get')) {
          fieldTypes[field.slice(3, field.length+1)] = this.reflectReturnType(root[field]);
        }
      })

      return fieldTypes;

    },

    loadBaseMessage() {
      if (this.messageObj === null) {
        this.messageObj = {};
        Object.keys(reaction_pb).map((field) => {
          this.messageObj[field] = new reaction_pb[field];
          Object.entries(reaction_pb[field]).map(([subfield, value]) => {
              if (value !== null && typeof value === "object" && !Array.isArray(value)) {
                  this.messageObj[field+"."+subfield] = value;
                  }
              }
            )
          }
        )
      }
      
      return this.messageObj;
    },

    loadProtoSubTypes(key) {
      if (typeof this.protoTree[key] === "undefined") {
        // console.log("!!!", key);
        const bm = this.loadBaseMessage();
        if (typeof bm[key] !== "undefined") {
          this.protoTree[key] = this.reflectFieldNames(bm[key]);
        } else {
          this.protoTree[key] = null;
        }
      }
      
      return this.protoTree[key];
    },

    getPrimaryTree() {
      return this.buildSubTree("Reaction", 1)
    },

    getKeys() {
        return Object.keys(this.getPrimaryTree());
    },

    getTypes() {
        return this.loadProtoSubTypes("Reaction");
    },

    getField(f) {
        return this.getPrimaryTree()[f];
    },

    resolveType(val, recursionDepth=-1) {
      // console.log(val, recursionDepth)
      let rv = val;
      if (val == "string") {
        rv = val
      } else if (["int32"].includes(val)){
        rv = val
      } else if (val.startsWith("!")) {
        rv = val;
      } else if (recursionDepth != 0) {
        //TODO: map strings to enums
        // console.log(key, "+", subkey, "=>", val);
        // res[subkey] = null;
        rv = this.buildSubTree(val, recursionDepth-1);
      }
      return rv;
    },

    buildSubTree(key, recursionDepth=-1) {
      if (typeof this.protoSubtrees[key] === "undefined" || this.protoSubtrees[key] === null) {
        if (this.loadProtoSubTypes(key) !== null) {
          let baseTypes = this.loadProtoSubTypes(key);
          let res = {};
          for (const subkey of Object.keys(baseTypes)) {
            res[subkey] = this.resolveType(baseTypes[subkey], recursionDepth)
          }
          this.protoSubtrees[key] = res;
        } else {
          this.protoSubtrees[key] = "Concrete Type:" + key;
        }
      } else {
        let baseTypes = this.loadProtoSubTypes(key);
        if (baseTypes !== null) {
          this.protoSubtrees[key] = {};
          for (const subkey of Object.keys(baseTypes)) {
            // console.log("...", baseTypes[subkey], this.protoSubtrees[key])
            if (typeof this.protoSubtrees[key][subkey] === "undefined") {
              this.protoSubtrees[key][subkey] = this.resolveType(baseTypes[subkey], recursionDepth)
            }
          }
        }
      }

      return this.protoSubtrees[key];

    },

    addListField(keySpec) {
      let baseFields = this.displayedFields;
      let data = this.queryData;
      for (const k of keySpec) {
        baseFields = baseFields[k];
        data = data[k];
      }

      //TODO: populate this subtree
      data.push({})
    },

    dropListField(keySpec) {
      let baseFields = this.displayedFields;
      let data = this.queryData;
      for (const k of keySpec) {
        baseFields = baseFields[k];
        data = data[k];
      }

      baseFields.pop()
    },

    isListKey(field) {
      return field.endsWith("List") || field.endsWith("Map");
    },

    _setupField(types, data, field) {
     const listField = this.isListKey(field);
     let subdata = {};
      if (listField) {
        data[field] = [subdata];
      } else {
        data[field] = subdata;
      }

      let testField = types[field];
      console.log(field, testField);
      for (const [key, value] of Object.entries(testField)) {
        if (typeof value == "object") {
          this._setupField(testField, subdata, key)
        }
      }
    },

    loadFieldDisplay(field) {
      this.displayedFields[field] = this.buildSubTree(this.protoTree["Reaction"][field], -1);
      this.displayedOptions[field] = this.displayedOptions[field] ? false:true;
      this._setupField(this.displayedFields, this.queryData, field)
    }
  },
  mounted() {
    this.displayedKeys = this.getKeys();
  }
}
</script>

<template lang="pug">
.search-options
  p() {{loadProtoSubTypes("Time")}}
  .search-segment(
    v-for='field in displayedKeys'
  )
    .options-title(
              @click='loadFieldDisplay(field)'
              :class='displayedOptions[field] ? "" : "closed"'
            ) {{field}}
    .options-container(
      v-if='displayedOptions[field]'
    )
      AdvancedSearchInput(
        :data='this.queryData'
        :field='field'
        :types='this.displayedFields'
        :labeled='false'
        :path='[field]'
      )
      
</template>

<style lang="sass" scoped>
@import '@/styles/vars'
@import '@/styles/transition'
@import '@/styles/tabs'
.search-options
  min-height: 90vh
  width: 100%
  min-width: 10 rem
  .search-segment
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
  #searchByReagent
    .reagent.options
      display: grid
      grid-template-columns: auto 1fr auto
      column-gap: 1rem
      row-gap: 0.5rem
      align-items: center
      .label
        font-size: 1.1rem
      #add-component, .copy
        grid-column: 1 / 3
      .field.long
        min-width: 250px
        input
          width: 95%
    .general.options
      display: grid
      grid-template-columns: auto 1fr
      column-gap: 1rem
      row-gap: 0.5rem
      input
        max-width: 15px
        text-align: center
      .slider-input
        display: flex
        column-gap: 0.5rem
        #similarity
          // width: 8rem
          max-width: 8rem
  #searchByReaction
    .slider-input
      display: grid
      grid-template-columns: 10rem 2.5rem 1fr
      column-gap: 0.5rem
      .value
        text-align: right
      &.multi
        grid-template-columns: 4rem 6rem 1fr
        align-items: center
  .suboptions-title
    font-size: 1.5rem
    font-weight: 700
    padding: 0.5rem 1rem
    border-top-left-radius: 0.25rem
    border-top-right-radius: 0.25rem
    margin-top: 1rem
    color: white
    background-color: $bg-primary
</style>