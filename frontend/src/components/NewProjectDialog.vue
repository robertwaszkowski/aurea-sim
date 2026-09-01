<template>
  <v-dialog v-model="dialog" max-width="1020px" persistent>
    <v-card
      @dragenter.prevent.stop="apiKeySet ? dragging = true : null"
      @dragover.prevent.stop="apiKeySet ? dragging = true : null"
      :style="{ width: cardWidth, maxWidth: '100%', transition: 'width 0.35s cubic-bezier(0.4, 0, 0.2, 1)', margin: '0 auto', position: 'relative' }"
    >
      <!-- Overlay drop zone for the ENTIRE modal -->
      <div v-if="dragging" class="position-absolute d-flex align-center justify-center" 
           style="inset: 0; z-index: 1000; background: rgba(var(--v-theme-surface), 0.95); border: 4px dashed rgb(var(--v-theme-primary)); backdrop-filter: blur(4px); border-radius: inherit;"
           @dragover.prevent.stop
           @dragleave.prevent.stop="dragging = false"
           @drop.prevent.stop="apiKeySet ? onDrop($event) : null"
      >
        <div class="text-center">
          <v-icon size="64" color="primary" class="mb-3">mdi-cloud-upload-outline</v-icon>
          <div class="text-h5 text-primary font-weight-bold mb-2">Drop BPMN file to upload</div>
          <div class="text-body-2 text-medium-emphasis">Release the mouse button to import the model.</div>
        </div>
      </div>

      <!-- ── Header ─────────────────────────────────────────────────── -->
      <v-card-title class="pa-4 bg-primary d-flex align-center" style="color: rgba(0,0,0,0.87); gap:12px">
        <template v-if="simulating">
          <span>{{ completedProjectTitle || (completedProjectName ? humanize(completedProjectName) : 'Run Simulation') }}</span>
          <v-spacer />
          <v-tooltip v-if="status === 'running'" text="Minimize to background" location="bottom">
            <template v-slot:activator="{ props: tp }">
              <v-btn
                v-bind="tp"
                icon="mdi-minus"
                variant="text"
                size="small"
                style="color: rgba(0,0,0,0.75)"
                @click="minimize"
              />
            </template>
          </v-tooltip>
        </template>
        <template v-else>
          <span>Run Simulation</span>
          <v-spacer />
          <v-menu v-if="apiKeySet" :close-on-content-click="false" location="bottom end">
            <template v-slot:activator="{ props: menuProps }">
              <v-tooltip text="Simulation Settings" location="bottom">
                <template v-slot:activator="{ props: tp }">
                  <v-btn icon="mdi-cog-outline" variant="text" size="small" style="color: rgba(0,0,0,0.6)" v-bind="Object.assign({}, menuProps, tp)" />
                </template>
              </v-tooltip>
            </template>
            <v-card width="350" class="pa-4">
              <div class="text-subtitle-2 font-weight-bold mb-3">Simulation Settings</div>
              <v-text-field v-model="form.industry_context" label="Industry Context (Optional)" placeholder="e.g. Retail banking" density="compact" hide-details class="mb-3" />
              <v-slider v-model="form.num_scenarios" label="Scenarios" min="1" max="5" step="1" thumb-label hide-details class="mb-3" />
              <v-radio-group v-model="form.grounding_mode" label="Grounding Mode" density="compact" hide-details class="mb-3">
                <v-radio label="Heuristic (Fast)" value="heuristic" />
                <v-radio label="Scientific (Accurate)" value="grounded" />
              </v-radio-group>
              <v-text-field v-model.number="form.inflation_factor" type="number" step="0.1" label="Inflation Factor" density="compact" hide-details class="mb-3" />
              <v-checkbox v-model="form.skip_ai_report" label="Skip AI Summary" density="compact" hide-details class="mb-3" />
              <div class="text-caption mb-1">Reports</div>
              <div class="d-flex" style="gap:8px">
                <v-checkbox v-model="form.report_formats" label="DOCX" value="docx" density="compact" hide-details />
                <v-checkbox v-model="form.report_formats" label="PDF" value="pdf" density="compact" hide-details />
                <v-checkbox v-model="form.report_formats" label="LaTeX" value="latex" density="compact" hide-details />
              </div>
            </v-card>
          </v-menu>
        </template>
      </v-card-title>

      <v-card-text class="pa-4">

        <!-- ══ MAIN LAYOUT ══════════════════════════════════ -->
        <div v-if="!simulating" class="d-flex" style="align-items: stretch; min-height: 480px; overflow: hidden;">

          <!-- ── Left column: library ─────────────────────────── -->
          <div style="flex: 0 0 320px; width: 320px; display: flex; flex-direction: column;">
            
            <input ref="fileInput" type="file" accept=".bpmn" class="d-none" @change="onFileSelected" />

          <template v-if="apiKeySet">
            <!-- Upload error -->
            <v-alert v-if="uploadError" type="error" variant="tonal" density="compact" class="mb-3 flex-shrink-0" closable @click:close="uploadError = ''">
              {{ uploadError }}
            </v-alert>

            <!-- Conflict resolution -->
            <v-card v-if="conflictInfo" variant="tonal" color="warning" class="mb-3 pa-3 flex-shrink-0" rounded="lg">
              <div class="text-subtitle-2 mb-2">
                <v-icon start size="16">mdi-alert-outline</v-icon>
                <strong>{{ conflictInfo.existing_name }}</strong> already exists
              </div>
              <v-radio-group v-model="conflictChoice" hide-details density="compact" class="mb-2">
                <v-radio value="replace" label="Replace existing" color="primary" />
                <v-radio value="rename" label="Save as new" color="primary" />
              </v-radio-group>
              <v-text-field v-if="conflictChoice === 'rename'" v-model="renameValue" density="compact" variant="outlined" label="New filename" suffix=".bpmn" hide-details class="mb-2" @click.stop />
              <div class="d-flex justify-end" style="gap:8px">
                <v-btn size="small" variant="text" @click.stop="conflictInfo = null; pendingConflictFile = null">Cancel</v-btn>
                <v-btn size="small" color="primary" variant="flat" @click.stop="resolveConflict">Apply</v-btn>
              </div>
            </v-card>
            
            <div v-if="uploading" class="d-flex align-center justify-center pa-2 mb-3 rounded border" style="border-color: rgba(128,128,128,0.2) !important; height: 40px;">
               <v-progress-circular indeterminate color="primary" size="20" width="2" class="mr-2" />
               <span class="text-body-2">Uploading...</span>
            </div>

            <!-- Divider with Add Diagram Link -->
            <div class="d-flex align-center mb-2 flex-shrink-0" style="gap: 8px">
              <span class="text-caption font-weight-medium text-medium-emphasis flex-shrink-0">
                <span class="text-primary font-weight-bold" style="text-decoration: underline; cursor: pointer;" @click="triggerFilePicker">Upload from device</span> or pick from library
              </span>
              <v-divider />
              <v-tooltip text="Refresh the library after adding or removing a BPMN file" location="top">
                <template #activator="{ props: tooltipProps }">
                  <v-btn
                    v-bind="tooltipProps"
                    icon="mdi-refresh"
                    size="x-small"
                    variant="text"
                    :loading="diagramLoading"
                    aria-label="Refresh BPMN library"
                    @click="fetchDiagrams"
                  />
                </template>
              </v-tooltip>
            </div>
          </template>
          <template v-else>
            <v-alert type="info" variant="tonal" class="mb-4 flex-shrink-0" density="compact">
              <div class="d-flex flex-column" style="gap: 10px">
                <div class="text-caption">Select a pre-loaded example below to run a simulation offline, or add a Gemini API Key to simulate custom processes.</div>
                <v-btn size="small" variant="outlined" color="info" @click="goToSettings">Set API Key</v-btn>
              </div>
            </v-alert>
            <div class="d-flex align-center mb-2 flex-shrink-0" style="gap: 8px">
              <span class="text-caption font-weight-medium text-medium-emphasis flex-shrink-0">Demo Examples</span>
              <v-divider />
            </div>
          </template>

          <!-- Library list -->
          <div v-if="diagrams.length === 0" class="text-center text-caption text-medium-emphasis py-4 flex-shrink-0">
            No models available.
          </div>
          <v-list v-else density="compact" class="library-list rounded-lg pa-0 flex-grow-1" style="overflow-y: auto; flex-basis: 0;">
            <v-list-item
              v-for="d in diagrams"
              :key="d.name"
              :value="d.name"
              :active="form.diagram_name === d.name && !uploadedName"
              color="primary"
              variant="flat"
              class="mb-1 rounded"
              @click="selectExisting(d)"
            >
              <template v-slot:prepend>
                <v-avatar size="28" rounded="sm" color="amber-lighten-4" class="mr-2">
                  <v-icon color="amber-darken-4" size="18">mdi-sitemap</v-icon>
                </v-avatar>
              </template>
              <v-list-item-title class="text-body-2 font-weight-bold">{{ d.process_name }}</v-list-item-title>
              <v-list-item-subtitle class="text-caption" style="font-size: 10px">{{ d.name }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
          </div><!-- /left column -->

          <!-- ── Right column: diagram preview ─────────────────────────── -->
          <div v-if="mdAndUp" :style="{ 
            flex: previewXml ? '1 1 0' : '0 0 0px',
            width: previewXml ? 'auto' : '0px',
            opacity: previewXml ? 1 : 0,
            marginLeft: previewXml ? '16px' : '0px',
            transition: 'flex 0.35s cubic-bezier(0.4, 0, 0.2, 1), width 0.35s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease, margin-left 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
            borderRadius: '8px',
            overflow: 'hidden',
            border: previewXml ? '1px solid rgba(128,128,128,0.2)' : 'none',
            position: 'relative'
          }" class="d-flex flex-column">
            <!-- Close Preview button -->
            <v-btn
              v-if="previewXml"
              icon="mdi-close"
              variant="flat"
              color="surface"
              size="small"
              class="position-absolute"
              style="top: 8px; right: 8px; z-index: 100; opacity: 0.8;"
              @click="unselectDiagram"
            />
            <div v-if="previewLoading || !renderDiagram" class="d-flex align-center justify-center flex-grow-1">
              <v-progress-circular indeterminate color="primary" size="24" />
            </div>
            
            <AureaEdenBpmnDiagram v-else-if="previewXml && renderDiagram" :bpmn-xml="previewXml" mode="VIEW" :theme="isDark ? 'DARK' : 'LIGHT'" style="flex: 1 1 auto; width:100%" />
          </div>

        </div><!-- /MAIN LAYOUT -->

        <!-- ══ RUNNING: Progress view ════════════════════════════════════ -->
        <div v-else class="py-2">

          <!-- Status header -->
          <div class="d-flex align-center justify-center mb-4 mt-2">
            <v-progress-circular v-if="status === 'running'" indeterminate color="primary" size="20" width="2" class="mr-3" />
            <v-icon v-else-if="status === 'done'" color="success" size="24" class="mr-3">mdi-check-circle</v-icon>
            <v-icon v-else-if="status === 'error'" color="error"   size="24" class="mr-3">mdi-alert-circle</v-icon>
            <h3 class="text-h6">{{ statusText }}</h3>
            <v-spacer />
            <v-chip size="small" variant="outlined" :color="status === 'error' ? 'error' : 'primary'" prepend-icon="mdi-timer-outline" class="ml-2 font-weight-bold">
              {{ formattedTime }}
            </v-chip>
          </div>

          <!-- Progress bar -->
          <div class="mb-1 d-flex justify-space-between text-caption text-medium-emphasis">
            <span>{{ currentStageName }}</span>
            <span>{{ Math.round(progress) }}%</span>
          </div>
          <v-progress-linear :model-value="progress" :color="status === 'error' ? 'error' : 'primary'" height="8" rounded class="mb-4" :striped="status === 'running'" />

          <!-- Stage dots -->
          <div class="d-flex align-center mb-4" style="gap: 4px; overflow: hidden">
            <div v-for="(stage, i) in STAGES" :key="i" class="flex-grow-1 rounded" style="height: 4px; transition: background 0.4s"
              :style="{ background: status === 'done' || i < currentStageIdx ? 'rgb(var(--v-theme-primary))' : i === currentStageIdx && status === 'running' ? 'rgba(var(--v-theme-primary), 0.4)' : 'rgba(128,128,128,0.2)' }"
            />
          </div>

          <!-- Terminal -->
          <v-sheet class="bg-grey-darken-4 rounded pa-3 text-left overflow-y-auto" height="240" id="terminal-log">
            <div v-for="(log, i) in logs" :key="i" class="mb-1" style="font-family: monospace; font-size: 10px; line-height: 1.4; white-space: pre-wrap" :class="logColor(log)">
              > {{ log }}
            </div>
          </v-sheet>
        </div>

      </v-card-text>

      <!-- ── Actions ────────────────────────────────────────────────── -->
      <v-card-actions class="pa-4 pt-0">
        <v-spacer />

        <!-- Running: close (background) -->
        <v-tooltip v-if="simulating && status === 'running'" text="The simulation will continue running in the background." location="top">
          <template v-slot:activator="{ props: tp }">
            <v-btn v-bind="tp" color="secondary" variant="text" @click="close">Close</v-btn>
          </template>
        </v-tooltip>

        <!-- Done/error: close -->
        <v-btn v-else-if="simulating" color="secondary" variant="text" @click="close">
          {{ status === 'done' ? 'Close' : 'Dismiss' }}
        </v-btn>

        <!-- Done: View Results -->
        <v-btn v-if="simulating && status === 'done'" color="primary" @click="viewResults">
          View Results
        </v-btn>

        <template v-if="!simulating">
          <v-spacer />
          <v-btn color="secondary" variant="text" @click="close">Cancel</v-btn>
          <v-btn color="primary" :disabled="apiKeySet ? !canProceed : !form.diagram_name" @click="apiKeySet ? startSimulation() : startOfflineDemo()">Run Simulation</v-btn>
        </template>
