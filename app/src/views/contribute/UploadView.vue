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
  data() {
    return {
      uploadFile: {
        name: null,
        loading: false,
        value: null,
        file: null
      },
      auxFiles: [],          // up to 5 optional auxiliary files
      maxAuxFiles: 5,
      maxFileSize: 5 * 1024 * 1024,  // 5 MB
      user: {
        name: null,
        email: null,
        username: null,
        cmccMember: null,
        ghAuthenticated: false
      },
      traceback: null,
      advancedUpload: false,
      inUpload: false
    }
  },
  mounted() {
    this.getUserData()
  },
  methods: {
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
              const searchParams = this.getSearchParams()
              if (searchParams.get("name") !== null && searchParams.get("name").length) {
                this.user.name = searchParams.get("name")
              }
              if (searchParams.get("email") !== null && searchParams.get("email").length) {
                this.user.email = searchParams.get("email")
              }
            }
          )
        )
      }
    },
    getSearchParams() {
      const urlParams = new URLSearchParams(window.location.search)
      return urlParams
    },
    getDB() {
      const searchParams = this.getSearchParams()
      const db = searchParams.get("database")
      const queryString=(typeof db === "string" && db.length) ? db : "cmcc"
      return queryString
    },
    getQueryString() {
      const urlParams = this.getSearchParams()
      if (this.user.name !== null) {
        urlParams.set("name", this.user.name)
      }
      if (this.user.username !== null) {
        urlParams.set("username", this.user.username)
      }
      if (this.user.email !== null) {
        urlParams.set("email", this.user.email)
      }
      return urlParams.toString()
    },
    getUploadEndpoint() {
      const searchParams = new URLSearchParams(this.getQueryString())
      searchParams.set("origin_url", window.location)
      return "/api/upload?" + searchParams.toString()
    },
    async setFile(e) {
      // converts uploaded file into useable array buffer
      const files = e.target.files || e.dataTransfer.files
      if (!files.length) return console.error('No file')
      if (files[0].size > this.maxFileSize) {
        e.target.value = ''
        return alert(`"${files[0].name}" exceeds the 5MB size limit.`)
      }
      this.uploadFile.loading = true
      this.uploadFile.name = files[0].name
      this.uploadFile.file = files[0]
      this.uploadFile.loading = false
    },
    setAuxFiles(e) {
      const files = e.target.files || e.dataTransfer.files
      if (!files.length) return console.error('No file')
      const selected = Array.from(files)
      if (selected.length > this.maxAuxFiles) {
        e.target.value = ''
        return alert(`You may attach at most ${this.maxAuxFiles} auxiliary files.`)
      }
      const tooLarge = selected.filter((f) => f.size > this.maxFileSize)
      if (tooLarge.length) {
        e.target.value = ''
        return alert(
          `The following auxiliary files exceed the 5MB limit: ${tooLarge
            .map((f) => f.name)
            .join(", ")}`
        )
      }
      this.auxFiles = selected
    },
    submitUpload() {
      if (!this.user.ghAuthenticated) {
        return alert("Login with GitHub to upload.")
      }
      if (!this.user.cmccMember && this.getDB() != "staging") {
        //TODO: add server side authentication
        return alert("Upload to primary database only supported for CMCC members.")
      }
      if (this.uploadFile.loading)
        return alert("Files are still processing. Please try again in a moment.")
      else if (!this.uploadFile.file)
        return alert("You must upload a file for the dataset before submitting.")
      // send dataset file to api for upload

      this.inUpload = true
      
      const xhr = new XMLHttpRequest();
      const endpoint = this.getUploadEndpoint()
      xhr.open('POST', endpoint);
      console.log("POST:", this.uploadFile.name, endpoint)
      let payload = new FormData();
      payload.append('uploadFile', this.uploadFile.file);
      this.auxFiles.forEach((f, i) => {
        payload.append(`auxFile${i}`, f, f.name);
      });
      xhr.onload = () => {
        this.inUpload = false;
        let response = JSON.parse(xhr.response);
        if (xhr.status === 200) {
          const searchParams = this.getSearchParams()
          searchParams.set("limit", "100")
          searchParams.set("dataset_ids", response["dataset_id"])
          window.location.href = '/search?' + searchParams.toString();
        } else {
          this.traceback = "ERROR: \n" + response["traceback"]
          alert("An error occured: see the traceback below")
        }
      }
      // Attempt to catch timeouts.
      xhr.onerror = () => {
        this.inUpload = false;
        alert('Error: request failed (possibly due to timeout)');
      }
      xhr.send(payload);
    }
  },
}
</script>

