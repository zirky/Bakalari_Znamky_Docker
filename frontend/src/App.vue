<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { apiFetch } from './api'

const viewMode = ref('child')
const pin = ref('')
const authenticated = ref(false)
const message = ref('')
const active = ref('child')
const childOverview = ref({})
const selectedSchoolYear = ref('')
const childOverviewLoading = ref(false)
const dashboard = ref({})
const grades = ref([])
const rules = ref([])
const preview = ref(null)
const previewMessage = ref('')
const previewLoading = ref(false)
const payoutDraft = ref(null)
const payoutHistory = ref([])
const payoutDraftMessage = ref('')
const payoutDraftLoading = ref(false)
const syncStatus = ref(null)
const syncStatusMessage = ref('')
const syncMode = ref('normal')
const settings = ref({
  start_date: '2026-01-01',
  sync_interval: 'manual',
  payout_threshold_czk: 100,
  ln_address: '',
  payout_mode: 'disabled'
})
const newRule = ref({
  grade_value: '',
  reward_czk: 0,
  active: true
})
const editingId = ref(null)
const ruleMessage = ref('')
const syncMessage = ref('')
const backendAvailable = ref(true)
const childTab = ref('averages')

// Uložení aktuálního režimu pro detekci změn
let previousPayoutMode = 'disabled'

const IDLE_MS = 60000
let idleTimer = null
let logoutInProgress = false

const activityEvents = [
  'mousemove',
  'mousedown',
  'keydown',
  'touchstart',
  'scroll',
  'click'
]

function resetIdleTimer() {
  if (!authenticated.value || logoutInProgress) return

  clearTimeout(idleTimer)
  idleTimer = setTimeout(forceLogout, IDLE_MS)
}

function startIdleWatch() {
  stopIdleWatch()

  activityEvents.forEach((event) => {
    window.addEventListener(event, resetIdleTimer, { passive: true })
  })

  resetIdleTimer()
}

function stopIdleWatch() {
  clearTimeout(idleTimer)
  idleTimer = null

  activityEvents.forEach((event) => {
    window.removeEventListener(event, resetIdleTimer)
  })
}

async function forceLogout() {
  if (logoutInProgress) return

  logoutInProgress = true
  stopIdleWatch()

  try {
    await apiFetch('/api/auth/parent/logout', {
      method: 'POST'
    })
  } finally {
    authenticated.value = false
    viewMode.value = 'child'
    active.value = 'child'
    message.value = 'Byli jste automaticky odhlášeni po 1 minutě nečinnosti.'
    logoutInProgress = false
    await loadChildOverview()
  }
}

function onAuthExpired() {
  if (authenticated.value && !logoutInProgress) {
    forceLogout()
  }
}

async function getJson(path, options) {
  const response = await apiFetch(path, options)
  backendAvailable.value = true

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  return response.json()
}

async function loadChildOverview(
  schoolYear = selectedSchoolYear.value
) {
  childOverviewLoading.value = true

  try {
    const query = schoolYear
      ? `?school_year=${encodeURIComponent(schoolYear)}`
      : ''

    childOverview.value = await getJson(
      `/api/child/overview${query}`
    )

    selectedSchoolYear.value =
      childOverview.value.selected_school_year ||
      childOverview.value.school_year ||
      ''
  } catch {
    childOverview.value = {}
    backendAvailable.value = false
  } finally {
    childOverviewLoading.value = false
  }
}

async function changeChildSchoolYear() {
  await loadChildOverview(selectedSchoolYear.value)
}

async function loadParentSection() {
  try {
    if (active.value === 'dashboard') {
      dashboard.value = await getJson('/api/parent/dashboard')
    }

    if (active.value === 'grades') {
      grades.value = await getJson('/api/parent/grades')
    }

    if (active.value === 'rewards') {
      rules.value = await getJson('/api/parent/reward-rules')
    }

    if (active.value === 'payout') {
      settings.value = await getJson('/api/parent/settings')
      previousPayoutMode = settings.value.payout_mode || 'disabled'
      await loadPayoutPreview()
      await loadPayouts()
    }

    if (active.value === 'sync') {
      await loadSyncStatus()
      settings.value = await getJson('/api/parent/settings')
      previousPayoutMode = settings.value.payout_mode || 'disabled'
    }

    if (active.value === 'settings') {
      settings.value = await getJson('/api/parent/settings')
      previousPayoutMode = settings.value.payout_mode || 'disabled'
    }
  } catch (error) {
    if (error.message.includes('HTTP 401')) {
      authenticated.value = false
      viewMode.value = 'child'
      active.value = 'child'
      stopIdleWatch()
      await loadChildOverview()
    } else {
      backendAvailable.value = false
    }
  }
}

