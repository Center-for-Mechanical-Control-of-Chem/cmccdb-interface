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
import FullSchemaSearch from './FullSchemaSearch'
import SearchResults from './SearchResults'
import LoadingSpinner from '@/components/LoadingSpinner'
import reaction_pb from "cmccdb-schema"
import hexToUint from "@/utils/hexToUint"

export default {
  components: {
    FullSchemaSearch,
    SearchResults,
    LoadingSpinner
  },
  watch: {
    '$route.query': {
      handler() {
        this.getSearchResults()
      },
      deep: true,
    }
  },
  data() {
    return {
      searchResults: [],
      queryParams: "",
      searchParams: {},
      loading: true,
      urlQuery: "",
      showOptions: false,
    }
  },
  methods: {
    async getSearchResults() {
      this.loading = true 
      // get raw url query string
      this.urlQuery =  window.location.search 
      console.log("GET: ", `/api/advanced-query${this.urlQuery}`)
      try {
        const res = await fetch(`/api/advanced-query${this.urlQuery}`, {method: "GET"})
        this.searchResults = await res.json()
        // unpack protobuff for each reaction in results
        this.searchResults.forEach((reaction) => {
          const bytes = hexToUint(reaction.proto)
          reaction.data = reaction_pb.Reaction.deserializeBinary(bytes).toObject();
        })
        this.loading = false
      } catch (e) {
        console.log(e)
        this.searchResults = []
        this.loading = false
      }
    },
    createSearch(options) {
      // reagent options
    },
    updateSearchOptions() {
      
    }
  },
  mounted() {
    // fetch initial query
    this.getSearchResults()
  },
}
</script>

<template lang="pug">
#search-main
  .search-options-container(:class='showOptions ? "slide-out" : "hidden"')
    .title Filters & Options
    .options-holder
      FullSchemaSearch(
        @searchOptions='updateSearchOptions'
      )
    .slide-out-tab(@click='showOptions=!showOptions')
      .line
      .line
      .line
  .search-results
    SearchResults(
      :searchResults='searchResults'
      v-if='!loading && searchResults?.length'
    )
    .no-results(v-else-if='!loading && !searchResults?.length')
      .title No results. Adjust the filters and options and search again.
    .loading(v-else)
      LoadingSpinner

</template>

<style lang="sass" scoped>
@import '@/styles/vars.sass'
#search-main
  width: 95%
  margin: 1rem 2.5%
  column-gap: 1rem
  min-width: 800px
  .search-options-container
    .title
      font-size: 2rem
      font-weight: 700
      margin-bottom: 0.85rem
    .options-holder
      position: -webkit-sticky
      position: sticky
      top: 1rem
      background-color: white
      padding: 1rem
      box-sizing: border-box
      border-radius: 0.25rem
      overflow-y: auto
  .no-results
    margin-top: 1rem
    text-align: center
  @media (max-width: 1000px)
    .title
      display: none
    .search-options-container
      position: fixed
      height: 100vh
      width: 90%
      transition: 0.5s
      top: 0
      &.hidden
        left: -81%
      &.slide-out
        left: 0
      .options-holder
        width: 90%
        height: 100%
        overflow-y: auto
        box-shadow: 0 0 5px $darkgrey
      .slide-out-tab
        background-color: white
        position: absolute
        left: 89.5%
        width: 7.5%
        top: 4rem
        box-shadow: 6px 3px 5px #ccc
        padding: 0.5rem 0
        border-bottom-right-radius: 0.25rem
        .line
          background-color: black
          height: 2px
          width: 60%
          margin: 0.5rem auto

</style>