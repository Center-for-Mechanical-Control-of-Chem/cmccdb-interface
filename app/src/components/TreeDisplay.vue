

<script>
export default {
    props:{
        value: [Object, String, Number, Boolean],
        type: String,
        types: Object
    },
    data() {
        const treeType = this.type ? this.type: typeof this.value;
        let isList = false;
        let isAtomic = false;
        let isObj = false;
        if (treeType !== "undefined" && this.value !== null) {
            if (treeType === "object") {
                if (Array.isArray(this.value)) {
                    isList = true;
                } else {
                    isObj = true;
                }
            } else {
                isAtomic = true
            }
        }
        return {
            "isObj": isObj,
            "isList": isList,
            "isAtomic": isAtomic,
            displayBody: true,
            labeled: true
        }
    },
    methods: {
        // toggleDisplay() { 
        //   this.displayBody = !this.displayBody
        // }

        prepFieldName(field) {
          if (field.endsWith("List")) {
            return field.slice(0, -4)
          } else if (field.endsWith("Map")) {
            return field.slice(0, -3)
          } else if (field.endsWith("Id")) {
            return field.slice(0, -2) + "ID"
          } else if (field.endsWith("Url")) {
            return field.slice(0, -3) + "URL"
          } else {
            return field
          }
        },

        resolveType(types, fieldName) {
            const capsName = fieldName.slice(0, 1).toUpperCase() + fieldName.slice(1, fieldName.length);
            return types[capsName]
        },
        
        enumType(enumName, value) {
            const controlTypes = enumName;
            return Object.keys(controlTypes)
                .find(key => controlTypes[key] == value)
        },

        resolveUnit(unit, allowedValues) {
            return this.enumType(allowedValues["allowedValues"], unit);
        },
        
        nonEmpty(subval) {
            if (Array.isArray(subval)) {
                return subval.length > 0
            } else {
                return subval
            }
        }
    }
}

</script>

<template lang="pug">
.tree-item(v-if='isAtomic')
    template(
        v-if='(typeof types["allowedValues"] !== "undefined")'
        )
        .tree-value() {{resolveUnit(value, types)}}
    template(v-else)
        .tee-value {{value}}
.tree-list(v-else-if='isList')
    .tree-list-item(v-for='subval of value')
        TreeDisplay(
            :value='subval'
            :types='types'
            )
.tree-list(v-else-if='isObj')
    template(
        v-if='(typeof value["value"] !== "undefined") && (typeof value["units"] !== "undefined")'
        )
        .tree-value() {{value["value"]}} {{resolveUnit(value["units"], types["Units"])}}
    template(v-else)
        .tree-list-item(v-for='[subfield, subval] of Object.entries(value)')
            template(v-if='nonEmpty(subval)')
                .tree-label {{prepFieldName(subfield)}}
                TreeDisplay(
                    :value='subval'
                    :types='resolveType(types, subfield)'
                    )


</template>

<style lang="sass" scoped>
@import '@/styles/vars'
@import '@/styles/transition'
@import '@/styles/tabs'

.tree-label
    padding: 0.2rem
    border-radius: 0.25rem
    margin-top: 1rem
    color: white
    background-color: $bg-primary
    display: flex
    align-content: center
    justify-content: space-between
    width: 100%
    box-sizing: border-box
    transition: 0.25s
    i
        font-size: 1rem
        transition: 0.25s
    i
        transform: rotate(180deg)
    &:first-child
        margin-top: 0
</style>