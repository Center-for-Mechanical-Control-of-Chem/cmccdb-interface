import reaction_pb from "cmccdb-schema"

export function fieldLabel(field) {
  const special = { ph: "pH", rpm: "RPM", gForce: "G force", chmoId: "CHMO ID" }
  if (special[field]) return special[field]
  const text = field.replace(/(List|Map)$/, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/_/g, " ")
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase()
}

export function enumLabel(values, value) {
  const name = Object.keys(values || {}).find(key => values[key] === value) || String(value)
  if (["LED", "RPM", "PSI", "KPSI", "PDMS"].includes(name)) return name
  return fieldLabel(name)
}

const enumeration = values => ({ enum: values })
const quantity = units => ({ units })
const temperature = quantity(reaction_pb.Temperature.TemperatureUnit)
const pressure = quantity(reaction_pb.Pressure.PressureUnit)
const time = quantity(reaction_pb.Time.TimeUnit)
const length = quantity(reaction_pb.Length.LengthUnit)
const current = quantity(reaction_pb.Current.CurrentUnit)
const voltage = quantity(reaction_pb.Voltage.VoltageUnit)

const schemas = {
  temperature: {
    control: { type: enumeration(reaction_pb.TemperatureConditions.TemperatureControl.TemperatureControlType) },
    setpoint: temperature,
    measurementsList: {
      type: enumeration(reaction_pb.TemperatureConditions.TemperatureMeasurement.TemperatureMeasurementType),
      time, temperature,
    },
  },
  pressure: {
    control: { type: enumeration(reaction_pb.PressureConditions.PressureControl.PressureControlType) },
    setpoint: pressure,
    atmosphere: { type: enumeration(reaction_pb.PressureConditions.Atmosphere.AtmosphereType) },
    measurementsList: {
      type: enumeration(reaction_pb.PressureConditions.PressureMeasurement.PressureMeasurementType),
      time, pressure,
    },
  },
  stirring: {
    type: enumeration(reaction_pb.StirringConditions.StirringMethodType),
    rate: { type: enumeration(reaction_pb.StirringConditions.StirringRate.StirringRateType) },
  },
  illumination: {
    type: enumeration(reaction_pb.IlluminationConditions.IlluminationType),
    peakWavelength: quantity(reaction_pb.Wavelength.WavelengthUnit),
    distanceToVessel: length,
  },
  electrochemistry: {
    type: enumeration(reaction_pb.ElectrochemistryConditions.ElectrochemistryType),
    current, voltage, electrodeSeparation: length,
    measurementsList: { time, current, voltage },
    cell: { type: enumeration(reaction_pb.ElectrochemistryConditions.ElectrochemistryCell.ElectrochemistryCellType) },
  },
  flow: {
    type: enumeration(reaction_pb.FlowConditions.FlowType),
    tubing: { type: enumeration(reaction_pb.FlowConditions.Tubing.TubingType), diameter: length },
  },
  mechanochemistry: {
    type: enumeration(reaction_pb.MechanochemistryConditions.MechanochemistryType),
    frequency: quantity(reaction_pb.Frequency.FrequencyUnit),
    force: quantity(reaction_pb.Force.ForceUnit), duration: time,
    ballRadius: length, dimensionList: length, contactSize: length,
    gForce: quantity(reaction_pb.GravitationalAcceleration.GravitationalAccelerationUnit),
  },
}

const unitSymbols = {
  CELSIUS: "°C", FAHRENHEIT: "°F", KELVIN: "K", HERTZ: "Hz", RPM: "rpm",
  NEWTON: "N", MILLINEWTON: "mN", DAY: "d", HOUR: "h", MINUTE: "min", SECOND: "s",
  CENTIMETER: "cm", MILLIMETER: "mm", METER: "m", INCH: "in", FOOT: "ft",
  STANDARD_GRAVITATIONAL_ACCELERATION: "g", NANOMETER: "nm", WAVENUMBER: "cm⁻¹",
  AMPERE: "A", MILLIAMPERE: "mA", VOLT: "V", MILLIVOLT: "mV", BAR: "bar",
  ATMOSPHERE: "atm", PSI: "psi", KPSI: "kpsi", PASCAL: "Pa", KILOPASCAL: "kPa",
  TORR: "Torr", MM_HG: "mmHg",
}

function formatQuantity(value, units) {
  const unitName = Object.keys(units || {}).find(key => units[key] === value.units)
  const unit = unitSymbols[unitName] || (unitName === "UNSPECIFIED" ? "(unit unspecified)" : `(${enumLabel(units, value.units)})`)
  const precision = value.precision == null ? "" : ` ± ${value.precision}`
  return `${value.value}${precision} ${unit}`
}

const otherFields = ["reflux", "ph", "conditionsAreDynamic", "details"]
export const conditionTabs = ["temperature", "pressure", "stirring", "illumination", "electrochemistry", "flow", "mechanochemistry", "other"]

function hasValue(value) {
  return value !== undefined && value !== null && value !== "" &&
    (!Array.isArray(value) || value.length > 0)
}

export function availableConditions(conditions = {}) {
  return conditionTabs.filter(tab => tab === "other"
    ? otherFields.some(field => hasValue(conditions[field]))
    : hasValue(conditions[tab]))
}

export function conditionRows(conditions = {}, tab) {
  const value = tab === "other"
    ? Object.fromEntries(otherFields.map(field => [field, conditions[field]]))
    : conditions[tab]
  const rows = []
  function visit(value, schema = {}, path = []) {
    if (!hasValue(value)) return
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, schema, [...path.slice(0, -1), `${path[path.length - 1]} ${index + 1}`]))
    } else if (schema.units && typeof value === "object") {
      if (hasValue(value.value)) rows.push({ label: path.join(" · "), value: formatQuantity(value, schema.units) })
    } else if (typeof value === "object") {
      Object.entries(value).forEach(([key, item]) => visit(item, schema[key], [...path, fieldLabel(key)]))
    } else {
      const text = schema.enum ? enumLabel(schema.enum, value) : typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)
      rows.push({ label: path.join(" · "), value: text })
    }
  }
  visit(value, schemas[tab])
  return rows
}
