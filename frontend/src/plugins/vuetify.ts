/**
 * plugins/vuetify.ts
 *
 * Framework documentation: https://vuetifyjs.com`
 */

// Composables
import { createVuetify } from 'vuetify'
// Styles
import '@mdi/font/css/materialdesignicons.css'

import 'vuetify/styles'

// https://vuetifyjs.com/en/introduction/why-vuetify/#feature-guides
export default createVuetify({
  theme: {
    defaultTheme: 'dark',
    themes: {
      light: {
        colors: {
          primary:    '#D97706', // Amber 600 – logo primary
          secondary:  '#78716C', // Warm Stone 500 – complements amber
          accent:     '#0F766E', // Teal 700 – amber's color-wheel complement
          info:       '#0891B2', // Cyan 600 – warm-adjacent blue
          background: '#FAFAF9', // Warm White (Stone 50)
          surface:    '#FFFFFF',
          success:    '#059669', // Emerald 600
          warning:    '#EA580C', // Orange 600 – warm but distinct from primary
          error:      '#DC2626', // Red 600
        },
      },
      dark: {
        colors: {
          primary:    '#FBBF24', // Amber 400 – logo primary
          secondary:  '#A8A29E', // Warm Stone 400 – replaces cool slate
          accent:     '#2DD4BF', // Teal 400 – amber's color-wheel complement
          info:       '#22D3EE', // Cyan 400 – warm-toned, replaces stark blue
          background: '#18181B', // Zinc 900 – warm dark (no blue tint)
          surface:    '#27272A', // Zinc 800 – warm surface
          success:    '#34D399', // Emerald 400
          warning:    '#FB923C', // Orange 400 – distinct from amber primary
          error:      '#F87171', // Red 400
        },
      },
    },
  },
})
