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
        /*
         * 首页卷首视觉层的令牌别名（定义见 assets/css/home-cover.css）。
         * 只用于「一处颜色」的简单场景；带透明度修饰符（如 bg-hp-surface/80）
         * 在 var() 颜色下不生效，需要半透明请直接用 rgba 令牌。
         */
        hp: {
          bg: 'var(--hp-bg)',
          'bg-2': 'var(--hp-bg-2)',
          surface: 'var(--hp-surface)',
          'surface-2': 'var(--hp-surface-2)',
          ink: 'var(--hp-ink)',
          'ink-2': 'var(--hp-ink-2)',
          'ink-3': 'var(--hp-ink-3)',
          line: 'var(--hp-line)',
          brand: 'var(--hp-brand)',
          accent: 'var(--hp-accent)',
          lume: 'var(--hp-accent-lume)',
          'on-accent': 'var(--hp-on-accent)',
          'on-brand': 'var(--hp-on-brand)',
        },
      },
    },
  },
  plugins: [],
}
