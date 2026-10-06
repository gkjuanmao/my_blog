/**
 * 皮肤动效（仅公开页、仅非默认皮肤、仅客户端 —— 由 layouts/default.vue 调用）：
 *  1) 滚动揭示 / 卡片 3D 倾斜 / 按钮磁场（复刻 0627 的 elegant-motion.js）
 *  2) 首屏粒子网络画布（.skin-hero 内，复刻 0627 的 hero canvas）
 *  3) 鼠标跟随光晕（驱动 --cursor-x/--cursor-y，CSS 里画径向渐变）
 *
 * 设计要点：
 * - 尊重 prefers-reduced-motion（开启时完全不动）
 * - 用 MutationObserver 兜住异步渲染出来/路由切换后的列表与新节点
 * - 皮肤切回默认 / 离开公开页时自动清理，不残留 class / 画布 / 监听器
 */
// 动效锚点用语义 data-skin 属性（见 components/ArticleCard.vue、pages/categories.vue、
// pages/article/[slug].vue），避免改了 Tailwind 工具类（如 rounded-2xl / bg-brand-600）
// 后动效静默失效（FE-20）。
const CARD_SELECTOR = '[data-skin="card"], [data-skin="card-link"]'
const REVEAL_SELECTOR = `${CARD_SELECTOR}, h1, h2, h3, .md-body > *`
const TILT_SELECTOR = CARD_SELECTOR
const MAGNETIC_SELECTOR = '.el-button:not(.is-text):not(.is-link), [data-skin="button"]'
const ALL_SELECTOR = [REVEAL_SELECTOR, TILT_SELECTOR, MAGNETIC_SELECTOR].join(',')
const REVEAL_MS = 900

interface Particle {
  x: number
  y: number
  phase: number
  rx: number
  ry: number
}

