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
import FloatingModal from "@/components/FloatingModal"

export default {
  name: 'DownloadResults',
  props: {
    reactionIds: Array,
    showDownloadResults: Boolean,
  },
  components: {
    "floating-modal": FloatingModal
  },
  watch: {
    fileType(val) {
      // store selected file type in vue session
      this.$store.commit('setDownloadFileType', val)
    }
  },
  data () {
    return {
      fileType: "pb.gz",
      downloading: false,
      downloadError: "",
    }
  },
  methods: {
    downloadResults () {
      if (this.downloading) return;
      this.downloadError = "";
      const fileType = this.fileType;
      if (!["pb.gz", "pbtxt", "csv"].includes(fileType)) {
        this.downloadError = "Choose a supported download format.";
        return;
      }
      this.downloading = true;
      const params = new URLSearchParams({
        format: fileType,
        database: this.$route.query.database || "cmcc",
      });
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/download_results?' + params.toString());
      xhr.responseType = "blob";
      xhr.onload = async () => {
        if (xhr.status === 200) {
          const url = URL.createObjectURL(xhr.response);
          const link = document.createElement('a');
          link.href = url;
          link.download = "cmccdb_search_results." + (fileType === "csv" ? "zip" : fileType);
          link.click();
          // https://stackoverflow.com/a/56547307.
          setTimeout(() => {
            URL.revokeObjectURL(url);
            link.remove();
          }, 100);
        } else {
          const status = "HTTP " + xhr.status + (xhr.statusText ? " " + xhr.statusText : "");
          let reference = xhr.getResponseHeader("X-Request-ID") || "";
          let detail = "The server returned an empty error response. Check the server log.";
          try {
            const text = await xhr.response.text();
            if (text.trim()) {
              try {
                const error = JSON.parse(text);
                detail = typeof error.message === "string" ? error.message :
                  "The server returned an error without an explanation. Check the server log.";
                reference = error.request_id || reference;
              } catch (_) {
                // Explain HTML proxy/server errors without rendering their markup.
                detail = /^\s*</.test(text)
                  ? "The server returned an HTML error page. Check the server log."
                  : text.trim().slice(0, 500);
              }
            }
          } catch (_) {
            detail = "The server's error response could not be read. Check the server log.";
          }
          this.downloadError = fileType.toUpperCase() + " download failed (" + status + "). " +
            detail.slice(0, 1000) + (reference ? " Reference: " + reference : "");
        }
      };
      xhr.onerror = () => {
        this.downloadError = fileType.toUpperCase() +
          " download failed: could not connect to the server. Check that Preview is running and its tunnel is connected.";
      };
      xhr.onloadend = () => { this.downloading = false; };
      xhr.setRequestHeader('Content-Type', 'application/json');

      // format request json to expected key/value in api
      const requestJson = this.reactionIds.map(reactionId => {return {"Reaction ID": reactionId}})
      xhr.send(JSON.stringify(requestJson));
    }
  },
  mounted() {
    const saved = this.$store.state.downloadFileType;
    this.fileType = ["pb.gz", "pbtxt", "csv"].includes(saved) ? saved : "pb.gz";
  }
}
</script>

<template lang="pug">
.download-results-main
  floating-modal(
      v-if='showDownloadResults'
      title="DownloadResults"
      @closeModal='$emit("hideDownloadResults")'
    )
      .download-body
        .title Select your desired file type and then click download.
        .options 
          label(for='file-type-select') File type:
          select#file-type-select(v-model='fileType')
            option(value="pb.gz") pb.gz
            option(value="csv") CSV + attachments (.zip)
            option(value="pbtxt") pbtxt
        .download
          button(@click='downloadResults' :disabled='downloading') {{downloading ? 'Preparing download…' : fileType === 'csv' ? 'Download CSV bundle (.zip)' : 'Download ' + fileType + ' file'}}
        .download-error(v-if='downloadError' role='alert') {{downloadError}}
</template>

<style lang="sass" scoped>
@import '@/styles/vars.sass'
@import '@/styles/transition.sass'
.download-body
  height: 100%
  display: grid
  grid-template-rows: 50% auto 1fr
  *
    margin: auto
    width: fit-content
  .title
    font-size: 1.5rem
  .options
    label
      margin-right: 0.5rem
    select
      min-width: 7rem
  .download
    margin-top: 2rem
  .download-error
    max-width: 44rem
    padding: 0.5rem
    overflow-wrap: anywhere
</style>
