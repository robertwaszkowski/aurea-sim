<template>
  <v-container>
    <v-row>
      <v-col>
        <h1 class="text-h4 mb-2">Settings</h1>
        <p class="text-body-1 text-medium-emphasis mb-6">
          Configure your AureaSim environment.
        </p>
      </v-col>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-item><v-card-title><v-icon start>mdi-database-check</v-icon>Reference Data</v-card-title></v-card-item>
          <v-card-text>
            <v-alert v-if="reference.valid" type="success" variant="tonal">
              Calibration repository active: {{ reference.profiles }} task profiles and {{ reference.calibration_samples?.toLocaleString() }} samples.
            </v-alert>
            <v-alert v-else type="warning" variant="tonal">No valid historical-task repository is configured.</v-alert>
            <div class="text-caption mt-3">{{ reference.path }}</div>
            <v-list density="compact" class="mt-3">
              <v-list-item v-for="source in sources" :key="source.source_id" :title="source.display_name || source.source_id" :subtitle="`${source.process_id || ''} ${source.process_version || ''} · ${source.calibration_samples?.toLocaleString() || 0} samples`">
                <template #append><v-switch :model-value="source.enabled" hide-details density="compact" @update:model-value="toggleSource(source, Boolean($event))" /></template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-item>
            <v-card-title>
              <v-icon start>mdi-key</v-icon>
              Gemini API Key
            </v-card-title>
          </v-card-item>

          <v-card-text>
            <v-alert
              v-if="settings.api_key_set"
              type="success"
              variant="tonal"
              class="mb-4"
            >
              API key is configured: {{ settings.api_key_masked }}
            </v-alert>
            <v-alert
              v-else
              type="warning"
              variant="tonal"
              class="mb-4"
            >
              No API key configured. AI features will not work.
            </v-alert>

            <v-text-field
              v-model="newApiKey"
              label="New API Key"
              :type="showKey ? 'text' : 'password'"
              :append-inner-icon="showKey ? 'mdi-eye-off' : 'mdi-eye'"
              @click:append-inner="showKey = !showKey"
              variant="outlined"
              hint="Enter your Google Gemini API key"
              persistent-hint
            />

            <v-btn
              class="mt-4"
              color="primary"
              :loading="saving"
              :disabled="!newApiKey"
              @click="saveKey"
            >
              Save API Key
            </v-btn>

            <v-snackbar v-model="showSnackbar" :timeout="3000" color="success">
              API key saved successfully.
            </v-snackbar>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
  import { ref, onMounted } from 'vue'

  interface SettingsData {
    api_key_set: boolean
    api_key_masked: string
  }
  interface ReferenceData { valid: boolean; path: string; profiles?: number; calibration_samples?: number }
  interface ReferenceSource { source_id: string; display_name?: string; process_id?: string; process_version?: string; calibration_samples?: number; enabled: boolean }

  const settings = ref<SettingsData>({ api_key_set: false, api_key_masked: '' })
  const reference = ref<ReferenceData>({ valid: false, path: '' })
  const sources = ref<ReferenceSource[]>([])
  const newApiKey = ref('')
  const showKey = ref(false)
  const saving = ref(false)
  const showSnackbar = ref(false)

  onMounted(async () => {
    try {
      const res = await fetch('/api/settings')
      settings.value = await res.json()
      const referenceResponse = await fetch('/api/reference-data')
      reference.value = await referenceResponse.json()
      if (reference.value.valid) sources.value = (await (await fetch('/api/reference-data/sources')).json()).sources
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  })

  async function toggleSource (source: ReferenceSource, enabled: boolean) {
    const response = await fetch(`/api/reference-data/sources/${encodeURIComponent(source.source_id)}?enabled=${enabled}`, { method: 'PUT' })
    if (response.ok) sources.value = (await response.json()).sources
  }

  async function saveKey () {
    saving.value = true
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: newApiKey.value }),
      })
      if (res.ok) {
        showSnackbar.value = true
        newApiKey.value = ''
        // Reload settings to show new masked key
        const updated = await fetch('/api/settings')
        settings.value = await updated.json()
      }
    } catch (e) {
      console.error('Failed to save settings:', e)
    } finally {
      saving.value = false
    }
  }
</script>