<template lang="pug">
.upload
  .subtitle Contributor Information:
  .submit
    .info-panel(
      v-if="user.ghAuthenticated"
      ) 
        .info-element
          label(
            for="user-info-username"
          ) GitHub ID:
          code(
            id="user-info-username"
            ) {{user.username}}
        .info-element
          label(
            for="user-info-name"
          ) Name:
          input(
            id="user-info-name"
            type="text"
            v-model="user.name"
            )
        .info-element
          label(
            for="user-info-email"
          ) Email:
          input(
            id="user-info-email"
            type="text"
            v-model="user.email"
            )
    button(
      @click='ghAuthenticate'
      v-else
      ) Login with GitHub
    

  .subtitle Upload dataset file:
  .advanced-upload(
    v-if="advancedUpload"
  )
    .file-picker
      .input
        label(for='upload') Dataset:
        input#upload(
          type='file'
          accept='.pbtxt,.pb,.json,.pb.gz,.pbtxt.gz,.json.gz'
          v-on:change='(e) => setFile(e)'
        )
    .copy Choose a &nbsp;
                  code() .pbtxt
                  | &nbsp; file compiled with the &nbsp;
                  code() construct_dataset.py
                  | &nbsp; script in the &nbsp;
                  a(href="https://github.com/Center-for-Mechanical-Control-of-Chem/cmccdb-schema") cmccdb-schema repository
  .basic-upload(
    v-else
  )
    .file-picker
      .input
        label(for='upload') Dataset:
        input#upload(
          type='file'
          accept='.xlsx,.csv'
          v-on:change='(e) => setFile(e)'
        )
    .copy Choose a &nbsp;
                  code() .xlsx/.csv
                  | &nbsp; file following the CMCCDB template, examples are in the &nbsp;
                  a(href="https://github.com/Center-for-Mechanical-Control-of-Chem/cmccdb-data") cmccdb-data repository
  .subtitle Optional auxiliary files:
    .file-picker
      .input
        label(for='aux-upload') Auxiliary files (up to 5, max 5MB each):
        input#aux-upload(
          type='file'
          accept='.xlsx,.csv,.png,.jpg,.jpeg,.pdf,.txt,.sdf,.mol,.xyz,.cif'
          multiple
          v-on:change='(e) => setAuxFiles(e)'
        )
      .copy(v-if='auxFiles.length') Attached: {{ auxFiles.map(f => f.name).join(", ") }}
  .submit
    button#upload-submit(
      @click='submitUpload'
      :disabled="inUpload"
      ) Submit Upload
    input(
      id="advanced-toggle"
      type="checkbox"
      class="advanced-toggle"
      v-model="advancedUpload"
    )
    label(for="advanced-toggle") Use precompiled dataset
  .error-message
    code 
      pre {{ traceback }}
   
</template>

<style lang="sass" scoped>
@import @/styles/vars

.subtitle
  font-size: 1.5rem
.info-panel
  display: block
  .info-element
    color: $text-accent
    label
      margin-right: 0.5rem
      min-width: 100px
.upload
  padding-top: 1rem
  .file-picker
    padding: 1rem 0
    display: flex
    flex-wrap: wrap
    row-gap: 1rem
    .input
      color: $text-accent
      label
        margin-right: 0.5rem
  .submit
    margin-bottom: 2rem
    #advanced-toggle
      margin-left: 1rem
    label
      color: $text-accent
      margin-left: 0.2rem
  .copy
    margin-bottom: 1rem
  .error-message
    max-width: 850px
  .advanced-upload
  .basic-upload
  #upload-submit:disabled
    background-color: $lightgrey,
    color: $darkgrey

</style>