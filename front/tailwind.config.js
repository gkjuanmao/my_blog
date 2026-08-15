export default {
  darkMode: 'selector',
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
    './app.vue',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          800: '#92400e',
          900: '#78350f',
        },
        paper: {
          light: '#fafaf9',
          dark: '#1c1917',
        },
        ink: {
          light: '#1c1917',
          dark: '#f5f5f4',
        },
      },
    },
  },
  plugins: [],
}
