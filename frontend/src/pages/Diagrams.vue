<template>
  <v-container max-width="960" class="py-8">

    <!-- Header -->
    <div class="d-flex align-center mb-6" style="gap: 16px">
      <div>
        <h1 class="text-h4 font-weight-bold">Process Models</h1>
        <p class="text-body-2 text-medium-emphasis mt-1">
          Upload and manage BPMN files used for simulation. Models are stored permanently and reusable across projects.
        </p>
      </div>
    </div>

    <!-- Upload Zone -->
    <v-card
      class="mb-6 upload-zone"
      :class="{ 'upload-zone--active': dragging }"
      variant="outlined"
      rounded="lg"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <div class="d-flex flex-column align-center justify-center pa-10" style="gap: 12px">
        <v-icon size="48" color="primary" :class="{ 'upload-bounce': dragging }">mdi-upload-outline</v-icon>
        <div class="text-center">
          <div class="text-subtitle-1 font-weight-medium">Drag &amp; drop a BPMN file here</div>
          <div class="text-body-2 text-medium-emphasis">or</div>
        </div>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-folder-open-outline" @click="triggerFilePicker">
          Browse File
        </v-btn>
        <div class="text-caption text-medium-emphasis">Only .bpmn files are accepted</div>
        <input ref="fileInput" type="file" accept=".bpmn" class="d-none" @change="onFileSelected" />
      </div>
    </v-card>

    <!-- Upload error -->
    <v-alert v-if="uploadError" type="error" variant="tonal" class="mb-4" closable @click:close="uploadError = ''">
      {{ uploadError }}
    </v-alert>

    <!-- Upload success -->
    <v-alert v-if="uploadSuccess" type="success" variant="tonal" class="mb-4" closable @click:close="uploadSuccess = ''">
      {{ uploadSuccess }}
    </v-alert>

    <!-- Model Library Table -->
    <v-card rounded="lg" variant="outlined">
      <v-card-title class="pa-4 pb-2 text-subtitle-1 font-weight-bold">
        <v-icon start>mdi-file-tree</v-icon>
        Library
        <v-chip size="x-small" class="ml-2" color="primary" variant="tonal">{{ diagrams.length }}</v-chip>
        <v-spacer />
        <v-btn icon size="small" variant="text" @click="fetchDiagrams" :loading="loading">
          <v-icon>mdi-refresh</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider />

      <div v-if="loading" class="pa-8 text-center">
        <v-progress-circular indeterminate color="primary" />
      </div>

      <v-alert v-else-if="diagrams.length === 0" type="info" variant="tonal" class="ma-4">
        No BPMN models found. Upload one above to get started.
      </v-alert>

      <v-table v-else hover style="table-layout: fixed; width: 100%">
        <colgroup>
          <col style="width: 32%" />
          <col style="width: 33%" />
          <col style="width: 11%" />
          <col style="width: 13%" />
          <col style="width: 11%" />
        </colgroup>
        <thead>
          <tr>
            <th class="text-left">Process Name</th>
            <th class="text-left">File</th>
            <th class="text-right">Size</th>
            <th class="text-right">Added</th>
            <th class="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in diagrams" :key="d.name">
            <td class="py-3 cell-nowrap">
              <div class="d-flex align-center" style="gap: 10px; min-width: 0">
                <v-icon color="primary" size="20" style="flex-shrink: 0">mdi-file-xml-box</v-icon>
                <v-tooltip :text="d.process_name" location="top">
                  <template v-slot:activator="{ props }">
                    <span v-bind="props" class="font-weight-medium text-truncate">{{ d.process_name }}</span>
                  </template>
                </v-tooltip>
              </div>
            </td>
            <td class="cell-nowrap text-body-2 text-medium-emphasis">
              <v-tooltip :text="d.name" location="top">
                <template v-slot:activator="{ props }">
                  <span v-bind="props" class="text-truncate d-block">{{ d.name }}</span>
                </template>
              </v-tooltip>
            </td>
            <td class="text-right text-body-2 cell-nowrap">{{ formatSize(d.size_bytes) }}</td>
            <td class="text-right text-body-2 text-medium-emphasis cell-nowrap">{{ formatDate(d.created_at) }}</td>
            <td class="text-right cell-nowrap">
              <v-tooltip
                v-if="pendingDelete === d.name"
                text="Click again to confirm deletion"
                location="top"
              >
                <template v-slot:activator="{ props }">
                  <v-btn
                    v-bind="props"
                    size="small"
                    color="error"
                    variant="tonal"
                    prepend-icon="mdi-check"
                    class="mr-1"
                    @click="confirmDelete(d.name)"
                  >Confirm</v-btn>
                </template>
              </v-tooltip>
              <v-btn
                v-if="pendingDelete === d.name"
                size="small"
                variant="text"
                @click="pendingDelete = ''"
              >Cancel</v-btn>
              <v-btn
                v-else
                size="small"
                icon
                variant="text"
                color="error"
                @click="requestDelete(d.name)"
              >
                <v-icon>mdi-delete-outline</v-icon>
              </v-btn>
            </td>
          </tr>
        </tbody>
      </v-table>
    </v-card>

    <!-- Conflict Resolution Dialog -->
    <v-dialog v-model="conflictDialog" max-width="480" persistent>
      <v-card rounded="lg">
        <v-card-title class="pa-4 bg-warning-darken-2">
          <v-icon start color="white">mdi-alert-outline</v-icon>
          <span style="color: white">File Already Exists</span>
        </v-card-title>
        <v-card-text class="pa-5">
          <p class="mb-4">
            A file named <strong>{{ conflictInfo.existing_name }}</strong> already exists in the library.
            How would you like to proceed?
          </p>

          <v-radio-group v-model="conflictChoice" hide-details>
            <v-radio value="replace" label="Replace — overwrite the existing file" color="primary" />
            <v-radio value="rename" label="Rename — save under a new name" color="primary" />
            <v-radio value="cancel" label="Cancel — discard this upload" color="primary" />
          </v-radio-group>

          <v-text-field
            v-if="conflictChoice === 'rename'"
            v-model="renameValue"
            label="New filename"
            suffix=".bpmn"
            class="mt-4"
            density="compact"
            variant="outlined"
            hide-details
          />
        </v-card-text>
        <v-card-actions class="pa-4 pt-0">
          <v-spacer />
          <v-btn variant="text" @click="resolveConflict('cancel')">Cancel</v-btn>
          <v-btn
            color="primary"
            variant="flat"
            :disabled="conflictChoice === 'rename' && !renameValue.trim()"
            @click="resolveConflict(conflictChoice)"
          >Apply</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Blocked Dialog -->
    <v-dialog v-model="deleteBlockedDialog" max-width="480">
      <v-card rounded="lg">
        <v-card-title class="pa-4">Cannot Delete Model</v-card-title>
        <v-card-text class="pa-5">
          <p class="mb-3">This model is referenced by the following projects and cannot be deleted:</p>
          <v-list density="compact" class="bg-surface-variant rounded">
            <v-list-item
              v-for="p in blockingProjects"
              :key="p"
              prepend-icon="mdi-folder"
              :title="p"
            />
          </v-list>
        </v-card-text>
        <v-card-actions class="pa-4 pt-0">
          <v-spacer />
          <v-btn color="primary" variant="tonal" @click="deleteBlockedDialog = false">OK</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

  </v-container>