async function loadPayouts() {
  try {
    payoutHistory.value = await getJson('/api/parent/payouts')

    payoutDraft.value = settings.value.payout_mode === 'draft'
      ? payoutHistory.value.find((item) => item.status === 'draft') || null
      : null
  } catch {
    payoutHistory.value = []
    payoutDraft.value = null
  }
}

async function createPayoutDraft() {
  if (settings.value.payout_mode !== 'draft') {
    return
  }

  payoutDraftLoading.value = true
  payoutDraftMessage.value = ''

  try {
    payoutDraft.value = await getJson('/api/parent/payout/draft', {
      method: 'POST',
      body: JSON.stringify({})
    })

    await loadPayouts()
    payoutDraftMessage.value = 'Draft byl vytvořen. Platba nebyla odeslána.'
  } catch (error) {
    payoutDraftMessage.value = error.message === 'HTTP 409'
      ? 'Draft nelze vytvořit: zkontroluj režim, limit, adresu a stav účtu.'
      : 'Draft výplaty se nepodařilo vytvořit.'
  } finally {
    payoutDraftLoading.value = false
  }
}

async function simulatePayoutConfirmation() {
  if (
    settings.value.payout_mode !== 'draft' ||
    !payoutDraft.value ||
    payoutDraft.value.status !== 'draft'
  ) {
    return
  }

  const amountCzk = payoutDraft.value.amount_czk
  const amountSats = payoutDraft.value.amount_sats

  if (!confirm(
    `Potvrdit simulaci payoutu?\n\n` +
    `Částka: ${amountCzk} Kč\n` +
    `Odhad: ${amountSats} sats\n\n` +
    `Platba nebude odeslána.`
  )) {
    return
  }

  payoutDraftLoading.value = true
  payoutDraftMessage.value = ''

  try {
    await getJson(
      `/api/parent/payout/${payoutDraft.value.id || payoutDraft.value.payout_id}/simulate-confirm`,
      {
        method: 'POST'
      }
    )

    await loadPayouts()
    payoutDraftMessage.value =
      'Payout byl simulovaně potvrzen. Platba nebyla odeslána.'
  } catch (error) {
    payoutDraftMessage.value = error.message === 'HTTP 409'
      ? 'Draft je neplatný, protože se stav účtu změnil. Vytvoř nový draft.'
      : 'Simulované potvrzení se nepodařilo provést.'

    await loadPayouts()
  } finally {
    payoutDraftLoading.value = false
  }
}

async function confirmManualPayout() {
  if (settings.value.payout_mode !== 'manual' || !preview.value) {
    return
  }

  const amountCzk = preview.value.payout_eligible_czk
  const amountSats = preview.value.estimated_sats
  const lnAddress = settings.value.ln_address || ''

  if (amountSats === null || amountSats === undefined) {
    payoutDraftMessage.value =
      'Kurz CZK/BTC není dostupný; ostrou platbu nelze připravit.'
    return
  }

  if (!lnAddress || !validLnAddress(lnAddress)) {
    payoutDraftMessage.value =
      'Lightning adresa není platná nebo není nastavená.'
    return
  }

  if (!confirm(
    `Odeslat skutečnou Lightning platbu?\n\n` +
    `Částka: ${amountCzk} Kč\n` +
    `Odhad: ${amountSats} sats\n` +
    `Lightning adresa: ${lnAddress}\n\n` +
    `Platba bude skutečně odeslána přes LNbits.`
  )) {
    return
  }

  payoutDraftLoading.value = true
  payoutDraftMessage.value = ''

  try {
    const payout = await getJson('/api/parent/payout', {
      method: 'POST',
      body: JSON.stringify({})
    })

    payoutDraftMessage.value = payout.status === 'paid'
      ? 'Platba byla úspěšně odeslána a odměny byly označeny jako vyplacené.'
      : 'Payout byl zpracován.'

    await loadPayoutPreview()
    await loadPayouts()
  } catch (error) {
    payoutDraftMessage.value = error.message === 'HTTP 409'
      ? 'Platbu nelze odeslat: zkontroluj režim, limit, zůstatek, adresu nebo existující payout.'
      : 'Skutečnou platbu se nepodařilo odeslat.'

    await loadPayouts()
  } finally {
    payoutDraftLoading.value = false
  }
}

async function loadSyncStatus() {
  syncStatusMessage.value = ''

  try {
    syncStatus.value = await getJson('/api/parent/sync/status')
  } catch {
    syncStatus.value = null
    syncStatusMessage.value =
      'Stav synchronizace se nepodařilo načíst.'
  }
}

async function loadPayoutPreview() {
  previewLoading.value = true
  previewMessage.value = ''

  try {
    preview.value = await getJson('/api/parent/payout/preview')
  } catch (error) {
    preview.value = null
    previewMessage.value = error.message === 'HTTP 401'
      ? 'Přihlášení rodiče vypršelo.'
      : 'Náhled výplaty se nepodařilo načíst.'
  } finally {
    previewLoading.value = false
  }
}

