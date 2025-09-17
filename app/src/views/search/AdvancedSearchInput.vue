

<script>
export default {
    props:{
        fieldKey: String,
        fieldData: Object
    }
}
</script>


<template lang="pug">

.suboptions-title(v-if='typeof vals !== "string"') {{subfield}}
.p(v-else) {{subfield}}:
input(
    v-if='vals === "string" || vals === "Concrete Type:number"'
    v-model='queryData[field][subfield]'
)
input(
    v-else-if='vals === "Concrete Type:boolean"'
    type='checkbox'
    v-model='queryData[field][subfield]'
)
.div(
    v-else-if='typeof vals === "string"'
) {{vals}}
.subsection(
    v-else
    v-for='(subsubvals, subsubfield) in vals'
) {{subsubfield}}:

</template>