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
      }
    }
  },
  methods: {
    async setFile(e) {
      // converts uploaded file into useable array buffer
      const files = e.target.files || e.dataTransfer.files
      if (!files.length) return console.error('No file')
      this.uploadFile.loading = true
      this.uploadFile.name = files[0].name
      this.uploadFile.file = files[0]
      this.uploadFile.loading = false
      // const fileReader = new FileReader()
      // fileReader.onload = readerEvent => {
      //   this.uploadFile.value = readerEvent.target.result
      //   this.uploadFile.loading = false
      // }
      // fileReader.readAsArrayBuffer(files[0])
    },
    submitUpload() {
      if (this.uploadFile.loading)
        return alert("Files are still processing. Please try again in a moment.")
      else if (!this.uploadFile.file)
        return alert("You must upload a file for the dataset before submitting.")
      // send dataset file to api for upload
      this.urlQuery =  window.location.search
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/upload${this.urlQuery}`);
      console.log("POST:", this.uploadFile.name, `/api/upload${this.urlQuery}`)
      let payload = new FormData();
      payload.append('uploadFile', this.uploadFile.file);
      xhr.onload = () => {
        let response = JSON.parse(xhr.response);
        if (xhr.status === 200) {
          location.reload();
        } else {
          alert(response["traceback"])
        }
      }
      // Attempt to catch timeouts.
      xhr.onerror = () => {
        alert('Error: request failed (possibly due to timeout)');
      }
      xhr.send(payload);
    }
  },
}
</script>

<template lang="pug">
.upload
  .subtitle Upload dataset file:
  .file-picker
    .input
      label(for='upload') Dataset filename:
      input#template(
        type='file'
        accept='.pbtxt,.pb,.xlsx,.csv'
        v-on:change='(e) => setFile(e)'
      )
  .submit
    button#upload-submit(@click='submitUpload') Submit Upload
  .copy Choose a &nbsp;
                code() .pbtxt/.xlsx/.csv
                | &nbsp; file compiled with the &nbsp;
                code() construct_dataset.py
                | &nbsp; script in the &nbsp;
                a(href="https://github.com/Center-for-Mechanical-Control-of-Chem/cmccdb-schema") cmccdb-schema repository
</template>

<style lang="sass" scoped>
.subtitle
  font-size: 1.5rem
.upload
  padding-top: 1rem
  .file-picker
    padding: 1rem 0
    display: flex
    flex-wrap: wrap
    row-gap: 1rem
    .input
      label
        margin-right: 0.5rem
  .submit
    margin-bottom: 2rem
  .copy
    margin-top: 1rem
</style>