async function login() {
  message.value = ''

  try {
    const response = await apiFetch('/api/auth/parent/login', {
      method: 'POST',
      body: JSON.stringify({
        pin: pin.value
      })
    })

    backendAvailable.value = true

    if (!response.ok) {
      message.value = response.status === 401
        ? 'Neplatný PIN.'
        : `Login selhal (HTTP ${response.status}).`
      return
    }

    authenticated.value = true
    viewMode.value = 'parent'
    active.value = 'dashboard'
    logoutInProgress = false
    pin.value = ''
    startIdleWatch()
    await loadParentSection()
  } catch {
    backendAvailable.value = false
    message.value = 'Backend není dostupný.'
  }
}

async function logout() {
  if (logoutInProgress) {
    return
  }

  logoutInProgress = true
  stopIdleWatch()

  try {
    await apiFetch('/api/auth/parent/logout', {
      method: 'POST'
    })
  } finally {
    authenticated.value = false
    viewMode.value = 'child'
    active.value = 'child'
    logoutInProgress = false
    await loadChildOverview()
  }
}

async function saveRule() {
  ruleMessage.value = ''

  try {
    const method = editingId.value ? 'PUT' : 'POST'
    const path = editingId.value
      ? `/api/parent/reward-rules/${editingId.value}`
      : '/api/parent/reward-rules'

    await getJson(path, {
      method,
      body: JSON.stringify(newRule.value)
    })

    ruleMessage.value = 'Pravidlo bylo uloženo.'
    editingId.value = null
    newRule.value = {
      grade_value: '',
      reward_czk: 0,
      active: true
    }

    await loadParentSection()
  } catch (error) {
    ruleMessage.value = error.message.includes('409')
      ? 'Pravidlo pro tuto známku již existuje.'
      : 'Pravidlo se nepodařilo uložit.'
  }
}

function editRule(rule) {
  editingId.value = rule.id
  newRule.value = {
    grade_value: rule.grade_value,
    reward_czk: rule.reward_czk,
    active: rule.active
  }
  ruleMessage.value = ''
}

function cancelEdit() {
  editingId.value = null
  newRule.value = {
    grade_value: '',
    reward_czk: 0,
    active: true
  }
}

async function removeRule(rule) {
  if (!confirm(`Smazat pravidlo pro známku ${rule.grade_value}?`)) {
    return
  }

  try {
    await getJson(`/api/parent/reward-rules/${rule.id}`, {
      method: 'DELETE'
    })

    ruleMessage.value = 'Pravidlo bylo smazáno.'
    await loadParentSection()
  } catch {
    ruleMessage.value = 'Pravidlo se nepodařilo smazat.'
  }
}

function validLnAddress(value) {
  return !value || /^[^@]+@[^@]+$/.test(value)
}

function formatDateTime(value) {
  if (!value) {
    return 'Nikdy'
  }

  return new Date(value).toLocaleString('cs-CZ')
}

function formatAverage(value) {
  if (value === null || value === undefined) {
    return '—'
  }

  return Number(value).toFixed(2).replace('.', ',')
}

function payoutStatusLabel(status) {
  return {
    draft: 'Draft',
    simulated: 'Simulováno',
    pending: 'Čeká',
    paid: 'Zaplaceno',
    failed: 'Selhalo',
    stale: 'Neaktuální',
    cancelled: 'Zrušeno'
  }[status] || status
}

async function saveSettings() {
  message.value = ''

  const oldMode = previousPayoutMode
  const newMode = settings.value.payout_mode

  const isModeChangeToAuto =
    (oldMode === 'disabled' || oldMode === 'manual') &&
    (newMode === 'draft' || newMode === 'scheduler')

  if (isModeChangeToAuto) {
    const isDraft = newMode === 'draft'
    const confirmMessage = isDraft
      ? 'Opravdu chcete zapnout režim "draft"? Po každé úspěšné plánované synchronizaci bude vytvořen návrh výplaty, ale žádná platba nebude odeslána.'
      : 'Opravdu chcete zapnout režim "scheduler"? Po každé úspěšné plánované synchronizaci může být automaticky odeslána Lightning platba na vaši uloženou LN adresu.'

    if (!confirm(confirmMessage)) {
      // Uživatel zrušil - vrátíme původní režim
      settings.value.payout_mode = oldMode
      message.value = 'Změna režimu výplaty byla zrušena.'
      return
    }
  }

  const payload = {
    start_date: settings.value.start_date,
    sync_interval: settings.value.sync_interval,
    payout_threshold_czk: settings.value.payout_threshold_czk,
    ln_address: settings.value.ln_address,
    payout_mode: settings.value.payout_mode
  }

  // Poslat potvrzení pouze při změně na draft/scheduler
  if (isModeChangeToAuto) {
    payload.auto_payout_confirmed = true
  }

  if (!validLnAddress(payload.ln_address)) {
    message.value = 'LN adresa musí mít tvar jmeno@domena.'
    return
  }

  try {
    await getJson('/api/parent/settings', {
      method: 'PUT',
      body: JSON.stringify(payload)
    })

    // Aktualizovat previousPayoutMode po úspěšném uložení
    previousPayoutMode = settings.value.payout_mode

    await loadParentSection()
    message.value = 'Nastavení uloženo.'
  } catch (error) {
    message.value = `Nastavení se nepodařilo uložit: ${error.message}`
  }
}