</v-card-actions>

    </v-card>
  </v-dialog>

  <!-- ── Floating Minimized Card ────────────────────────────────── -->
  <v-card
    v-if="minimized"
    elevation="10"
    class="minimized-card"
    border
    color="surface"
  >
    <div class="pa-3 d-flex align-center">
      <v-progress-circular v-if="status === 'running'" indeterminate color="primary" size="20" width="2" class="mr-3" />
      <v-icon v-else-if="status === 'done'" color="success" size="20" class="mr-3">mdi-check-circle</v-icon>
      <v-icon v-else-if="status === 'error'" color="error" size="20" class="mr-3">mdi-alert-circle</v-icon>
      
      <div class="flex-grow-1" style="min-width: 0;">
        <div class="text-subtitle-2 text-truncate">{{ statusText }}</div>
        <div class="text-caption text-medium-emphasis text-truncate">{{ currentStageName }}</div>
      </div>
      
      <v-chip size="x-small" variant="tonal" :color="status === 'error' ? 'error' : 'primary'" class="ml-2 font-weight-bold">
        {{ formattedTime }}
      </v-chip>
    </div>
    
    <v-progress-linear :model-value="progress" :color="status === 'error' ? 'error' : 'primary'" height="4" :striped="status === 'running'" />
    
    <div class="pa-2 d-flex justify-end" style="gap: 8px;">
      <v-btn v-if="status === 'done'" size="small" color="primary" @click="viewResults">View Results</v-btn>
      <v-btn v-else-if="status === 'error'" size="small" color="secondary" variant="text" @click="close">Dismiss</v-btn>
      <v-btn v-if="status === 'running'" size="small" variant="text" icon="mdi-window-maximize" @click="maximize" />
      <v-btn v-else size="small" variant="text" icon="mdi-close" @click="close" />
    </div>
  </v-card>