export function useSkinMotion() {
  const { skin } = useAppTheme()

  if (!import.meta.client) return

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const finePointer = window.matchMedia('(pointer: fine)')
  let dispose: (() => void) | null = null

  function teardown() {
    dispose?.()
    dispose = null
  }

  function setup() {
    teardown()
    if (skin.value === 'default' || reduced.matches) return

    const shell = document.querySelector<HTMLElement>('.public-shell')
    if (!shell) return
    // 取别名后再进闭包，避免 TS 在闭包内丢失非空收窄
    const root: HTMLElement = shell

    const timers = new Set<ReturnType<typeof setTimeout>>()
    const bound = new WeakSet<HTMLElement>()
    const interactionCleanups: Array<() => void> = []
    let scanTimer: ReturnType<typeof setTimeout> | undefined
    let heroCleanup: (() => void) | null = null
    let glowCleanup: (() => void) | null = null

    /* ---------------- 1) 滚动揭示 / 倾斜 / 磁场 ---------------- */
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const el = entry.target as HTMLElement
          el.classList.add('skin-reveal-in')
          observer.unobserve(el)
          const delay =
            Number((el.style.getPropertyValue('--reveal-delay') || '0ms').replace('ms', '')) || 0
          // 动画结束后移除 class，交还元素自身的样式（否则会压住 hover 的位移效果）
          const t = setTimeout(() => {
            el.classList.remove('skin-reveal', 'skin-reveal-in')
            el.style.removeProperty('--reveal-delay')
            timers.delete(t)
          }, delay + REVEAL_MS)
          timers.add(t)
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.12 },
    )

    function bindTilt(el: HTMLElement) {
      el.classList.add('skin-tilt')
      const move = (event: PointerEvent) => {
        const rect = el.getBoundingClientRect()
        const x = (event.clientX - rect.left) / rect.width - 0.5
        const y = (event.clientY - rect.top) / rect.height - 0.5
        el.style.setProperty('--tilt-y', `${x * 7}deg`)
        el.style.setProperty('--tilt-x', `${y * -7}deg`)
        el.classList.add('is-tilting')
      }
      const leave = () => {
        el.classList.remove('is-tilting')
        el.style.setProperty('--tilt-x', '0deg')
        el.style.setProperty('--tilt-y', '0deg')
      }
      el.addEventListener('pointermove', move)
      el.addEventListener('pointerleave', leave)
      interactionCleanups.push(() => {
        el.removeEventListener('pointermove', move)
        el.removeEventListener('pointerleave', leave)
        el.classList.remove('skin-tilt', 'is-tilting')
        el.style.removeProperty('--tilt-x')
        el.style.removeProperty('--tilt-y')
      })
    }

    function bindMagnetic(el: HTMLElement) {
      el.classList.add('skin-magnetic')
      const move = (event: PointerEvent) => {
        const rect = el.getBoundingClientRect()
        const x = event.clientX - (rect.left + rect.width / 2)
        const y = event.clientY - (rect.top + rect.height / 2)
        el.style.setProperty('--mag-x', `${x * 0.16}px`)
        el.style.setProperty('--mag-y', `${y * 0.16}px`)
        el.classList.add('is-magnetic')
      }
      const leave = () => {
        el.classList.remove('is-magnetic')
        el.style.setProperty('--mag-x', '0px')
        el.style.setProperty('--mag-y', '0px')
      }
      el.addEventListener('pointermove', move)
      el.addEventListener('pointerleave', leave)
      interactionCleanups.push(() => {
        el.removeEventListener('pointermove', move)
        el.removeEventListener('pointerleave', leave)
        el.classList.remove('skin-magnetic', 'is-magnetic')
        el.style.removeProperty('--mag-x')
        el.style.removeProperty('--mag-y')
      })
    }

    function bind(el: HTMLElement) {
      if (bound.has(el)) return
      bound.add(el)
      if (el.matches(REVEAL_SELECTOR)) {
        el.classList.add('skin-reveal')
        observer.observe(el)
      }
      if (!finePointer.matches) return
      if (el.matches(TILT_SELECTOR)) bindTilt(el)
      if (el.matches(MAGNETIC_SELECTOR)) bindMagnetic(el)
    }

    /* ---------------- 2) 首屏粒子网络画布 ---------------- */
    function mountHeroCanvas(hero: HTMLElement) {
      const canvas = document.createElement('canvas')
      canvas.className = 'skin-motion-field'
      canvas.setAttribute('aria-hidden', 'true')
      hero.prepend(canvas)

      const ctx = canvas.getContext('2d')
      if (!ctx) {
        canvas.remove()
        return
      }

      const styles = getComputedStyle(document.documentElement)
      const lineRgb = styles.getPropertyValue('--skin-motion-line').trim() || '143, 105, 63'
      const dotRgb = styles.getPropertyValue('--skin-motion-dot').trim() || '33, 31, 26'

      let width = 0
      let height = 0
      let gap = 0
      let linkDist = 0
      let points: Particle[] = []
      let raf = 0
      let stopped = false
      // 离屏 / 后台标签页时暂停 rAF，避免持续逐帧重绘（FE-21）
      let running = false
      let inView = true
      const pointer = { x: 0, y: 0, active: false }

      function resize() {
        const rect = hero.getBoundingClientRect()
        const dpr = Math.min(window.devicePixelRatio || 1, 2)
        width = Math.max(1, rect.width)
        height = Math.max(1, rect.height)
        canvas.width = Math.floor(width * dpr)
        canvas.height = Math.floor(height * dpr)
        canvas.style.width = `${width}px`
        canvas.style.height = `${height}px`
        ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)
        // 间距按容器尺寸自适应：0627 的 hero 是整屏高，而本站 hero 是矮横幅卡片，
        // 用固定 132px 会让绝大多数点落到画布外（只剩顶边一行，肉眼不可见）。
        gap = Math.max(40, Math.min(120, Math.min(width / 9, height / 3.5)))
        linkDist = Math.max(88, gap * 2.6)
        points = []
        for (let y = -gap; y <= height + gap; y += gap) {
          for (let x = -gap; x <= width + gap; x += gap) {
            points.push({ x, y, phase: Math.random() * Math.PI * 2, rx: x, ry: y })
          }
        }
      }

      function frame(time: number) {
        if (stopped || !running) return
        const t = time * 0.001
        ctx!.clearRect(0, 0, width, height)
        ctx!.lineWidth = 1

        for (const p of points) {
          const x = p.x + Math.sin(t + p.phase) * 16
          const y = p.y + Math.cos(t * 0.8 + p.phase) * 10
          if (pointer.active) {
            const dx = pointer.x - x
            const dy = pointer.y - y
            const distance = Math.hypot(dx, dy)
            if (distance < 230 && distance > 0) {
              const pull = (1 - distance / 230) * 20
              p.rx = x - (dx / distance) * pull
              p.ry = y - (dy / distance) * pull
            } else {
              p.rx = x
              p.ry = y
            }
          } else {
            p.rx = x
            p.ry = y
          }
        }

        for (let i = 0; i < points.length; i += 1) {
          const a = points[i]
          for (let j = i + 1; j < points.length; j += 1) {
            const b = points[j]
            const distance = Math.hypot(a.rx - b.rx, a.ry - b.ry)
            if (distance < linkDist) {
              ctx!.strokeStyle = `rgba(${lineRgb}, ${(1 - distance / linkDist) * 0.42})`
              ctx!.beginPath()
              ctx!.moveTo(a.rx, a.ry)
              ctx!.lineTo(b.rx, b.ry)
              ctx!.stroke()
            }
          }
        }

        ctx!.fillStyle = `rgba(${dotRgb}, 0.34)`
        for (const p of points) {
          ctx!.beginPath()
          ctx!.arc(p.rx, p.ry, 1.35, 0, Math.PI * 2)
          ctx!.fill()
        }
        raf = requestAnimationFrame(frame)
      }

      const onMove = (event: PointerEvent) => {
        const rect = hero.getBoundingClientRect()
        pointer.x = event.clientX - rect.left
        pointer.y = event.clientY - rect.top
        pointer.active = true
      }
      const onLeave = () => {
        pointer.active = false
      }
      const onResize = () => resize()

      hero.addEventListener('pointermove', onMove, { passive: true })
      hero.addEventListener('pointerleave', onLeave)
      window.addEventListener('resize', onResize, { passive: true })

      function start() {
        if (running || stopped || !inView || document.hidden) return
        running = true
        raf = requestAnimationFrame(frame)
      }
      function pause() {
        running = false
        cancelAnimationFrame(raf)
      }
      const onVisibility = () => {
        if (document.hidden) pause()
        else start()
      }
      const io = new IntersectionObserver((entries) => {
        inView = entries[0]?.isIntersecting ?? true
        if (inView) start()
        else pause()
      })

      resize()
      io.observe(hero)
      document.addEventListener('visibilitychange', onVisibility)
      start()

      heroCleanup = () => {
        stopped = true
        cancelAnimationFrame(raf)
        io.disconnect()
        document.removeEventListener('visibilitychange', onVisibility)
        hero.removeEventListener('pointermove', onMove)
        hero.removeEventListener('pointerleave', onLeave)
        window.removeEventListener('resize', onResize)
        canvas.remove()
        heroCleanup = null
      }
    }

    /** 路由切换/异步渲染后同步：有 .skin-hero 就挂画布，没有就拆掉 */
    function syncHeroCanvas() {
      const hero = root.querySelector<HTMLElement>('.skin-hero')
      if (!hero) {
        heroCleanup?.()
        return
      }
      if (heroCleanup) return
      mountHeroCanvas(hero)
    }

    /* ---------------- 3) 鼠标跟随光晕 ---------------- */
    function setupPointerGlow() {
      if (!finePointer.matches) return
      const el = document.documentElement
      let currentX = window.innerWidth / 2
      let currentY = window.innerHeight / 2
      let targetX = currentX
      let targetY = currentY
      let raf = 0
      let stopped = false
      let running = false

      const onMove = (event: PointerEvent) => {
        targetX = event.clientX
        targetY = event.clientY
        el.classList.add('skin-pointer')
      }

      function tick() {
        if (stopped || !running) return
        currentX += (targetX - currentX) * 0.14
        currentY += (targetY - currentY) * 0.14
        // 收敛后不再写样式，避免无意义的逐帧样式重算
        if (Math.abs(targetX - currentX) > 0.2 || Math.abs(targetY - currentY) > 0.2) {
          el.style.setProperty('--cursor-x', `${currentX}px`)
          el.style.setProperty('--cursor-y', `${currentY}px`)
        }
        raf = requestAnimationFrame(tick)
      }

      function start() {
        if (running || stopped || document.hidden) return
        running = true
        raf = requestAnimationFrame(tick)
      }
      function pause() {
        running = false
        cancelAnimationFrame(raf)
      }
      const onVisibility = () => {
        if (document.hidden) pause()
        else start()
      }

      window.addEventListener('pointermove', onMove, { passive: true })
      document.addEventListener('visibilitychange', onVisibility)
      start()

      glowCleanup = () => {
        stopped = true
        cancelAnimationFrame(raf)
        document.removeEventListener('visibilitychange', onVisibility)
        window.removeEventListener('pointermove', onMove)
        el.classList.remove('skin-pointer')
        el.style.removeProperty('--cursor-x')
        el.style.removeProperty('--cursor-y')
        glowCleanup = null
      }
    }

    /* ---------------- 扫描 + 观察 ---------------- */
    function scan() {
      if (root.matches(ALL_SELECTOR)) bind(root)
      root.querySelectorAll<HTMLElement>(ALL_SELECTOR).forEach(bind)
      syncHeroCanvas()
    }

    scan()
    setupPointerGlow()

    const mo = new MutationObserver((records) => {
      // 只在**新增节点**时重扫：纯删除/属性变化不需要重新绑定（FE-21）
      if (!records.some((record) => record.addedNodes.length > 0)) return
      if (scanTimer) clearTimeout(scanTimer)
      scanTimer = setTimeout(scan, 120)
    })
    mo.observe(root, { childList: true, subtree: true })

    dispose = () => {
      observer.disconnect()
      mo.disconnect()
      if (scanTimer) clearTimeout(scanTimer)
      timers.forEach(clearTimeout)
      timers.clear()
      interactionCleanups.forEach((fn) => fn())
      heroCleanup?.()
      glowCleanup?.()
      root.querySelectorAll<HTMLElement>('.skin-reveal').forEach((el) => {
        el.classList.remove('skin-reveal', 'skin-reveal-in')
        el.style.removeProperty('--reveal-delay')
      })
    }
  }

  watch(
    () => skin.value,
    () => nextTick(setup),
  )
  onBeforeUnmount(teardown)
  nextTick(setup)
}