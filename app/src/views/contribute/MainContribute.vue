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
import Enumerate from "./EnumerateView"
import Upload from "./UploadView"
import Datasets from "./DatasetsView"

export default {
  components: {
    LoadingSpinner,
    Enumerate,
    Upload,
    Datasets
  },
  data() {
    return {
      loading: true,
      tabs: [
        "Introduction",
        "Upload",
      ],
      activeTab: "Upload",
    }
  },
  computed: {
  },
  methods: {
  },
  async mounted() {
    // if this is user's first time, default page is get started
    const notFirstTime = localStorage.getItem('notFirstTime')
    if (!notFirstTime) {
      localStorage.setItem("notFirstTime", "false")
      this.activeTab = "Introduction"
    }
    this.loading = false
  },
}
</script>

<template lang="pug">
.main-contribute
  transition(name="fade")
    .loading(v-if='loading')
      LoadingSpinner
  transition(name="fade")
    .contribute-menu(v-if='!loading')
      .title {{activeTab}}
      .contribute-container
        .tabs
          .tab(
            v-for='tab in tabs'
            @click='activeTab = tab'
            :class='activeTab == tab ? "selected" : ""'
          ) {{tab}}
        transition(name="fade")
          .get-started(v-if='activeTab == "Introduction"')
            .copy We have adapted the ORD submission template to support a single-file workflow.
                All submissions are driven by a single spreadsheet file which is compiled down to a &nbsp;
                code() .pbtxt
                | &nbsp; file with the &nbsp;
                code() construct_dataset.py
                | &nbsp; script in the main repository.
        transition(name="fade")
          Upload(v-if='activeTab == "Upload"')

</template>

<style lang="sass" scoped>
@import "@/styles/vars"
@import "@/styles/tabs"
@import '@/styles/transition.sass'
.main-contribute
  margin: 0 5%
  padding: 1rem
  .title
    font-size: 2rem
    font-weight: 700
    margin-bottom: 1rem
  .subtitle
    font-size: 1.5rem
  .contribute-container
    background-color: white
    border-radius: 0.25rem
    padding: 1rem
  .get-started
    .copy
      margin: 3rem 0 2rem
    .tutorial-videos
      display: flex
      flex-wrap: wrap
      column-gap: 1rem
      row-gap: 1rem
</style>