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
    const payoutMode = findField(form, ['payout_mode', 'payoutMode'], 4)
    
    const payload = {
      start_date: readValue(startDate),
      interval_minutes: Number(readValue(interval)),
      daily_limit: Number(readValue(dailyLimit)),
      ln_address: readValue(lnAddress).trim(),
      payout_mode: readValue(payoutMode) || 'manual',
    }

    // Kontrola změny režimu a potvrzovací dialog
    const oldMode = window.__currentPayoutMode || 'manual'
    const newMode = payload.payout_mode
    
    const isModeChangeToAuto = 
      (oldMode === 'disabled' || oldMode === 'manual') &&
      (newMode === 'draft' || newMode === 'scheduler')
    
    if (isModeChangeToAuto) {
      const isDraft = newMode === 'draft'
      const message = isDraft
        ? 'Opravdu chcete zapnout režim "draft"? Po každé úspěšné plánované synchronizaci bude vytvořen návrh výplaty, ale žádná platba nebude odeslána.'
        : 'Opravdu chcete zapnout režim "scheduler"? Po každé úspěšné plánované synchronizaci může být automaticky odeslána Lightning platba na vaši uloženou LN adresu.'
      
      if (!confirm(message)) {
        // Uživatel zrušil - vrátíme původní režim
        if (payoutMode) payoutMode.value = oldMode
        console.log('[settings] payout mode change cancelled')
        return
      }
      
      // Uživatel potvrdil - posíláme potvrzení
      payload.auto_payout_confirmed = true
      console.log('[settings] payout mode change confirmed:', newMode)
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

// Uložení aktuálního režimu pro detekci změn
document.addEventListener('DOMContentLoaded', () => {
  const payoutModeField = document.querySelector('[name="payout_mode"], #payout_mode')
  if (payoutModeField) {
    window.__currentPayoutMode = payoutModeField.value || 'manual'
  }
})

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installSettingsSubmit, { once: true })
} else {
  installSettingsSubmit()
}