</template>

<script setup lang="ts">
const apiKeySet = ref(false)

import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTheme, useDisplay } from 'vuetify'
import AureaEdenBpmnDiagram from 'aurea-eden/vue'

function humanize(name: string): string {
  return name.replace(/[-_]/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/\b\w/g, c => c.toUpperCase())
}

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits(['update:modelValue', 'completed'])

const dialog = ref(props.modelValue)
const step   = ref<1 | 2>(1)
const minimized = ref(false)

function minimize() {
  minimized.value = true
  dialog.value = false
}

function maximize() {
  minimized.value = false
  dialog.value = true
}

watch(() => props.modelValue, (val) => {
  dialog.value = val
  if (val) {
    minimized.value = false
  }
  if (val && !simulating.value) {
    fetchSettings().then(() => {
      fetchDiagrams()
    })
    resetStep1()
  }
})
watch(dialog, (val) => emit('update:modelValue', val))

// ─── Pipeline Stages ──────────────────────────────────────────────────────────
const STAGES = computed(() => {
  const simSteps = Array.from({ length: form.value.num_scenarios }, (_, i) => ({
    label: `Simulating Scenario ${i + 1}/${form.value.num_scenarios}`,
    match: '[SIM] Simulating Scenario',
  }))
  return [
    { label: 'Initializing Workspace',      match: '[INIT]' },
    { label: 'Generating Project Identity', match: '[BRANDING]' },
    { label: 'AI: Base Parameters (1/2)',   match: 'Phase 1/2: Searching' },
    { label: 'AI: Base Parameters (2/2)',   match: 'Phase 2/2: Generating' },
    { label: 'AI: Scenarios (1/2)',         match: 'Phase 1/2: Searching for capacity' },
    { label: 'AI: Scenarios (2/2)',         match: 'Phase 2/2: Designing' },
    { label: 'Sanitizing BPMN Model',       match: '[SIM] Sanitizing' },
    ...simSteps,
    { label: 'Aggregating Simulation Data', match: '[REPORT] Aggregating' },
    { label: 'Resolving Citations',         match: '[REPORT] Resolving' },
    { label: 'AI: Executive Summary',       match: '[AI] Drafting' },
    { label: 'Compiling Reports',           match: '[REPORT] Compiling' },
  ]
})

