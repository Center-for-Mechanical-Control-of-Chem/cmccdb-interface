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
import EntityTable from '@/components/EntityTable'
import LoadingSpinner from '../../components/LoadingSpinner.vue'

export default {
  components: {
    EntityTable,
    LoadingSpinner,
  },
  methods: {
    getSearchParams() {
      const urlParams = new URLSearchParams(window.location.search)
      return urlParams
    },
    getDBQuery() {
      const searchParams = this.getSearchParams();
      const db = searchParams.get("database");
      const queryString=(db.length) ? `?database=${db}` : "";
      return queryString
    },
  },
  data() {
    return {
      loading: true,
      tableData: [],
      body: "No datasets found"
    }
  },
  mounted() {
    this.urlQuery =  window.location.search
    console.log("GET: ", `/api/fetch_datasets${this.urlQuery}`)
    fetch(`/api/fetch_datasets${this.urlQuery}`, {method: "GET"})
      .then(response => response.json())
      .then(
        data => {
          if ("traceback" in data) {
            alert(data["traceback"])
          } else if ("response" in data) {
            this.body = data["response"]
            this.loading = false
          } else {
            this.tableData = data
            this.loading = false
          }
      })
  }
}
</script>

<template lang="pug">
#browse-main 
  EntityTable(
    :tableData='tableData'
    title="",
    v-slot='{ entities }'
    v-if='tableData.length'
  ) 
    .table-container
      .column.label Dataset ID
      .column.label Name
      .column.label Description
      .column.label Size
      template(
        v-for='(row, idx) in entities'
      )
        .column 
          router-link(:to='{ name: "search", query: {dataset_ids: row["Dataset ID"], limit: 100, database:$route.query.database}}') {{row["Dataset ID"]}}
        .column {{row.Name}}
        .column {{row.Description?.length > 75 ? row.Description.substr(0,75)+"..." : row.Description}}
        .column {{row.Size}}
  .loading(
    :loading='loading',
    v-else-if='loading'
    )
    LoadingSpinner
  .container(
      :body='body',
      v-else
  ) 
    p(
      style="text-align: center"
    ) {{body}}
  
</template>

<style lang="sass" scoped>
@import '@/styles/table'
#browse-main
  padding: 1rem 0
  .table-container
    grid-template-columns: 1fr 1fr 1fr auto
  .loading
    margin-top: 30vh
</style>