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
      auxFiles: [],
      maxAuxFiles: 5,
      maxFileSize: 5 * 1024 * 1024,
      fileError: null,
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
    setFile(e) {
      this.fileError = null
      this.uploadFile.file = null
      this.uploadFile.name = null
      const files = e.target.files || e.dataTransfer?.files || []
      if (!files.length) return
      if (files[0].size > this.maxFileSize) {
        e.target.value = ''
        this.fileError = `"${files[0].name}" exceeds the 5 MB file size limit.`
        return
      }
      this.uploadFile.name = files[0].name
      this.uploadFile.file = files[0]
    },
    setAuxFiles(e) {
      this.fileError = null
      this.auxFiles = []
      const files = Array.from(e.target.files || e.dataTransfer?.files || [])
      if (files.length > this.maxAuxFiles) {
        this.fileError = `You may attach at most ${this.maxAuxFiles} auxiliary files.`
      } else if (files.some(file => file.size > this.maxFileSize)) {
        this.fileError = 'Each auxiliary file must be 5 MB or smaller.'
      } else if (new Set(files.map(file => file.name)).size !== files.length) {
        this.fileError = 'Auxiliary files must have distinct filenames.'
      } else {
        this.auxFiles = files
      }
      // Reset the picker so a removed or rejected file can be selected again.
      e.target.value = ''
    },
    removeAuxFile(index) {
      this.auxFiles.splice(index, 1)
    },
    fileSize(size) {
      return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`
    },
    submitUpload() {
      if (this.inUpload) return
      if (!this.user.ghAuthenticated) {
        return alert("Login with GitHub to upload.")
      }
      if (!this.user.cmccMember && this.getDB() != "staging") {
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
      this.auxFiles.forEach((file, index) => payload.append(`auxFile${index}`, file, file.name));
      xhr.onload = () => {
        this.inUpload = false;
        let response
        try {
          response = JSON.parse(xhr.response)
        } catch {
          this.traceback = `Upload failed (HTTP ${xhr.status}). Please try again.`
          return
        }
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
          accept='.pbtxt,.pb'
          :disabled='inUpload'
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
          :disabled='inUpload'
          v-on:change='(e) => setFile(e)'
        )
    .copy Choose a &nbsp;
                  code() .xlsx/.csv
                  | &nbsp; file following the CMCCDB template, examples are in the &nbsp;
                  a(href="https://github.com/Center-for-Mechanical-Control-of-Chem/cmccdb-data") cmccdb-data repository
  .auxiliary-upload
    .subtitle Optional auxiliary files
    p#aux-upload-help.copy Attach images, spectra or other supporting files referenced in your dataset. Use the original filenames from its links (in a spreadsheet, enter #[code url(filename)] in the appropriate data field).
    .file-picker
      .input
        label(for='aux-upload') Choose files:
        input#aux-upload(
          type='file'
          multiple
          :disabled='inUpload'
          aria-describedby='aux-upload-help aux-upload-limits'
          @change='setAuxFiles'
        )
    p#aux-upload-limits.file-limits Up to 5 auxiliary files, 5 MB per file. The dataset file also has a 5 MB limit. A new selection replaces the list below.
    ul.attachment-list(v-if='auxFiles.length')
      li(v-for='(file, index) in auxFiles' :key='file.name')
        .attachment-details
          span.attachment-name {{ file.name }}
          span.attachment-size {{ fileSize(file.size) }}
        button.remove-attachment(
          type='button'
          :disabled='inUpload'
          :aria-label='`Remove ${file.name}`'
          @click='removeAuxFile(index)'
        ) Remove
  p.file-error(v-if='fileError' role='alert') {{ fileError }}
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
      :disabled="inUpload"
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
  .auxiliary-upload
    max-width: 850px
    padding: 1.25rem
    margin-bottom: 1.5rem
    border: 1px solid $medgrey
    border-radius: 8px
    .file-picker
      padding: 0.5rem 0
  .file-limits
    font-size: 0.9rem
    color: $darkgrey
    margin: 0.5rem 0 0
  .file-error
    color: $text-accent
  .attachment-list
    list-style: none
    padding: 0
    margin: 1rem 0 0
    li
      display: flex
      align-items: center
      justify-content: space-between
      gap: 1rem
      padding: 0.6rem 0
      border-top: 1px solid $medgrey
  .attachment-details
    min-width: 0
    display: flex
    flex-direction: column
  .attachment-name
    overflow-wrap: anywhere
  .attachment-size
    color: $darkgrey
    font-size: 0.85rem
  .remove-attachment
    padding: 0.35rem 0.7rem
    font-size: 0.9rem
  .advanced-upload
  .basic-upload
  #upload-submit:disabled
    background-color: $lightgrey
    color: $darkgrey

</style>
