export function validLnAddress(value) {
  return !value || /^[^@]+@[^@]+$/.test(value)
}