// ─── Diagrams ─────────────────────────────────────────────────────────────────
interface Diagram { name: string; process_name: string; size_bytes: number }
const diagrams = ref<Diagram[]>([])
const diagramLoading = ref(false)

async function fetchDiagrams() {
  diagramLoading.value = true
  try {
    const endpoint = apiKeySet.value ? '/api/diagrams' : '/api/examples'
    const res = await fetch(endpoint)
    diagrams.value = await res.json()
  } catch { /* silent */ }
  finally { diagramLoading.value = false }
}

// ─── Theme ──────────────────────────────────────────────────────────────────
const theme  = useTheme()
const isDark = computed(() => theme.global.current.value.dark)
const showDiagramPreview = ref(false)

// ─── Step 1: upload & selection ───────────────────────────────────────────────
const fileInput        = ref<HTMLInputElement | null>(null)
const dragging         = ref(false)
const uploading        = ref(false)
const uploadedName     = ref('')     // saved filename after successful upload
const uploadedProcessName = ref('')  // friendly name of uploaded file
const uploadError      = ref('')

// Diagram preview
const previewXml     = ref('')
const previewLoading = ref(false)
const renderDiagram  = ref(false)

const { mdAndUp } = useDisplay()

const cardWidth = computed(() => {
  if (simulating.value) return '640px'
  if (previewXml.value && mdAndUp.value) return '1020px'
  return '360px'
})

