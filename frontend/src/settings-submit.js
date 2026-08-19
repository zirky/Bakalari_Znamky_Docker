function findField(form, names, fallbackIndex) {
  for (const name of names) {
    const field = form.querySelector(`[name="${name}"], #${name}`)
    if (field) return field
  }
  return form.elements[fallbackIndex] || null
}

function readValue(field) {
  return field?.value ?? ''
}

function installSettingsSubmit() {
  document.addEventListener('submit', async (event) => {
    const form = event.target
    if (!(form instanceof HTMLFormElement)) return

    const text = form.textContent || ''
    if (!/nastaven|settings/i.test(text)) return

    event.preventDefault()
    event.stopImmediatePropagation()

    const startDate = findField(form, ['start_date', 'startDate'], 0)
    const interval = findField(form, ['interval_minutes', 'intervalMinutes', 'interval'], 1)
    const dailyLimit = findField(form, ['daily_limit', 'dailyLimit', 'limit'], 2)
    const lnAddress = findField(form, ['ln_address', 'lnAddress', 'lightning_address'], 3)
    const payload = {
      start_date: readValue(startDate),
      interval_minutes: Number(readValue(interval)),
      daily_limit: Number(readValue(dailyLimit)),
      ln_address: readValue(lnAddress).trim()
    }

    try {
      console.log('[settings] submit', payload)
      if (payload.ln_address && !/^[^@]+@[^@]+$/.test(payload.ln_address)) {
        throw new Error('LN adresa musí mít tvar jmeno@domena')
      }
      console.log('[settings] sending PUT /api/parent/settings')
      const response = await fetch('/api/parent/settings', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!response.ok) throw new Error(`PUT /api/parent/settings: ${response.status}`)
      console.log('[settings] saved, reloading settings')
      window.location.reload()
    } catch (error) {
      console.error('[settings] save failed', error)
      let message = form.querySelector('[role="alert"], .error, .message')
      if (!message) {
        message = document.createElement('div')
        message.setAttribute('role', 'alert')
        form.prepend(message)
      }
      message.textContent = error instanceof Error ? error.message : String(error)
    }
  }, true)
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installSettingsSubmit, { once: true })
} else {
  installSettingsSubmit()
}
