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

<template lang="pug">
div Loading the structure editor…
</template>

<script>

export default {
  mounted() {
    // Ketcher already ships a built application. Serve its files unchanged.
    // The modal keeps the same iframe WindowProxy and can still access ketcher.
    window.location.replace(`${process.env.BASE_URL}ketcher/index.html`)
  }
}
</script>
