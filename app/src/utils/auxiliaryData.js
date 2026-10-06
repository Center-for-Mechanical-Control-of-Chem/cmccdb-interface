import { fieldLabel } from "./conditionDisplay"

const dataFields = ["floatValue", "integerValue", "bytesValue", "stringValue", "url", "description", "format"]
const mimeTypes = {
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif",
  webp: "image/webp", svg: "image/svg+xml", avif: "image/avif", bmp: "image/bmp",
  ico: "image/x-icon", tif: "image/tiff", tiff: "image/tiff",
}

function isData(value) {
  return value && !Array.isArray(value) && typeof value === "object" &&
    Object.keys(value).some(key => dataFields.includes(key) && key !== "description" && key !== "format") &&
    Object.keys(value).every(key => dataFields.includes(key))
}

// Data messages can occur in analyses, features, metadata, automation and observations.
export function collectAuxiliaryData(reaction) {
  const entries = []
  function visit(value, path) {
    if (!value || typeof value !== "object") return
    if (isData(value)) {
      if (value.url || value.bytesValue || value.stringValue !== undefined ||
          value.floatValue !== undefined || value.integerValue !== undefined || value.description) {
        entries.push({ id: JSON.stringify(path), label: path[path.length - 1] || "Data", context: path.slice(0, -1).join(" / "), data: value })
      }
    } else if (Array.isArray(value)) {
      value.forEach((item, index) => {
        if (Array.isArray(item) && item.length === 2 && typeof item[0] === "string") {
          visit(item[1], [...path, item[0]])
        } else {
          visit(item, [...path.slice(0, -1), `${path[path.length - 1]} ${index + 1}`])
        }
      })
    } else {
      Object.entries(value).forEach(([key, item]) => visit(item, [...path, fieldLabel(key)]))
    }
  }
  visit(reaction, [])
  return entries
}

export function dataMimeType(data) {
  const format = (data.format || "").trim().toLowerCase().replace(/^\./, "")
  if (mimeTypes[format]) return mimeTypes[format]
  if (Object.values(mimeTypes).includes(format)) return format
  const extension = (data.url || "").split(/[?#]/)[0].split(".").pop().toLowerCase()
  return mimeTypes[extension] || "application/octet-stream"
}

export function resolveDataUrl(url, reactionId, database) {
  const value = (url || "").trim()
  if (!value || Array.from(value).some(char => char.charCodeAt(0) < 32 || char === "\\")) return ""
  if (/^https?:\/\//i.test(value) || /^\/\//.test(value)) return value
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("#")) return ""
  if (value.startsWith("/")) return value
  if (!reactionId) return ""
  const params = new URLSearchParams({ url: value })
  if (database) params.set("database", database)
  return `/api/auxiliary/${encodeURIComponent(reactionId)}?${params}`
}

export function dataPresentation(entry, reactionId, database) {
  const data = entry.data
  const mime = dataMimeType(data)
  const href = data.bytesValue
    ? `data:${mime};base64,${data.bytesValue}`
    : resolveDataUrl(data.url, reactionId, database)
  const value = data.floatValue ?? data.integerValue ?? data.stringValue
  return { ...entry, href, isImage: mime.startsWith("image/"), value,
    downloadName: `${entry.label.replace(/[^a-z0-9._-]/gi, "_")}.${(data.format || "bin").replace(/[^a-z0-9]/gi, "")}` }
}
