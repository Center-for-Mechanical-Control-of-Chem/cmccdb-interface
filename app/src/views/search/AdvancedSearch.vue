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
import { reactionIdentifier } from "@/utils/reactionSummary"
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
  data() {
    return {
      searchResults: [],
      queryParams: "",
      searchParams: {},
      loading: false,
      urlQuery: "",
      showOptions: false,
      saveSearch: false,
      queryDisplay: "",
      traceback: "",
      requestId: 0,
      hasSearched: false
    }
  },
  methods: {
    async getSearchResults() {
      const requestId = ++this.requestId;
      this.traceback = "";
      this.searchResults = [];
      this.hasSearched = true;
      this.loading = true;
      this.urlQuery = window.location.search;
      try {
        const response = await fetch(`/api/advanced-query${this.urlQuery}`, {
          method: "POST",
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(this.searchParams)
        });
        let results;
        try {
          results = await response.json();
        } catch (_) {
          throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`);
        }
        if (!response.ok || !Array.isArray(results)) {
          throw new Error(results?.message || `Search failed (HTTP ${response.status}).`);
        }
        const decoded = results.map((reaction) => {
          if (!reaction || typeof reaction.proto !== "string" || !/^(?:[0-9a-f]{2})*$/i.test(reaction.proto)) {
            throw new Error("The server returned an invalid reaction record.");
          }
          const data = reaction_pb.Reaction.deserializeBinary(hexToUint(reaction.proto)).toObject();
          const result = {...reaction, data};
          result.reaction_id = reactionIdentifier(result);
          return result;
        });
        if (requestId === this.requestId) this.searchResults = decoded;
      } catch (error) {
        if (requestId === this.requestId) {
          this.traceback = error.message || String(error);
          this.searchResults = [];
        }
      } finally {
        if (requestId === this.requestId) this.loading = false;
      }
    },
    updateSearchOptions(searchResults) {
      this.searchParams = searchResults;
      if (this.saveSearch) {
        this.requestId++;
        this.loading = false;
        this.traceback = "";
        this.queryDisplay = JSON.stringify(this.searchParams, null, 2)
      } else {
        this.queryDisplay = "";
        this.getSearchResults();
      }

      
    }
  },
  mounted() {
    // fetch initial query
    // this.getSearchResults()
  },
}
</script>

<template lang="pug">
#search-main
  .search-options-container(:class='showOptions ? "slide-out" : "hidden"')
    .title Filters & Options
    .options-holder
      FullSchemaSearch(
        @updateSearch='updateSearchOptions'
      )
      label.query-preview
        input.boolean-value(type='checkbox' v-model='saveSearch')
        | Show search JSON without running
      p.search-help Text supports contains and does not contain. Numbers support >=, <=, in range [10, 20], and not in range [10, 20]. Lists use any of [a, b] or none of [a, b]. Up to 1,000 results are returned.
    .slide-out-tab(@click='showOptions=!showOptions')
      .line
      .line
      .line
  .search-results
    pre(v-if='queryDisplay.length') {{queryDisplay}}
    SearchResults(
      :searchResults='searchResults'
      :shareable='false'
      v-else-if='!loading && searchResults?.length'
    )
    .error-message(v-else-if='!loading && traceback.length' role='alert') {{traceback}}
    .no-results(v-else-if='!loading && !hasSearched') Choose filters and click Search.
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
  display: grid
  grid-template-columns: minmax(18rem, 30rem) minmax(0, 1fr)
  min-width: 0
  .search-results
    min-width: 0
    pre
      white-space: pre-wrap
      overflow-wrap: anywhere
  .query-preview
    display: flex
    gap: 0.5rem
    align-items: center
    margin-top: 1rem
  .search-help
    font-size: 0.9rem
  .error-message
    white-space: pre-wrap
    overflow-wrap: anywhere
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
    grid-template-columns: minmax(0, 1fr)
    .search-options-container
      z-index: 20
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