</template>

<script lang="ts" setup>
import { ref, onMounted } from 'vue'

interface Diagram {
  name: string
  process_name: string
  size_bytes: number
  created_at: number
}

interface ConflictInfo {
  existing_name: string
  suggested_rename: string
  options: string[]
}

// ─── State ──────────────────────────────────────────────────────────────────

const diagrams    = ref<Diagram[]>([])
const loading     = ref(true)
const dragging    = ref(false)
const uploadError = ref('')
const uploadSuccess = ref('')
const fileInput   = ref<HTMLInputElement | null>(null)

// Conflict dialog
const conflictDialog  = ref(false)
const conflictInfo    = ref<ConflictInfo>({ existing_name: '', suggested_rename: '', options: [] })
const conflictChoice  = ref('rename')
const renameValue     = ref('')
let   pendingFile: File | null = null

// Delete state
const pendingDelete       = ref('')
const deleteBlockedDialog = ref(false)
const blockingProjects    = ref<string[]>([])

// ─── Lifecycle ───────────────────────────────────────────────────────────────

onMounted(fetchDiagrams)

// ─── API ─────────────────────────────────────────────────────────────────────

async function fetchDiagrams() {
  loading.value = true
  try {
    const res = await fetch('/api/diagrams')
    diagrams.value = await res.json()
  } catch {
    uploadError.value = 'Failed to load model library.'
  } finally {
    loading.value = false
  }
}

async function doUpload(file: File, resolution = '') {
  uploadError.value = ''
  uploadSuccess.value = ''
  const form = new FormData()
  form.append('file', file)
  form.append('resolution', resolution)

  const res = await fetch('/api/diagrams/upload', { method: 'POST', body: form })
  const data = await res.json()

  if (!res.ok) {
    uploadError.value = data.detail ?? 'Upload failed.'
    return
  }

  if (data.conflict) {
    pendingFile = file
    conflictInfo.value = data
    conflictChoice.value = 'rename'
    renameValue.value = data.suggested_rename.replace(/\.bpmn$/, '')
    conflictDialog.value = true
    return
  }

  uploadSuccess.value = `"${data.saved_as}" uploaded successfully.`
  fetchDiagrams()
}

async function resolveConflict(choice: string) {
  conflictDialog.value = false
  if (choice === 'cancel' || !pendingFile) { pendingFile = null; return }

  let resolution = choice
  if (choice === 'rename') {
    const name = renameValue.value.trim()
    resolution = `rename:${name.endsWith('.bpmn') ? name : name + '.bpmn'}`
  }

  const file = pendingFile
  pendingFile = null
  await doUpload(file, resolution)
}

async function requestDelete(name: string) {
  pendingDelete.value = name
}

async function confirmDelete(name: string) {
  pendingDelete.value = ''
  const res = await fetch(`/api/diagrams/${encodeURIComponent(name)}`, { method: 'DELETE' })
  const data = await res.json()

  if (res.status === 409) {
    blockingProjects.value = data.detail?.blocking_projects ?? []
    deleteBlockedDialog.value = true
    return
  }
  if (!res.ok) {
    uploadError.value = data.detail ?? 'Delete failed.'
    return
  }
  uploadSuccess.value = `"${name}" removed from library.`
  fetchDiagrams()
}

// ─── File picking ─────────────────────────────────────────────────────────────

function triggerFilePicker() {
  fileInput.value?.click()
}

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

// ─── Formatting ──────────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.upload-zone {
  border: 2px dashed rgba(var(--v-theme-primary), 0.35);
  transition: border-color 0.2s, background 0.2s;
  cursor: pointer;
}
.upload-zone--active {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.06);
}
.upload-bounce {
  animation: bounce 0.5s ease infinite alternate;
}
@keyframes bounce {
  from { transform: translateY(0); }
  to   { transform: translateY(-6px); }
}
.cell-nowrap {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 0;        /* forces ellipsis to respect column width in fixed-layout table */
}
</style>
