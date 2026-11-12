/**
 * 首页卷首动效（只在首页、只在客户端生效）。
 *
 * 三条纪律（见 02-ux-spec.md M8 / N1 与 01-visual-spec.md §9）：
 *  1. 入场与揭示的**起始隐藏态只能由 JS 挂类触发**（`html.js.motion-ok` / `.cv-reveal`），
 *     SSR 输出与「无 JS」场景必须直接可见 —— 首屏不可见是博客最致命的故障。
 *  2. 全页只有**一个** scroll 监听，写在 layouts/default.vue（导航态 + 进度条 + 视差）。
 *     这里只负责入场、揭示，以及三个常驻循环的暂停条件，不碰滚动（滚动回调里不读 layout）。
 *  3. 任何异常都要有兜底：入场 3s 看门狗无条件解除隐藏；没有 IntersectionObserver 时直接全可见。
 */

/** 入场序列总时长（7 项延迟 0→540ms + 720ms 动画 ≈ 1.26s） */
const ENTRANCE_SETTLE_MS = 1300
/** 看门狗：超时无条件落定，避免任何 JS 异常把首屏留在不可见状态 */
const WATCHDOG_MS = 3000
/** 卡片揭示动画时长（播完移除 data 类，交还元素自身样式，否则会压住 hover 位移） */
const REVEAL_MS = 520

/**
 * 入场 + 常驻循环的暂停条件。
 *
 * hero 元素用选择器取（首页只有一处 `.cv-hero`），避免为「组件实例 → DOM」多引一层 ref。
 */
export function useCoverEntrance(): void {
  if (!import.meta.client) return

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  let settleTimer: ReturnType<typeof setTimeout> | undefined
  let watchdogTimer: ReturnType<typeof setTimeout> | undefined
  let heroObserver: IntersectionObserver | null = null

  function onVisibilityChange() {
    document.documentElement.classList.toggle('is-hidden', document.hidden)
  }

  onMounted(() => {
    const root = document.documentElement
    // 双门控的第一道：没有 .js.motion-ok 时，CSS 里的起始隐藏态一律不生效
    root.classList.add('js')
    if (reduced.matches) return

    root.classList.add('motion-ok')
    // 落定时刻以「动画实际结束」为准，而不是固定常量：
    // 固定常量在慢水合（dev / 低端机 / 弱网）下会早于动画结束，`html.is-settled` 的
    // 「解除隐藏」规则会把入场腰斩（实测 animStart=1110ms、settle=2038ms，只播了 928ms）。
    // 拿不到动画信息时回落到常量；看门狗仍是无条件兜底。
    const settle = () => root.classList.add('is-settled')
    const scheduleSettle = () => {
      try {
        const copy = document.querySelector<HTMLElement>('.cv-home .cv-hero__copy')
        const anims = copy ? copy.getAnimations({ subtree: true }) : []
        if (!anims.length) {
          settleTimer = setTimeout(settle, ENTRANCE_SETTLE_MS)
          return
        }
        const ends = anims
          .map((a) => {
            const timing =
              a.effect && 'getComputedTiming' in a.effect
                ? (a.effect as KeyframeEffect).getComputedTiming()
                : null
            const startTime = Number(a.startTime ?? performance.now())
            const endTime = timing ? Number(timing.endTime) : Number.NaN
            return Number.isFinite(startTime) && Number.isFinite(endTime) ? startTime + endTime : Number.NaN
          })
          .filter((n) => Number.isFinite(n))
        if (!ends.length) {
          settleTimer = setTimeout(settle, ENTRANCE_SETTLE_MS)
          return
        }
        const wait = Math.max(0, Math.max(...ends) - performance.now()) + 40
        settleTimer = setTimeout(settle, wait)
      } catch {
        settleTimer = setTimeout(settle, ENTRANCE_SETTLE_MS)
      }
    }
    // 动画在挂类后的下一帧才创建，等两帧再量
    requestAnimationFrame(() => requestAnimationFrame(scheduleSettle))
    watchdogTimer = setTimeout(settle, WATCHDOG_MS)

    document.addEventListener('visibilitychange', onVisibilityChange)

    const hero = document.querySelector<HTMLElement>('.cv-home .cv-hero')
    if (hero && 'IntersectionObserver' in window) {
      heroObserver = new IntersectionObserver(
        (entries) => {
          root.classList.toggle('hero-offscreen', !(entries[0]?.isIntersecting ?? true))
        },
        { threshold: 0 },
      )
      heroObserver.observe(hero)
    }
  })

  onBeforeUnmount(() => {
    const root = document.documentElement
    clearTimeout(settleTimer)
    clearTimeout(watchdogTimer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    heroObserver?.disconnect()
    heroObserver = null
    root.classList.remove('js', 'motion-ok', 'is-settled', 'hero-offscreen', 'is-hidden')
  })
}

/**
 * 卡片揭示（IntersectionObserver）。
 *
 * @param grid 网格根元素（`<ul class="cv-grid">`）
 * @param signature 数据签名；变化（翻页 / 换每页条数）后重新绑定
 *
 * 错峰规则：同排 +80ms、换排 +120ms。行判定用 `offsetTop`，只在数据变化时读一次，
 * 不进滚动回调，所以不会造成强制同步布局。
 */
export function useCoverReveal(
  grid: Ref<HTMLElement | null>,
  signature: () => string,
): void {
  if (!import.meta.client) return

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  let observer: IntersectionObserver | null = null
  const timers = new Set<ReturnType<typeof setTimeout>>()

  function teardown() {
    observer?.disconnect()
    observer = null
    timers.forEach(clearTimeout)
    timers.clear()
    grid.value?.querySelectorAll<HTMLElement>('.cv-grid__item').forEach((item) => {
      item.classList.remove('cv-reveal', 'is-revealed')
      item.style.removeProperty('--cv-reveal-delay')
    })
  }

  function setup() {
    teardown()
    const root = grid.value
    // 减少动效 / 无 IntersectionObserver：保持元素天然可见，不做任何隐藏
    if (!root || reduced.matches || !('IntersectionObserver' in window)) return

    const items = Array.from(root.children) as HTMLElement[]
    if (items.length === 0) return

    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const el = entry.target as HTMLElement
          el.classList.add('is-revealed')
          observer?.unobserve(el)
          const delay =
            Number(el.style.getPropertyValue('--cv-reveal-delay').replace('ms', '')) || 0
          const timer = setTimeout(() => {
            el.classList.remove('cv-reveal', 'is-revealed')
            el.style.removeProperty('--cv-reveal-delay')
            timers.delete(timer)
          }, REVEAL_MS + delay)
          timers.add(timer)
        }
      },
      // rootMargin 下方放宽到 +12%：卡片刚进入视口下缘就揭示，而不是「再滚 6% 才开始」
      { rootMargin: '0px 0px 12% 0px', threshold: 0.01 },
    )

    let delay = 0
    items.forEach((item, index) => {
      if (index > 0) {
        // 行判定：与上一项顶边基本重合 = 同排
        const sameRow = Math.abs(item.offsetTop - items[index - 1]!.offsetTop) < 8
        // 错峰只做「同行微错开」，不再累加到 900ms 那种让最后一张卡迟迟不出现的程度
        delay += sameRow ? 60 : 90
        delay = Math.min(delay, 360)
      }
      item.style.setProperty('--cv-reveal-delay', `${delay}ms`)
      item.classList.add('cv-reveal')
      observer?.observe(item)
    })
  }

  onMounted(setup)
  watch(signature, () => {
    void nextTick(setup)
  })
  onBeforeUnmount(teardown)
}
