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
  data: () => ({
    database: "cmcc", 
    user: {
        name: null,
        email: null,
        username: null,
        cmccMember: null,
        ghAuthenticated: false
      }
    }),
  created() {
    const urlParams = this.getSearchParams()
    const db = urlParams.get("database")
    if (db) { this.database = db }
    this.getUserData()
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
    },
    ghAuthenticate() {
      const searchParams = new URLSearchParams("")
      searchParams.set("origin_url", window.location)
      window.location.href = "/api/authenticate?" + searchParams.toString()
    },
    async getUserData() {
      if (!this.user.ghAuthenticated) {
        fetch("/api/user-info").then(
          (response) => response.json().then(
            (authData) => {
              if (authData !== null) {
                this.user.ghAuthenticated = true
                this.user.name = authData.name
                this.user.email = authData.email
                this.user.cmccMember = authData.member
                this.user.username = authData.username
              }
            }
          )
        )
      }
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
    .navbar-nav.pe-3
      .nav-item
        .input-group
          .db-label.input-group-text(
            for="db-selector"
          ) database
          input.form-control(
            id="db-selector"
            type="text"
            v-model="database"
            @change="$event => (this.reroute(event))"
          )
    .navbar-nav
      .nav-item
        .gh-user-info(
          v-if="user.ghAuthenticated"
        ) {{ user.username }}
        .gh-login(
          v-else
        )  
          a(
            href="#"
            @click="ghAuthenticate"
            ) Login
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
.db-label
  color:$text-accent
.gh-user-info
  color:$text-accent
.gh-login a
  color:$text-accent
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
