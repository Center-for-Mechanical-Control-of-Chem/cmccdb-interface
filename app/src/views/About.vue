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
  name: 'AboutView',
  components: {
  }
}
</script>

<template>
  <div id="about" class="container">
    <div class="row mt-5">
        <div class="col-3 border-top pt-3">
            <h3>About</h3>
        </div>
        <div class="col-9 p-3">
            The Center for the Mechanical Control of Chemistry Reactions Database is a prototyping fork of the 
            <a href="https://open-reaction-database.org/">Open Reaction Database</a>
            project with a focus on the addition of mechanochemical information.
            As part of the work of the CMCC, the Database is maintained by the 
            <a href="https://dtaborgroup.com">Tabor Group</a>

            Learn more about the work of the Center <a href="https://www.chem.tamu.edu/cmcc/">here</a>
        </div>
    </div>
    <div class="row mt-5">
        <div class="col-3 border-top pt-3">
            <h3>Publications and Media</h3>
        </div>
        <div class="col-9 p-3">
            <h5>Journal Articles</h5>
            <ul>
                <li>
                    To be updated
                </li>
            </ul>
            <h5>News</h5>
            <ul>
                <li>
                    To be updated
                </li>
            </ul>
        </div>
    </div>
    <div class="row mt-5">
        <div class="col-3 border-top pt-3">
            <h3>Support</h3>
        </div>
        <div class="col-9 p-3">
            <p>We gratefully acknowledge support from the NSF</p>
        </div>
    </div>
  </div>
</template>

<style lang="sass" scoped>
#about
  margin-top: 2rem
  background-color: white
  padding: 0 2rem
  border-radius: 0.5rem
</style>
