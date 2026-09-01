<template>
  <div>
    <!-- Loading -->
    <div v-if="loading" class="text-center py-12">
      <v-progress-circular indeterminate color="primary" />
    </div>

    <!-- Error -->
    <v-alert v-else-if="error" type="warning" variant="tonal" class="mb-4">
      {{ error }}
    </v-alert>

    <template v-else-if="data">

      <!-- Scenario selector -->
      <div class="d-flex align-center mb-6" style="gap: 12px; flex-wrap: wrap">
        <span class="text-body-2 text-medium-emphasis font-weight-medium">Scenario:</span>
        <v-btn-toggle v-model="activeScenario" color="primary" variant="outlined" density="compact" mandatory>
          <v-btn
            v-for="sc in data.scenarios"
            :key="sc.scenario"
            :value="sc.scenario"
            size="small"
          >{{ humanizeScenario(sc.scenario) }}</v-btn>
        </v-btn-toggle>
      </div>

      <template v-if="current">

        <!-- ── KPI summary strip ─────────────────────────────────────────── -->
        <v-row class="mb-4">
          <v-col cols="6" sm="3">
            <v-card variant="tonal" color="primary" rounded="lg" class="pa-4 text-center">
              <div class="text-caption text-uppercase mb-1" style="letter-spacing:.08em">Avg Cycle Time</div>
              <div class="text-h5 font-weight-bold">{{ formatDuration(current.cycle_times.avg_hours * 3600) }}</div>
            </v-card>
          </v-col>
          <v-col cols="6" sm="3">
            <v-card variant="tonal" color="secondary" rounded="lg" class="pa-4 text-center">
              <div class="text-caption text-uppercase mb-1" style="letter-spacing:.08em">Min Cycle</div>
              <div class="text-h5 font-weight-bold">{{ formatDuration(current.cycle_times.min_hours * 3600) }}</div>
            </v-card>
          </v-col>
          <v-col cols="6" sm="3">
            <v-card variant="tonal" color="secondary" rounded="lg" class="pa-4 text-center">
              <div class="text-caption text-uppercase mb-1" style="letter-spacing:.08em">Max Cycle</div>
              <div class="text-h5 font-weight-bold">{{ formatDuration(current.cycle_times.max_hours * 3600) }}</div>
            </v-card>
          </v-col>
          <v-col cols="6" sm="3">
            <v-card variant="tonal" rounded="lg" class="pa-4 text-center">
              <div class="text-caption text-uppercase mb-1" style="letter-spacing:.08em">Activities</div>
              <div class="text-h5 font-weight-bold">{{ current.activities.length }}</div>
            </v-card>
          </v-col>
        </v-row>

        <!-- ── Activity breakdown ────────────────────────────────────────── -->
        <v-card border variant="flat" class="mb-6" rounded="lg">
          <v-card-item>
            <v-card-title>Activity Breakdown</v-card-title>
            <v-card-subtitle>Processing time and waiting time per activity — sorted by bottleneck impact</v-card-subtitle>
          </v-card-item>
          <v-card-text class="pa-0">
            <div class="px-4 pb-4" style="overflow-x: auto">
              <!-- Horizontal stacked bar chart -->
              <div
                v-for="act in activitiesByWait"
                :key="act.activity"
                class="mb-3"
              >
                <div class="d-flex justify-space-between align-center mb-1" style="gap: 8px">
                  <span class="text-body-2 font-weight-medium act-label">{{ act.activity }}</span>
                  <span class="text-caption text-medium-emphasis flex-shrink-0">
                    {{ formatDuration(act.avg_processing_s) }} process · {{ formatDuration(act.avg_wait_s) }} wait
                  </span>
                </div>
                <div class="bar-track rounded">
                  <div
                    class="bar-process rounded-s"
                    :style="{ width: processWidth(act) + '%' }"
                  />
                  <div
                    class="bar-wait"
                    :style="{ width: waitWidth(act) + '%' }"
                    :class="act.avg_wait_s > highWaitThreshold ? 'bar-wait--alert' : ''"
                  />
                </div>
              </div>
              <!-- Legend -->
              <div class="d-flex align-center mt-3" style="gap: 16px">
                <div class="d-flex align-center" style="gap: 6px">
                  <div style="width:12px;height:12px;border-radius:3px;background:rgb(var(--v-theme-primary))" />
                  <span class="text-caption">Processing time</span>
                </div>
                <div class="d-flex align-center" style="gap: 6px">
                  <div style="width:12px;height:12px;border-radius:3px;background:rgba(var(--v-theme-error),0.7)" />
                  <span class="text-caption">Wait time (bottleneck)</span>
                </div>
                <div class="d-flex align-center" style="gap: 6px">
                  <div style="width:12px;height:12px;border-radius:3px;background:rgba(var(--v-theme-primary),0.25)" />
                  <span class="text-caption">Wait time (normal)</span>
                </div>
              </div>
            </div>

            <v-divider />

            <!-- Detailed table -->
            <v-table density="comfortable" hover>
              <thead>
                <tr>
                  <th class="text-left">Activity</th>
                  <th class="text-right">Count</th>
                  <th class="text-right">Avg Process</th>
                  <th class="text-right">Min Process</th>
                  <th class="text-right">Max Process</th>
                  <th class="text-right">Avg Wait</th>
                  <th class="text-right">Max Wait</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="act in activitiesByWait" :key="act.activity">
                  <td class="text-body-2 font-weight-medium">{{ act.activity }}</td>
                  <td class="text-right text-body-2">{{ act.count }}</td>
                  <td class="text-right text-body-2">{{ formatDuration(act.avg_processing_s) }}</td>
                  <td class="text-right text-body-2 text-medium-emphasis">{{ formatDuration(act.min_processing_s) }}</td>
                  <td class="text-right text-body-2 text-medium-emphasis">{{ formatDuration(act.max_processing_s) }}</td>
                  <td class="text-right text-body-2" :class="act.avg_wait_s > highWaitThreshold ? 'text-error font-weight-bold' : ''">
                    {{ formatDuration(act.avg_wait_s) }}
                  </td>
                  <td class="text-right text-body-2 text-medium-emphasis">{{ formatDuration(act.max_wait_s) }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>

        <!-- ── Resource utilisation ──────────────────────────────────────── -->
        <v-card border variant="flat" class="mb-6" rounded="lg">
          <v-card-item>
            <v-card-title>Resource Utilisation</v-card-title>
            <v-card-subtitle>Busy time as a percentage of total simulation span</v-card-subtitle>
          </v-card-item>
          <v-card-text>
            <div
              v-for="res in current.resources"
              :key="res.resource"
              class="mb-4"
            >
              <div class="d-flex justify-space-between align-center mb-1">
                <span class="text-body-2 font-weight-medium">{{ res.resource }}</span>
                <span class="text-body-2 font-weight-bold" :class="utilColour(res.utilisation_pct)">
                  {{ res.utilisation_pct }}% · {{ res.busy_hours }}h busy
                </span>
              </div>
              <v-progress-linear
                :model-value="res.utilisation_pct"
                :color="utilColour(res.utilisation_pct)"
                height="10"
                rounded
                bg-color="surface-variant"
              />
            </div>
          </v-card-text>
        </v-card>

        <!-- ── Cycle time histogram ──────────────────────────────────────── -->
        <v-card border variant="flat" rounded="lg">
          <v-card-item>
            <v-card-title>Case Cycle Time Distribution</v-card-title>
            <v-card-subtitle>How many cases completed within each duration bucket</v-card-subtitle>
          </v-card-item>
          <v-card-text>
            <div class="histogram-wrap">
              <div
                v-for="(bucket, i) in current.cycle_times.histogram"
                :key="i"
                class="hist-col"
                :title="`${bucket.label}: ${bucket.count} cases`"
              >
                <div class="hist-count text-caption text-medium-emphasis">{{ bucket.count }}</div>
                <div class="hist-bar-bg">
                  <div
                    class="hist-bar"
                    :style="{ height: histBarHeight(bucket.count) + '%' }"
                  />
                </div>
                <div class="hist-label text-caption text-medium-emphasis">{{ bucket.label }}</div>
              </div>
            </div>
          </v-card-text>
        </v-card>

      </template>
    </template>
  </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, watch } from 'vue'

