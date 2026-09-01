// Global intercepts for path-based reverse proxy environments (like Code Ocean)
const pathMatch = window.location.pathname.match(/\/cw\/[^\/]+\/proxy\/[0-9]+\//)
if (pathMatch) {
  const base = pathMatch[0].replace(/\/$/, '') // Extract prefix (e.g. '/cw/session-id/proxy/3000')
  
  // Override Fetch
  const originalFetch = window.fetch
  window.fetch = async (input, init) => {
    if (typeof input === 'string' && input.startsWith('/api/')) {
      input = base + input
    }
    return originalFetch(input, init)
  }

  // Override EventSource
  const originalEventSource = window.EventSource
  window.EventSource = class extends originalEventSource {
    constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
      if (typeof url === 'string' && url.startsWith('/api/')) {
        url = base + url
      }
      super(url, eventSourceInitDict)
    }
  } as any
}


// Composables
import { createApp } from 'vue'

// Plugins
import { registerPlugins } from '@/plugins'

// Components
import App from './App.vue'

// Styles
import 'unfonts.css'

const app = createApp(App)

registerPlugins(app)

app.mount('#app')