watch(previewXml, (newXml) => {
  renderDiagram.value = false
  if (newXml) {
    setTimeout(() => {
      renderDiagram.value = true
    }, 400)
  }
})

async function fetchPreview(diagramName: string) {
  previewXml.value     = ''
  previewLoading.value = true
  try {
    const endpoint = apiKeySet.value ? `/api/diagrams/${encodeURIComponent(diagramName)}/xml` : `/api/examples/${encodeURIComponent(diagramName)}/xml`
    const res = await fetch(endpoint)
    if (res.ok) previewXml.value = await res.text()
  } catch { /* silent */ }
  finally { previewLoading.value = false }
}

// Conflict
interface ConflictData { existing_name: string; suggested_rename: string; options: string[] }
const conflictInfo        = ref<ConflictData | null>(null)
const pendingConflictFile = ref<File | null>(null)
const conflictChoice      = ref('rename')
const renameValue         = ref('')

// Form state (shared across steps)
const form = ref({ diagram_name: '', industry_context: 'General business process', num_scenarios: 3, demo_mode: false, grounding_mode: 'heuristic', inflation_factor: 1.0, skip_ai_report: false, report_formats: ['docx', 'pdf', 'latex'] })
const selectedProcessName = ref('')  // friendly name for existing-library pick

const canProceed = computed(() => !!uploadedName.value || !!form.value.diagram_name)

function triggerFilePicker() { if (!uploadedName.value) fileInput.value?.click() }
function onFileSelected(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) doUpload(file)
  ;(e.target as HTMLInputElement).value = ''
}
function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) doUpload(file)
}
function clearUpload() {
  uploadedName.value = ''
  uploadedProcessName.value = ''
  form.value.diagram_name = ''
  uploadError.value = ''
}

