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

  },
  methods: {
    reconfigureDatabase() {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/reconfigure`);
      xhr.onload = () => {
        if (xhr.status === 200) {
          location.reload();
        } else {
          alert('Error: ' + xhr.response);
        }
      }
      // Attempt to catch timeouts.
      xhr.onerror = () => {
        alert('Error: request failed (possibly due to timeout)');
      }
    }
  },
}
</script>

<template lang="pug">
.upload
  .subtitle
   .copy WARNING: RECONFIGURING THE DATABASE DELETES ALL EXISTING DATA
  .submit
    button#upload-submit(@click='reconfigureDatabase') RECONFIGURE
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