async function syncGrades() {
  syncMessage.value = 'Spouštím synchronizaci…'

  try {
    const response = await getJson('/api/parent/sync', {
      method: 'POST',
      body: JSON.stringify({
        from_date: settings.value.start_date,
        mode: syncMode.value
      })
    })

    syncMessage.value =
      `Synchronizace: ${response.grades_new} nových známek. ` +
      `Stav účtu: ${response.running_balance_czk} Kč.`

    await loadSyncStatus()
  } catch (error) {
    syncMessage.value = error.message.includes('501')
      ? 'API Bakalářů zatím není nakonfigurováno.'
      : 'Synchronizace selhala.'

    await loadSyncStatus()
  }
}

async function selectParentSection(name) {
  if (!authenticated.value) {
    return
  }

  resetIdleTimer()
  active.value = name
  await loadParentSection()
}

function selectChildSection() {
  active.value = 'child'
  loadChildOverview()
}

onMounted(async () => {
  window.addEventListener('auth-expired', onAuthExpired)

  await loadChildOverview()

  try {
    const response = await apiFetch('/api/auth/parent/session')

    if (response.ok) {
      authenticated.value = true
      viewMode.value = 'parent'
      active.value = 'dashboard'
      startIdleWatch()
      await loadParentSection()
    }
  } catch {
    backendAvailable.value = false
  }
})

onBeforeUnmount(() => {
  stopIdleWatch()
  window.removeEventListener('auth-expired', onAuthExpired)
})
</script>

<template>
  <main class="shell dark-theme">
    <section
      v-if="viewMode === 'child'"
      class="child-view"
    >
      <header class="page-header">
        <div>
          <p class="eyebrow">Dětský panel</p>
          <h1>Bakaláři známky a odměny</h1>
        </div>

        <div class="child-header-actions">
          <form
            class="parent-login-form"
            @submit.prevent="login"
          >
            <label>
              PIN rodiče
              <input
                v-model="pin"
                type="password"
                inputmode="numeric"
                autocomplete="off"
                placeholder="PIN"
              >
            </label>

            <button
              class="primary-button"
              type="submit"
            >
              Přihlásit rodiče
            </button>
          </form>

          <button
            class="secondary-button"
            type="button"
            :disabled="childOverviewLoading"
            @click="selectChildSection"
          >
            {{ childOverviewLoading ? 'Načítám…' : 'Obnovit' }}
          </button>
        </div>
      </header>

      <p
        v-if="message"
        class="error"
      >
        {{ message }}
      </p>

      <p
        v-if="!backendAvailable"
        class="error"
      >
        Backend není dostupný.
      </p>

      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>Známky</h2>
            <p v-if="childOverview.selected_school_year">
              Školní rok {{ childOverview.selected_school_year }}
            </p>
          </div>

          <label
            v-if="childOverview.available_school_years?.length"
            class="school-year-select"
          >
            Školní rok
            <select
              v-model="selectedSchoolYear"
              :disabled="childOverviewLoading"
              @change="changeChildSchoolYear"
            >
              <option
                v-for="year in childOverview.available_school_years"
                :key="year"
                :value="year"
              >
                {{ year }}
              </option>
            </select>
          </label>
        </div>

        <div class="child-tabs">
  <button :class="{ selected: childTab === 'averages' }" type="button" @click="childTab = 'averages'">Průměry podle předmětu</button>
  <button :class="{ selected: childTab === 'grades' }" type="button" @click="childTab = 'grades'">Seznam známek</button>