async function doUpload(file: File, resolution = '') {
  uploading.value = true
  uploadError.value = ''
  conflictInfo.value = null
  const fd = new FormData()
  fd.append('file', file)
  fd.append('resolution', resolution)
  try {
    const res = await fetch('/api/diagrams/upload', { method: 'POST', body: fd })
    const data = await res.json()
    if (!res.ok) { uploadError.value = data.detail ?? 'Upload failed.'; return }
    if (data.conflict) {
      pendingConflictFile.value = file
      conflictInfo.value = data
      conflictChoice.value = 'rename'
      renameValue.value = data.suggested_rename.replace(/\.bpmn$/, '')
      return
    }
    // Success — use as selected model
    uploadedName.value = data.saved_as
    form.value.diagram_name = data.saved_as
    await fetchDiagrams()
    const match = diagrams.value.find(d => d.name === data.saved_as)
    uploadedProcessName.value = match?.process_name ?? data.saved_as
    fetchPreview(data.saved_as)
  } catch { uploadError.value = 'Network error during upload.' }
  finally { uploading.value = false }
}

async function resolveConflict() {
  if (!pendingConflictFile.value) return
  const file = pendingConflictFile.value
  pendingConflictFile.value = null
  let resolution = conflictChoice.value
  if (conflictChoice.value === 'rename') {
    const n = renameValue.value.trim()
    resolution = `rename:${n.endsWith('.bpmn') ? n : n + '.bpmn'}`
  }
  conflictInfo.value = null
  await doUpload(file, resolution)
}

function selectExisting(d: Diagram) {
  if (form.value.diagram_name === d.name && !uploadedName.value) {
    unselectDiagram()
    return
  }
  uploadedName.value = ''
  uploadedProcessName.value = ''
  form.value.diagram_name = d.name
  selectedProcessName.value = d.process_name
  fetchPreview(d.name)
}

function resetStep1() {
  step.value = 1
  uploadedName.value = ''
  uploadedProcessName.value = ''
  uploadError.value = ''
  conflictInfo.value = null
  form.value.diagram_name = ''
  selectedProcessName.value = ''
  previewXml.value = ''
}

// ─── Simulation ───────────────────────────────────────────────────────────────
const error              = ref('')
const simulating         = ref(false)
const status             = ref('idle')
const logs               = ref<string[]>([])
const completedProjectName = ref('')
const completedProjectTitle = ref('')
const statusText         = ref('Preparing...')
const currentStageIdx    = ref(-1)
let eventSource: EventSource | null = null

const router = useRouter()

let timerInterval: ReturnType<typeof setInterval> | null = null
const elapsedSeconds = ref(0)
const formattedTime  = computed(() => {
  const m = Math.floor(elapsedSeconds.value / 60)
  const s = elapsedSeconds.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})
function startTimer() { elapsedSeconds.value = 0; timerInterval = setInterval(() => { elapsedSeconds.value++ }, 1000) }
function stopTimer()  { if (timerInterval) { clearInterval(timerInterval); timerInterval = null } }

const progress = computed(() => {
  const total = STAGES.value.length
  if (status.value === 'done') return 100
  if (currentStageIdx.value < 0) return 0
  return Math.round(((currentStageIdx.value + 1) / total) * 100)
})
const currentStageName = computed(() => {
  if (status.value === 'done') return 'All stages complete'
  if (currentStageIdx.value < 0) return 'Starting up...'
  return STAGES.value[currentStageIdx.value]?.label ?? 'Processing...'
})

function logColor(msg: string): string {
  if (msg.includes('[ERROR]') || msg.includes('[FATAL]')) return 'text-red-lighten-2'
  if (msg.includes('[WARNING]'))  return 'text-deep-orange-lighten-2'
  if (msg.includes('[DONE]'))     return 'text-amber-lighten-1'
  if (msg.includes('[AI]'))       return 'text-amber-lighten-2'
  if (msg.includes('[REPORT]'))   return 'text-orange-lighten-2'
  return 'text-grey-lighten-2'
}

function close() { dialog.value = false; setTimeout(reset, 500) }

function viewResults() {
  const name = completedProjectName.value
  if (name) router.push(`/projects/${encodeURIComponent(name)}`)
  close()
  emit('completed')
}


async function fetchSettings() {
  try {
    const res = await fetch('/api/settings')
    if (res.ok) {
      const data = await res.json()
      apiKeySet.value = data.api_key_set
    }
  } catch { /* silent */ }
}

function goToSettings() {
  close()
  router.push('/settings')
}

