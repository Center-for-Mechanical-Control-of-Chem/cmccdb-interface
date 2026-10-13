export function reactionIdentifier(result = {}) {
  return result.reaction_id || result.data?.reactionId || result.row_id || ''
}

// A valid outcome may contain analyses without any identified products.
export function summaryOutcome(reaction = {}) {
  const outcomes = reaction?.outcomesList || []
  return [...outcomes].reverse().find(outcome => outcome?.productsList?.length) ||
    outcomes[outcomes.length - 1] || {}
}

export function preferredIdentifier(compound = {}) {
  const identifiers = compound?.identifiersList || []
  return identifiers.find(identifier => identifier.type === 2 && identifier.value) ||
    identifiers.find(identifier => identifier.value)
}

export function formatPercentage(percentage) {
  if (!percentage || !Number.isFinite(percentage.value)) return 'Not listed'
  // Protobuf floats expose binary roundoff; retain seven significant digits.
  const value = Number(percentage.value.toPrecision(7))
  const precision = percentage.precision == null ? '' :
    ` ± ${Number(percentage.precision.toPrecision(7))}`
  return `${value}${precision}%`
}

export function productYield(product = {}) {
  const measurement = (product?.measurementsList || []).find(item => item.type === 3)
  return formatPercentage(measurement?.percentage)
}