</div>
        

        <div v-if="childTab === 'averages'">
  <h3>Průměry podle předmětu</h3>

        <p v-if="!childOverview.subjects?.length">
          Pro vybraný školní rok nejsou k dispozici číselné známky.
        </p>

        <table v-else>
          <thead>
            <tr>
              <th>Předmět</th>
              <th>Počet známek</th>
              <th>Průměr</th>
            </tr>
          </thead>

          <tbody>
            <tr
              v-for="subject in childOverview.subjects"
              :key="subject.subject"
            >
              <td>{{ subject.subject }}</td>
              <td>{{ subject.grades_count }}</td>
              <td>{{ formatAverage(subject.average) }}</td>
            </tr>
          </tbody>
        </table>
          </div>

        <div v-if="childTab === 'grades'">
  <h3>Seznam známek</h3>

        <p v-if="!childOverview.grades?.length">
          Pro vybraný školní rok nejsou načtené žádné známky.
        </p>

        <div
          v-else
          class="grades-scroll"
        >
          <table>
            <thead>
              <tr>
                <th>Datum</th>
                <th>Předmět</th>
                <th>Známka</th>
                <th>Popis</th>
              </tr>
            </thead>

            <tbody>
              <tr
                v-for="grade in childOverview.grades"
                :key="grade.id"
              >
                <td>{{ grade.grade_date }}</td>
                <td>{{ grade.subject }}</td>
                <td>{{ grade.grade_value }}</td>
                <td>{{ grade.description || '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
       </div>
      </section>
    </section>

    <section
      v-else
      class="parent-view"
    >
      <header class="page-header">
        <div>
          <p class="eyebrow">Rodičovský panel</p>
          <h1>Bakaláři známky a odměny</h1>
        </div>

        <button
          class="secondary-button"
          @click="logout"
        >
          Odhlásit rodiče
        </button>
      </header>

      <nav class="nav">
        <button
          :class="{ selected: active === 'dashboard' }"
          @click="selectParentSection('dashboard')"
        >
          Přehled
        </button>

        <button
          :class="{ selected: active === 'grades' }"
          @click="selectParentSection('grades')"
        >
          Známky
        </button>

        <button
          :class="{ selected: active === 'rewards' }"
          @click="selectParentSection('rewards')"
        >
          Odměny
        </button>

        <button
          :class="{ selected: active === 'payout' }"
          @click="selectParentSection('payout')"
        >
          Výplata
        </button>

        <button
          :class="{ selected: active === 'sync' }"
          @click="selectParentSection('sync')"
        >
          Synchronizace
        </button>

        <button
          :class="{ selected: active === 'settings' }"
          @click="selectParentSection('settings')"
        >
          Nastavení
        </button>
      </nav>

      <p
        v-if="!backendAvailable"
        class="error"
      >
        Backend není dostupný.
      </p>

      <section
        v-if="active === 'dashboard'"
        class="panel"
      >
        <h2>Rodičovský přehled</h2>

        <div class="cards">
          <div>
            Čekající odměny
            <strong>
              {{ dashboard.pending_reward_czk ?? 0 }} Kč
            </strong>
          </div>

          <div>
            Počet známek
            <strong>
              {{ dashboard.grades_count ?? 0 }}
            </strong>
          </div>

          <div>
            Čekající položky
            <strong>
              {{ dashboard.pending_rewards_count ?? 0 }}
            </strong>
          </div>
        </div>
      </section>

      <section
        v-if="active === 'grades'"
        class="panel"
      >
        <h2>Známky</h2>

        <button
          class="secondary-button"
          @click="loadParentSection"
        >
          Obnovit
        </button>

        <div
          v-if="grades.length"
          class="grades-scroll"
        >
          <table>
            <thead>
              <tr>
                <th>Datum</th>
                <th>Předmět</th>
                <th>Známka</th>
                <th>Popis</th>
              </tr>
            </thead>

            <tbody>
              <tr
                v-for="grade in grades"
                :key="grade.id"
              >
                <td>{{ grade.grade_date }}</td>
                <td>{{ grade.subject }}</td>
                <td>{{ grade.grade_value }}</td>
                <td>{{ grade.description || '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-else>
          Zatím nejsou načtené žádné známky.
        </p>
      </section>

      <section
        v-if="active === 'rewards'"
        class="panel"
      >
        <h2>Pravidla odměn</h2>

        <form
          class="inline"
          @submit.prevent="saveRule"
        >
          <input
            v-model="newRule.grade_value"
            placeholder="Známka, např. 1"
            required
          >

          <input
            v-model.number="newRule.reward_czk"
            type="number"
            step="1"
            placeholder="CZK"
          >

          <label>
            <input
              v-model="newRule.active"
              type="checkbox"
            >
            Aktivní
          </label>

          <button
            class="primary-button"
            type="submit"
          >
            {{ editingId ? 'Uložit změnu' : 'Přidat pravidlo' }}
          </button>

          <button
            v-if="editingId"
            class="secondary-button"
            type="button"
            @click="cancelEdit"
          >
            Zrušit
          </button>
        </form>

        <p
          v-if="ruleMessage"
          :class="ruleMessage.includes('uloženo') ? 'success' : 'error'"
        >
          {{ ruleMessage }}
        </p>

        <table>
          <thead>
            <tr>
              <th>Známka</th>
              <th>Odměna/pokuta</th>
              <th>Aktivní</th>
              <th>Akce</th>
            </tr>
          </thead>

          <tbody>
            <tr
              v-for="rule in rules"
              :key="rule.id"
            >
              <td>{{ rule.grade_value }}</td>
              <td>{{ rule.reward_czk }} Kč</td>
              <td>{{ rule.active ? 'Ano' : 'Ne' }}</td>
              <td>
                <button
                  class="secondary-button"
                  type="button"
                  @click="editRule(rule)"
                >
                  Upravit
                </button>

                <button
                  class="danger-button"
                  type="button"
                  @click="removeRule(rule)"
                >
                  Smazat
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section
        v-if="active === 'payout'"
        class="panel"
      >
        <h2>Výplata odměn</h2>

        <p>
          Režim výplaty:
          <strong>
            {{ settings.payout_mode }}
          </strong>
        </p>

        <p>
          Náhled ani draft neodesílají platbu.
          Ostrá platba se odešle pouze po explicitním potvrzení
          v režimu manual.
        </p>

        <button
          class="secondary-button"
          :disabled="previewLoading"
          @click="loadPayoutPreview"
        >
          {{ previewLoading ? 'Načítám…' : 'Načíst náhled' }}
        </button>

        <button
          v-if="settings.payout_mode === 'draft'"
          class="secondary-button"
          :disabled="
            payoutDraftLoading ||
            payoutDraft?.status === 'simulated'
          "
          @click="createPayoutDraft"
        >
          {{ payoutDraftLoading ? 'Připravuji…' : 'Vytvořit draft' }}
        </button>

        <button
          v-if="
            settings.payout_mode === 'draft' &&
            payoutDraft?.status === 'draft'
          "
          class="secondary-button"
          :disabled="payoutDraftLoading"
          @click="simulatePayoutConfirmation"
        >
          Simulovat potvrzení
        </button>

        <button
          v-if="settings.payout_mode === 'manual'"
          class="danger-button"
          :disabled="
            payoutDraftLoading ||
            !preview ||
            preview.payout_eligible_czk <= 0
          "
          @click="confirmManualPayout"
        >
          {{ payoutDraftLoading ? 'Odesílám…' : 'Odeslat skutečnou platbu' }}
        </button>

        <p
          v-if="previewMessage"
          class="error"
        >
          {{ previewMessage }}
        </p>

        <p
          v-if="payoutDraftMessage"
          :class="
            payoutDraftMessage.includes('neodeslána') ||
            payoutDraftMessage.includes('potvrzen') ||
            payoutDraftMessage.includes('úspěšně')
              ? 'success'
              : 'error'
          "
        >
          {{ payoutDraftMessage }}
        </p>

        <div
          v-if="preview"
          class="cards"
        >
          <div>
            Stav účtu
            <strong>
              {{ preview.pending_reward_czk }} Kč
            </strong>
          </div>

          <div>
            Částka k výplatě
            <strong>
              {{ preview.payout_eligible_czk }} Kč
            </strong>
          </div>

          <div>
            Limit
            <strong>
              {{ preview.payout_threshold_czk }} Kč
            </strong>
          </div>

          <div>
            Odhad
            <strong>
              {{
                preview.estimated_sats === null
                  ? 'Kurz není dostupný'
                  : `${preview.estimated_sats} sats`
              }}
            </strong>
          </div>

          <div>
            Lightning adresa
            <strong>
              {{
                preview.ln_address_configured
                  ? 'Nastavena'
                  : 'Nenastavena'
              }}
            </strong>
          </div>
        </div>

        <div
          v-if="payoutDraft"
          class="cards"
        >
          <div>
            Aktivní draft
            <strong>
              #{{ payoutDraft.payout_id || payoutDraft.id }}
            </strong>
          </div>

          <div>
            Částka
            <strong>
              {{ payoutDraft.amount_czk }} Kč
            </strong>
          </div>

          <div>
            Sats
            <strong>
              {{ payoutDraft.amount_sats }}
            </strong>
          </div>

          <div>
            Stav
            <strong>
              {{ payoutStatusLabel(payoutDraft.status) }}
            </strong>
          </div>

          <div v-if="payoutDraft.ln_address">
            Lightning adresa
            <strong>
              {{ payoutDraft.ln_address }}
            </strong>
          </div>
        </div>

        <h3>Historie výplat</h3>

        <p v-if="!payoutHistory.length">
          Zatím nejsou evidované žádné výplaty.
        </p>

        <table v-else>
          <thead>
            <tr>
              <th>Datum</th>
              <th>Částka</th>
              <th>Sats</th>
              <th>Lightning adresa</th>
              <th>Stav</th>
              <th>Chyba</th>
            </tr>
          </thead>

          <tbody>
            <tr
              v-for="payout in payoutHistory"
              :key="payout.id || payout.payout_id"
            >
              <td>
                {{ formatDateTime(payout.completed_at || payout.created_at) }}
              </td>
              <td>{{ payout.amount_czk }} Kč</td>
              <td>{{ payout.amount_sats }}</td>
              <td>{{ payout.ln_address }}</td>
              <td>{{ payoutStatusLabel(payout.status) }}</td>
              <td>{{ payout.error_message || '' }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section
        v-if="active === 'sync'"
        class="panel"
      >
        <h2>Synchronizace</h2>

        <div class="cards">
          <div>
            Stav účtu
            <strong>
              {{ syncStatus?.running_balance_czk ?? 0 }} Kč
            </strong>
          </div>

          <div>
            Z toho k výplatě
            <strong>
              {{ syncStatus?.payout_eligible_czk ?? 0 }} Kč
            </strong>
          </div>

          <div>
            Kladné odměny
            <strong>
              {{ syncStatus?.positive_pending_czk ?? 0 }} Kč
            </strong>
          </div>

          <div>
            Záporné úpravy
            <strong>
              {{ syncStatus?.negative_pending_czk ?? 0 }} Kč
            </strong>
          </div>

          <div>
            Poslední synchronizace
            <strong>
              {{ formatDateTime(syncStatus?.last_sync_at) }}
            </strong>
          </div>

          <div>
            Stav posledního běhu
            <strong>
              {{ syncStatus?.sync_status ?? 'neznámý' }}
            </strong>
          </div>
        </div>

        <p>
          Načítat od:
          {{ syncStatus?.sync_from_date || settings.start_date }}
        </p>

        <p
          v-if="syncStatusMessage"
          class="error"
        >
          {{ syncStatusMessage }}
        </p>

        <label>
          Režim synchronizace

          <select v-model="syncMode">
            <option value="normal">
              Běžná synchronizace
            </option>

            <option value="backtest">
              Backtest od zadaného data
            </option>
          </select>
        </label>

        <button
          class="secondary-button"
          @click="syncGrades"
        >
          Spustit synchronizaci
        </button>

        <button
          class="secondary-button"
          @click="loadSyncStatus"
        >
          Obnovit stav
        </button>

        <p>
          {{ syncMessage }}
        </p>

        <p>
          Synchronizace sama nespouští výplatu.
          Skutečné odeslání je možné pouze ručně v režimu manual
          po explicitním potvrzení.
        </p>
      </section>

      <section
        v-if="active === 'settings'"
        class="panel"
      >
        <h2>Nastavení</h2>

        <form
          class="settings"
          @submit.prevent="saveSettings"
        >
          <label>
            Počáteční datum

            <input
              v-model="settings.start_date"
              type="date"
            >
          </label>

          <label>
            Interval

            <select v-model="settings.sync_interval">
              <option value="manual">
                Ruční
              </option>

              <option value="weekly">
                Týdně
              </option>

              <option value="monthly">
                Měsíčně
              </option>
            </select>
          </label>

          <label>
            Režim výplaty

            <select v-model="settings.payout_mode">
              <option value="disabled">
                Vypnuto
              </option>

              <option value="draft">
                Draft / simulace
              </option>

              <option value="manual">
                Ruční
              </option>

              <option value="scheduler">
                Scheduler
              </option>
            </select>
          </label>

          <label>
            Limit výplaty v CZK

            <input
              v-model.number="settings.payout_threshold_czk"
              type="number"
              min="0"
            >
          </label>

          <label>
            Lightning adresa

            <input
              v-model.trim="settings.ln_address"
              type="text"
              inputmode="email"
              autocomplete="off"
              placeholder="jmeno@domena.tld"
            >

            <small>
              Adresa se pouze uloží;
              platby se nespouštějí automaticky.
            </small>
          </label>

          <button
            class="primary-button"
            type="submit"
          >
            Uložit nastavení
          </button>

          <p
            v-if="message"
            :class="
              message === 'Nastavení uloženo.'
                ? 'success'
                : 'error'
            "
          >
            {{ message }}
          </p>
        </form>
      </section>
    </section>
  </main>
</template>

<style>
:root {
  color-scheme: dark;
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  color: #f8fafc;
  background: #0f172a;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  background: #0f172a;
  color: #f8fafc;
}

button,
input,
select {
  font: inherit;
}

button {
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.shell {
  min-height: 100vh;
  padding: 32px;
  background:
    radial-gradient(
      circle at top right,
      #1e3a8a 0,
      transparent 36rem
    ),
    #0f172a;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin: 0 auto 24px;
  max-width: 1280px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #60a5fa;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1,
h2,
h3 {
  margin-top: 0;
}

h1 {
  margin-bottom: 0;
  font-size: clamp(2rem, 4vw, 3.2rem);
}

h2 {
  margin-bottom: 20px;
  font-size: 1.7rem;
}

h3 {
  margin-top: 32px;
  color: #e2e8f0;
}

p {
  color: #cbd5e1;
}

.shell > section,
.child-view,
.parent-view {
  max-width: 1280px;
  margin: 0 auto;
}

.panel {
  margin-bottom: 24px;
  padding: 24px;
  border: 1px solid #334155;
  border-radius: 18px;
  background: rgba(23, 32, 51, 0.94);
  box-shadow: 0 20px 45px rgba(2, 6, 23, 0.25);
}

.panel-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.panel-header h2 {
  margin-bottom: 8px;
}

.panel-header p {
  margin-bottom: 0;
}

.school-year-select {
  min-width: 180px;
}

.nav {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  max-width: 1280px;
  margin: 0 auto 24px;
  padding: 14px;
  border: 1px solid #334155;
  border-radius: 16px;
  background: #172033;
}

.nav button,
.primary-button,
.secondary-button,
.danger-button {
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 10px 16px;
  color: #f8fafc;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    transform 0.15s ease;
}

.nav button:hover,
.primary-button:hover,
.secondary-button:hover,
.danger-button:hover {
  transform: translateY(-1px);
}

.nav button {
  background: #1e293b;
  border-color: #334155;
}

.nav button.selected {
  background: #2563eb;
  border-color: #60a5fa;
}

.primary-button {
  background: #2563eb;
  border-color: #3b82f6;
}

.secondary-button {
  background: #1e293b;
  border-color: #475569;
}

.danger-button {
  background: #991b1b;
  border-color: #ef4444;
}

.child-header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  justify-content: flex-end;
  gap: 12px;
}

.parent-login-form {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 10px;
}

.parent-login-form label {
  min-width: 160px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin: 20px 0;
}

.cards > div {
  min-height: 84px;
  padding: 16px;
  border: 1px solid #334155;
  border-radius: 14px;
  background: #1e293b;
  color: #cbd5e1;
}

.cards strong {
  display: block;
  margin-top: 8px;
  color: #f8fafc;
  font-size: 1.25rem;
}

table {
  width: 100%;
  margin-top: 16px;
  border-collapse: collapse;
  overflow: hidden;
  border: 1px solid #334155;
  border-radius: 12px;
  background: #172033;
}

th,
td {
  padding: 12px 14px;
  border-bottom: 1px solid #334155;
  text-align: left;
  vertical-align: top;
}

th {
  background: #1e293b;
  color: #e2e8f0;
  font-weight: 700;
}

td {
  color: #cbd5e1;
}

tr:last-child td {
  border-bottom: 0;
}

.grades-scroll {
  max-height: 420px;
  margin-top: 16px;
  overflow: auto;
  border: 1px solid #334155;
  border-radius: 12px;
  background: #172033;
}

.grades-scroll table {
  min-width: 720px;
  margin-top: 0;
  border: 0;
  border-radius: 0;
}

.grades-scroll thead th {
  position: sticky;
  top: 0;
  z-index: 1;
}

form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: end;
}

form.settings {
  display: grid;
  max-width: 620px;
  gap: 16px;
}

label {
  display: grid;
  gap: 7px;
  color: #cbd5e1;
}

input,
select {
  width: 100%;
  min-height: 44px;
  border: 1px solid #475569;
  border-radius: 10px;
  padding: 10px 12px;
  background: #0f172a;
  color: #f8fafc;
}

input:focus,
select:focus {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.inline input:not([type="checkbox"]) {
  width: auto;
  min-width: 150px;
}

input[type="checkbox"] {
  width: auto;
  min-height: auto;
}

small {
  color: #94a3b8;
}

.success {
  color: #4ade80;
}

.error {
  color: #fca5a5;
}

@media (max-width: 720px) {
  .shell {
    padding: 16px;
  }

  .page-header,
  .panel-header {
    display: grid;
  }

  .panel {
    padding: 16px;
  }

  .school-year-select {
    min-width: 0;
  }

  .child-header-actions {
    display: grid;
    justify-content: stretch;
  }

  .parent-login-form {
    display: grid;
  }

  .parent-login-form label {
    min-width: 0;
  }

  .child-header-actions > button,
  .parent-login-form button {
    width: 100%;
  }

  .nav {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .nav button {
    width: 100%;
  }
}
</style>
.child-tabs { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.child-tabs button { border: 1px solid #475569; border-radius: 10px; padding: 10px 16px; background: #1e293b; color: #f8fafc; }
.child-tabs button.selected { border-color: #60a5fa; background: #2563eb; }
.lesson-card { display: grid; gap: 5px; margin-bottom: 10px; padding: 10px; border: 1px solid #475569; border-radius: 10px; background: #172033; color: #cbd5e1; }
.lesson-card:last-child { margin-bottom: 0; }
.lesson-card strong { color: #f8fafc; }
.lesson-number { color: #60a5fa; font-weight: 700; }
