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
  methods: {
    getSearchParams() {
      const urlParams = new URLSearchParams(window.location.search)
      return urlParams
    },
    getUserCode() {
      const searchParams = this.getSearchParams();
      return searchParams.get("user_code");
    },
    getVerificationURI() {
      const searchParams = this.getSearchParams();
      return searchParams.get("verification_uri");
    },
    getLoopbackURI() {
      return "/api/dev/auth/gh_device_complete_auth" + window.location.search;
    },
  },
  data() {
    return {
      userCode: "",
      verificationURI: "",
      loopbackURI: ""
    }
  },
  mounted() {
    this.userCode = this.getUserCode();
    this.verificationURI = this.getVerificationURI();
    this.loopbackURI = this.getLoopbackURI();
  }
}
</script>

<template lang="pug">
.main-auth
  .auth-container
    h1(class="title") GitHub Authentication
    p In a new tab, open 
      a(
        target="_blank" 
        rel="noopener noreferrer"
        :href="verificationURI"
        ) {{verificationURI}}
      | &nbsp; and supply the following user code
    p(
      class="user-code"
    )
      code {{userCode}}
    p When done, click below
    a(
        :href="loopbackURI"
        class="login-button"
        ) 
        button Complete Log In
    
  
</template>

<style lang="sass" scoped>
@import "@/styles/vars"
@import "@/styles/tabs"
@import '@/styles/transition.sass'
.main-auth
  margin-top: 2rem
  background-color: white
  padding: 0 2rem
  border-radius: 0.5rem
  .title
    font-size: 2rem
    font-weight: 700
    margin-bottom: 1rem
  .user-code
    text-align: center
    font-size: 1.5rem
  .login-button
      text-align: center
      font-size: 1.5rem
  .auth-container
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