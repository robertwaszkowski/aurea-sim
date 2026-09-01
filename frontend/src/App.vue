<template>
  <v-app>
    <v-app-bar elevation="1">
      <v-app-bar-nav-icon @click="drawer = !drawer" />
      <router-link to="/" class="d-flex align-center ml-1" style="gap: 10px; text-decoration: none; color: inherit; cursor: pointer;">
        <img src="/aurea-sim-logo.svg" alt="AureaSim logo" height="28" style="display:block" />
        <span class="text-h6 font-weight-bold text-primary" style="letter-spacing: -0.5px">AureaSim</span>
      </router-link>
      <v-spacer />
      <v-btn icon @click="toggleTheme">
        <v-icon>{{ themeIcon }}</v-icon>
      </v-btn>
    </v-app-bar>

    <v-navigation-drawer v-model="drawer" width="280">
      <div class="px-4 pt-5 pb-4">
        <v-btn
          rounded="xl"
          elevation="4"
          height="52"
          block
          class="text-none"
          color="primary"
          variant="flat"
          @click="showNewProjectDialog = true"
        >
          <v-icon start size="22">mdi-rocket-launch-outline</v-icon>
          <span class="text-subtitle-2 font-weight-bold">Run Simulation</span>
        </v-btn>
      </div>
      <v-divider class="mx-3 mb-2" />

      <v-list nav density="compact" class="px-3">
        <v-list-item
          prepend-icon="mdi-view-dashboard"
          title="Projects"
          to="/"
          class="rounded-pill"
          color="primary"
        />
        <v-list-item
          prepend-icon="mdi-file-tree"
          title="Process Models"
          to="/diagrams"
          class="rounded-pill"
          color="primary"
        />
        <v-list-item
          prepend-icon="mdi-cog"
          title="Settings"
          to="/settings"
          class="rounded-pill"
          color="primary"
        />
      </v-list>

      <!-- Version footer pinned to bottom of drawer -->
      <template v-slot:append>
        <div class="pa-4 d-flex align-center" style="gap: 8px">
          <v-icon size="x-small" color="medium-emphasis">mdi-information-outline</v-icon>
          <span class="text-caption text-medium-emphasis">AureaSim v{{ appVersion }}</span>
        </div>
      </template>
    </v-navigation-drawer>

    <v-main>
      <div v-if="isChecking" class="d-flex align-center justify-center fill-height">
        <v-progress-circular indeterminate size="64" color="primary"></v-progress-circular>
      </div>
      <div v-else-if="serverOffline" class="d-flex align-center justify-center fill-height pa-4">
        <v-card max-width="650" width="100%" elevation="8" rounded="lg" border>
          <v-card-item class="pb-2">
            <template v-slot:prepend>
              <v-icon color="error" size="36" class="mr-3">mdi-server-network-off</v-icon>
            </template>
            <v-card-title class="text-h5 font-weight-bold text-error">Backend Server Offline</v-card-title>
          </v-card-item>
          <v-card-text class="pt-4 text-body-1">
            <p class="mb-4">
              AureaSim's Vue frontend cannot connect to the Python FastAPI backend. The simulation orchestrator must be running for the dashboard to function.
            </p>
            <p class="font-weight-bold mb-2">How to start the server (in a new terminal):</p>
            <v-sheet color="grey-darken-4" class="pa-4 rounded-lg mb-4" theme="dark" border>
              <code class="text-body-2 d-block text-white" style="font-family: monospace;">
                # 1. Activate the AureaSim Conda environment<br>
                <span class="text-green-accent-2">conda</span> activate prosimos_env<br>
                <br>
                # 2. Start the backend server<br>
                <span class="text-green-accent-2">python</span> server.py
              </code>
            </v-sheet>
            <p class="text-body-2 text-medium-emphasis mb-2">
              If your environment is broken or missing, recreate it cleanly using Python 3.11:
            </p>
            <v-sheet color="grey-darken-4" class="pa-4 rounded-lg mb-4" theme="dark" border>
              <code class="text-caption d-block text-grey-lighten-2" style="font-family: monospace;">
                <span class="text-green-accent-2">conda</span> create -n prosimos_env python=3.11 pip -y<br>
                <span class="text-green-accent-2">conda</span> activate prosimos_env<br>
                <span class="text-green-accent-2">pip</span> install -r requirements.txt<br>
                <span class="text-green-accent-2">python</span> server.py
              </code>
            </v-sheet>
          </v-card-text>
          <v-divider></v-divider>
          <v-card-actions class="pa-4 bg-grey-lighten-4">
            <v-spacer></v-spacer>
            <v-btn color="primary" variant="flat" prepend-icon="mdi-refresh" size="large" class="px-6 text-none" @click="checkServer" :loading="isChecking">
              Reconnect
            </v-btn>
          </v-card-actions>
        </v-card>
      </div>
      <router-view v-else />
    </v-main>

    <NewProjectDialog
      v-model="showNewProjectDialog"
      @completed="onSimulationCompleted"
    />
  </v-app>
</template>

<script lang="ts" setup>
  import { ref, computed, onMounted } from 'vue'
  import { useTheme } from 'vuetify'
  import NewProjectDialog from '@/components/NewProjectDialog.vue'

  const drawer = ref(true)
  const theme = useTheme()
  const showNewProjectDialog = ref(false)
  const appVersion = ref('...')
  const serverOffline = ref(false)
  const isChecking = ref(true)

  onMounted(() => {
    checkServer()
  })

  async function checkServer() {
    isChecking.value = true
    try {
      const res = await fetch('/api/version')
      if (!res.ok) throw new Error('Network response was not ok')
      const data = await res.json()
      appVersion.value = data.version
      serverOffline.value = false
    } catch {
      appVersion.value = '?'
      serverOffline.value = true
    } finally {
      isChecking.value = false
    }
  }

  const themeIcon = computed(() => {
    return theme.global.current.value.dark ? 'mdi-weather-sunny' : 'mdi-weather-night'
  })

  function toggleTheme () {
    theme.change(theme.global.current.value.dark ? 'light' : 'dark')
  }

  function onSimulationCompleted() {
    // Notify components that a project was created (e.g. Dashboard)
    window.dispatchEvent(new CustomEvent('project-created'))
  }
</script>