const props = defineProps<{ projectName: string }>()

// ─── Data ─────────────────────────────────────────────────────────────────────
interface Activity {
  activity: string
  count: number
  avg_processing_s: number
  min_processing_s: number
  max_processing_s: number
  avg_wait_s: number
  max_wait_s: number
}
interface Resource {
  resource: string
  busy_hours: number
  utilisation_pct: number
}
interface Scenario {
  scenario: string
  activities: Activity[]
  resources: Resource[]
  cycle_times: {
    avg_hours: number
    min_hours: number
    max_hours: number
    histogram: { label: string; count: number }[]
  }
}
interface Analytics { scenarios: Scenario[] }

const data    = ref<Analytics | null>(null)
const loading = ref(true)
const error   = ref('')
const activeScenario = ref('')

onMounted(fetchData)
watch(() => props.projectName, fetchData)

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(props.projectName)}/analytics`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    data.value = await res.json()
    if (data.value!.scenarios.length) activeScenario.value = data.value!.scenarios[0].scenario
  } catch (e: any) {
    error.value = 'Could not load analytics. Make sure simulation logs are available.'
  } finally {
    loading.value = false
  }
}

// ─── Derived ─────────────────────────────────────────────────────────────────
const current = computed<Scenario | undefined>(() =>
  data.value?.scenarios.find(s => s.scenario === activeScenario.value)
)

const activitiesByWait = computed(() =>
  [...(current.value?.activities ?? [])].sort((a, b) => b.avg_wait_s - a.avg_wait_s)
)

const highWaitThreshold = computed(() => {
  const waits = activitiesByWait.value.map(a => a.avg_wait_s)
  if (!waits.length) return Infinity
  const avg = waits.reduce((s, v) => s + v, 0) / waits.length
  return avg  // activities above avg wait are highlighted
})

const maxBarTotal = computed(() => {
  if (!data.value?.scenarios) return 1
  let maxVal = 1
  for (const s of data.value.scenarios) {
    for (const a of s.activities ?? []) {
      const total = a.avg_processing_s + a.avg_wait_s
      if (total > maxVal) {
        maxVal = total
      }
    }
  }
  return maxVal
})

function processWidth(act: Activity): number {
  return Math.round((act.avg_processing_s / maxBarTotal.value) * 100)
}
function waitWidth(act: Activity): number {
  return Math.round((act.avg_wait_s / maxBarTotal.value) * 100)
}

const maxHistCount = computed(() =>
  Math.max(...(current.value?.cycle_times.histogram ?? []).map(b => b.count), 1)
)
function histBarHeight(count: number): number {
  return Math.round((count / maxHistCount.value) * 100)
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}

function utilColour(pct: number): string {
  if (pct >= 90) return 'error'
  if (pct >= 70) return 'warning'
  return 'success'
}

function humanizeScenario(name: string): string {
  return name.replace(/_/g, ' ')
}
</script>

<style scoped>
.act-label {
  max-width: 380px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Stacked bar */
.bar-track {
  display: flex;
  height: 12px;
  background: rgba(128,128,128,0.12);
  overflow: hidden;
}
.bar-process {
  background: rgb(var(--v-theme-primary));
  flex-shrink: 0;
  transition: width 0.4s ease;
}
.bar-wait {
  background: rgba(var(--v-theme-primary), 0.25);
  flex-shrink: 0;
  transition: width 0.4s ease;
}
.bar-wait--alert {
  background: rgba(var(--v-theme-error), 0.7);
}

/* Histogram */
.histogram-wrap {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 160px;
  padding-bottom: 24px;
  position: relative;
}
.hist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}
.hist-count {
  font-size: 10px;
  margin-bottom: 2px;
}
.hist-bar-bg {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
}
.hist-bar {
  width: 100%;
  background: rgb(var(--v-theme-primary));
  opacity: 0.8;
  border-radius: 3px 3px 0 0;
  transition: height 0.4s ease;
  min-height: 2px;
}
.hist-label {
  font-size: 9px;
  margin-top: 4px;
  text-align: center;
  line-height: 1.2;
}
</style>
