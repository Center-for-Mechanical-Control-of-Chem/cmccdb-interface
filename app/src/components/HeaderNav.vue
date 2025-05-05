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

export default {
  data: () => ({ database: "cmcc" }),
  created() {
    const urlParams = this.getSearchParams()
    const db = urlParams.get("database")
    if (db) { this.database = db }
  },
  methods: {
    getSearchParams() {
      const urlParams = new URLSearchParams(window.location.search)
      return urlParams
    },
    reroute(event) {
      const urlParams = this.getSearchParams()
      if (this.database.length) {
        urlParams.set("database", this.database)
      } else {
        urlParams.delete("database")
      }
      window.location.search = urlParams.toString()
    }
  }
}
</script>

<template lang="pug">
nav.navbar.navbar-expand-lg.bg-light
  .container
    a.navbar-brand(href="/")
      img(
        src="/img/header_logo.png"
        alt="CMCC Logo"
        height="30"
      )
    #navbarNav.collapse.navbar-collapse
      .navbar-nav
        .nav-item
          router-link.nav-link(:to='{name: "browse", query:{"database":$route.query.database}}') Browse
          router-link.nav-link(:to='{name: "search", query:{"database":$route.query.database}}') Search
          router-link.nav-link(:to='{name: "contribute", query:{"database":$route.query.database}}') Contribute
        .nav-item
          a.nav-link(href="https://github.com/Center-for-Mechanical-Control-of-Chem") GitHub
        .nav-item
          router-link.nav-link(:to='{name: "about"}') About
    input(
      type="text"
      class="float-right"
      v-model="database"
      @change="$event => (this.reroute(event))"
      )
div.alt-dataset(:class="{ 'alt-visible' : ($route.query.database) && ($route.query.database !== 'cmcc') }") Viewing a Secondary Database
</template>

<style lang="sass" scoped>
@import @/styles/vars

nav
  background-color: white !important
  .container
    display: flex
    flex-wrap: inherit
    align-items: center
    width: 90%
    margin: auto
    padding: 0.5rem 0
    .navbar-brand
      padding: 0.5rem 0
    #navbarNav
      flex-direction: row
      .navbar-nav
        margin-left: 1rem
        .nav-item
          display: flex
          .nav-link
            padding: 0.5rem
            text-decoration: none
            transition: .15s
            color: $bg-primary
            &:hover
              color: $bg-secondary
.alt-dataset
  text-align: center
  font-size: 1.5rem
  font-variant: bold
  background: $bg-primary
  color: $text-primary
  display: none
  width: 100%
  padding: 2rem
  height: 6rem
.alt-visible
  display: block
</style>
