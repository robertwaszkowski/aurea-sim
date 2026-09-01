<template>
  <v-container>
    <v-row align="center" class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-2">Projects</h1>
        <p class="text-body-1 text-medium-emphasis">
          Browse completed simulation experiments.
        </p>
      </v-col>
      <v-col cols="auto">
        <v-menu>
          <template v-slot:activator="{ props }">
            <v-btn
              variant="outlined"
              v-bind="props"
              prepend-icon="mdi-sort"
              density="comfortable"
            >
              Sort: {{ sortLabel }}
            </v-btn>
          </template>
          <v-list density="compact">
            <v-list-item @click="sortBy = 'date'">
              <v-list-item-title>Newest First</v-list-item-title>
            </v-list-item>
            <v-list-item @click="sortBy = 'name'">
              <v-list-item-title>Name (A-Z)</v-list-item-title>
            </v-list-item>
          </v-list>
        </v-menu>
      </v-col>
    </v-row>

    <v-row v-if="loading">
      <v-col cols="12" class="text-center">
        <v-progress-circular indeterminate />
      </v-col>
    </v-row>

    <v-row v-else-if="sortedProjects.length === 0">
      <v-col>
        <v-alert type="info" variant="tonal">
          No projects found. Run the AureaSim wizard to generate your first simulation.
        </v-alert>
      </v-col>
    </v-row>

    <v-row v-else>
      <v-col cols="12">
        <v-card variant="flat" border>
          <v-list lines="two">
            <template v-for="(project, index) in sortedProjects" :key="project.name">
              <v-list-item
                :to="`/projects/${project.name}`"
                link
              >
                <template v-slot:prepend>
                  <v-avatar :color="`${getProjectColor(project)}-lighten-5`" size="48">
                    <v-icon :color="`${getProjectColor(project)}-darken-1`" size="24" :icon="getProjectIcon(project)" />
                  </v-avatar>
                </template>

                <v-list-item-title class="font-weight-bold d-flex align-center gap-2">
                  {{ project.display_name }}
                  <span
                    v-if="runNumber(project.name)"
                    class="text-caption text-medium-emphasis font-weight-regular ml-1"
                  >#{{ runNumber(project.name) }}</span>
                </v-list-item-title>
                
                <v-list-item-subtitle>
                  <span class="text-medium-emphasis">{{ formatDate(project.created_at) }}</span>
                  <span class="mx-2 text-disabled">•</span>
                  <v-icon size="x-small" class="mr-1" color="medium-emphasis">mdi-folder-outline</v-icon>
                  <span class="text-caption">{{ project.name }}</span>
                </v-list-item-subtitle>

                <template v-slot:append>
                  <div class="d-none d-md-flex align-center">
                    <v-chip
                      v-if="project.has_kpis"
                      size="x-small"
                      color="success"
                      variant="flat"
                      class="mr-1"
                    >
                      KPIs
                    </v-chip>
                    <v-chip
                      v-if="project.has_chart"
                      size="x-small"
                      color="info"
                      variant="flat"
                      class="mr-1"
                    >
                      Chart
                    </v-chip>
                    <v-chip
                      v-for="report in project.reports"
                      :key="report"
                      size="x-small"
                      variant="outlined"
                      class="mr-1"
                    >
                      {{ report.split('.').pop()?.toUpperCase() }}
                    </v-chip>
                    <div class="ml-4 text-caption text-medium-emphasis" style="min-width: 80px">
                      {{ project.scenario_count }} scenario{{ project.scenario_count !== 1 ? 's' : '' }}
                    </div>
                  </div>
                  <v-icon class="ml-4" color="medium-emphasis">mdi-chevron-right</v-icon>
                </template>
              </v-list-item>
              <v-divider v-if="index < sortedProjects.length - 1" inset></v-divider>
            </template>
          </v-list>
        </v-card>
      </v-col>
    </v-row>

    <!-- No FAB here as it is moved to Navigation Drawer (optional, but requested there) -->
  </v-container>
</template>

<script lang="ts" setup>
  import { ref, computed, onMounted, onUnmounted } from 'vue'

  interface Project {
    name: string
    display_name: string
    created_at: number
    icon?: string
    color?: string
    has_kpis: boolean
    has_chart: boolean
    reports: string[]
    scenario_count: number
  }

  const projects = ref<Project[]>([])
  const loading = ref(true)
  const sortBy = ref<'name' | 'date'>('date')

  const sortLabel = computed(() => {
    return sortBy.value === 'date' ? 'Newest' : 'Name'
  })

  const sortedProjects = computed(() => {
    return [...projects.value].sort((a, b) => {
      if (sortBy.value === 'date') {
        return b.created_at - a.created_at
      }
      return a.name.localeCompare(b.name)
    })
  })

  function humanize (name: string): string {
    return name
      .replace(/[-_]/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\b\w/g, c => c.toUpperCase())
  }

  function runNumber (folderName: string): string | null {
    const match = folderName.match(/-(\d+)$/)
    return match ? match[1] : null
  }

  function formatDate (timestamp: number): string {
    return new Date(timestamp * 1000).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function getProjectIcon (project: Project): string {
    if (project.icon) return project.icon
    
    const n = project.name.toLowerCase()
    if (n.includes('sales')) return 'mdi-currency-usd'
    if (n.includes('employment') || n.includes('dismissal') || n.includes('hr') || n.includes('kadrowa')) return 'mdi-account-group-outline'
    if (n.includes('installation')) return 'mdi-wrench-outline'
    
    // Fallback based on name hash
    const icons = ['mdi-chart-timeline-variant', 'mdi-chart-line', 'mdi-database-outline', 'mdi-pulse', 'mdi-flask-outline']
    let hash = 0
    for (let i = 0; i < project.name.length; i++) hash = project.name.charCodeAt(i) + ((hash << 5) - hash)
    return icons[Math.abs(hash) % icons.length]
  }

  function getProjectColor (project: Project): string {
    if (project.color) return project.color
    
    const n = project.name.toLowerCase()
    if (n.includes('sales')) return 'green'
    if (n.includes('employment') || n.includes('dismissal') || n.includes('hr') || n.includes('kadrowa')) return 'blue'
    if (n.includes('installation')) return 'orange'
    
    const colors = ['indigo', 'purple', 'teal', 'cyan', 'deep-purple']
    let hash = 0
    for (let i = 0; i < project.name.length; i++) hash = project.name.charCodeAt(i) + ((hash << 5) - hash)
    return colors[Math.abs(hash) % colors.length]
  }

  async function fetchProjects() {
    try {
      const res = await fetch('/api/projects')
      projects.value = await res.json()
    } catch (e) {
      console.error('Failed to load projects:', e)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    fetchProjects()
    window.addEventListener('project-created', fetchProjects)
  })

  onUnmounted(() => {
    window.removeEventListener('project-created', fetchProjects)
  })
</script>