function reset() {
  simulating.value = false
  status.value = 'idle'
  logs.value = []
  error.value = ''
  currentStageIdx.value = -1
  completedProjectName.value = ''
  completedProjectTitle.value = ''
  minimized.value = false
  stopTimer()
  if (eventSource) { eventSource.close(); eventSource = null }
  resetStep1()
}

function scrollToBottom() {
  nextTick(() => { const el = document.getElementById('terminal-log'); if (el) el.scrollTop = el.scrollHeight })
}

function startOfflineDemo() {
  form.value.demo_mode = true
  startSimulation()
}

async function startSimulation() {
  error.value = ''
  simulating.value = true
  status.value = 'running'
  logs.value = []
  currentStageIdx.value = -1
  statusText.value = form.value.demo_mode ? 'Initializing Offline Demo...' : 'Contacting Backend...'
  startTimer()

  try {
    const res = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to start simulation') }

    const data = await res.json()
    statusText.value = 'Connecting to Stream...'
    eventSource = new EventSource(`/api/simulate/${data.task_id}/stream`)

    eventSource.onmessage = (e) => {
      const { msg, status: srvStatus } = JSON.parse(e.data)
      if (msg === '[EOF]') {
        status.value = srvStatus
        statusText.value = srvStatus === 'done' ? 'Simulation Complete!' : 'Simulation Failed'
        stopTimer(); eventSource?.close(); return
      }
      logs.value.push(msg)
      const stages = STAGES.value
      for (let i = stages.length - 1; i >= 0; i--) {
        if (msg.includes(stages[i].match) && i >= currentStageIdx.value) { currentStageIdx.value = i; break }
      }
      if (msg.includes('[BRANDING]'))          statusText.value = 'Generating Project Identity...'
      else if (msg.includes('[AI] Generating Base')) statusText.value = 'AI: Base Parameters...'
      else if (msg.includes('[AI] Innovating')) statusText.value = 'AI: Scenario Design...'
      else if (msg.includes('[SIM] Simulating')) statusText.value = 'Running Prosimos Engine...'
      else if (msg.includes('[REPORT] Aggregating')) statusText.value = 'Aggregating Results...'
      else if (msg.includes('[REPORT] Resolving'))   statusText.value = 'Resolving Citations...'
      else if (msg.includes('[AI] Drafting'))         statusText.value = 'AI: Executive Summary...'
      else if (msg.includes('[REPORT] Compiling'))    statusText.value = 'Compiling Reports...'
      else if (msg.includes('[DONE]')) {
        const m = msg.match(/project=(.+?)(?: display_name=(.+?))? Headless/)
        if (m) {
          completedProjectName.value = m[1]
          completedProjectTitle.value = m[2] || ''
        }
      } else if (msg.includes('[FATAL]') || msg.includes('[ERROR]')) {
        status.value = 'error'; statusText.value = 'Simulation Failed'; stopTimer()
      }
      scrollToBottom()
    }
    eventSource.onerror = () => {
      if (status.value === 'running') logs.value.push('[SYSTEM] Connection to server lost. Checking status...')
    }
  } catch (err: any) {
    simulating.value = false; status.value = 'error'; error.value = err.message; stopTimer()
  }
}

function unselectDiagram() {
  uploadedName.value = ''
  uploadedProcessName.value = ''
  form.value.diagram_name = ''
  selectedProcessName.value = ''
  previewXml.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (dialog.value && e.key === 'Escape' && previewXml.value) {
    unselectDiagram()
    e.stopPropagation()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.step-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: rgba(0,0,0,0.25);
  transition: background 0.3s;
}
.step-dot.active { background: rgba(0,0,0,0.75); }
.step-dot.done   { background: rgba(0,0,0,0.5); }

/* Diagram preview slide-in */
.slide-preview-enter-active,
.slide-preview-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.slide-preview-enter-from,
.slide-preview-leave-to {
  opacity: 0;
  transform: translateX(16px);
}

.upload-zone {

  border: 2px dashed rgba(var(--v-theme-primary), 0.4);
  transition: border-color 0.2s, background 0.2s;
  min-height: 140px;
}
.upload-zone--active {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.06);
}
.upload-zone--selected {
  border-style: solid;
  border-color: rgb(var(--v-theme-success));
  background: rgba(var(--v-theme-success), 0.05);
  cursor: default;
}

.library-list { border: 1px solid rgba(128,128,128,0.15); }

.minimized-card {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 340px;
  z-index: 9999;
  border-radius: 8px;
}
</style>
