
import reaction_pb from "cmccdb-schema"

export default {
    pbType(path) {
        let baseType = reaction_pb['reaction_json'];
        for (const k of path) {
            baseType = baseType[k]
        }
        if (typeof baseType["allowedFields"] !== "undefined") {
            baseType = baseType["allowedFields"]
        }
        return baseType;
    },


  enumType(enumName, value) {
    const controlTypes = enumName;
    return Object.keys(controlTypes)
        .find(key => controlTypes[key] == value)
  }
    
}