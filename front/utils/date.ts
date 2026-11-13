/** 日期/时间格式化的单一来源：统一 `Asia/Shanghai` 口径，避免各页面各写一套（FE-23）。 */

const DATE_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

const DATETIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const COMPACT_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** 仅日期，如「2026年7月18日」（公开页卡片/详情） */
export function formatDate(iso: string): string {
  return DATE_FORMATTER.format(new Date(iso))
}

/**
 * 紧凑日期，如「2026.07.18」（首页卡片脚行 / 序号区，与等宽字搭配）。
 * 口径与 formatDate 一致（Asia/Shanghai），只是换成不占宽的纯数字形态。
 */
export function formatDateCompact(iso: string): string {
  const parts = COMPACT_FORMATTER.formatToParts(new Date(iso))
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? ''
  return `${pick('year')}.${pick('month')}.${pick('day')}`
}

/** 日期 + 时分，如「2026/07/18 16:00」（后台列表） */
export function formatDateTime(iso: string): string {
  return DATETIME_FORMATTER.format(new Date(iso))
}

const MINUTE_MS = 60_000

/**
 * 相对时间，如「刚刚 / 12 分钟前 / 3 小时前 / 2 天前」，超过 30 天回落成日期。
 *
 * 用于用户列表的「最近活跃」：绝对时间在这里没有信息量，
 * 而「多久没动过」才是管理员关心的。`now` 可注入，便于测试与统一渲染基准。
 * 传入 null（从未活跃）返回「从未」。
 */
export function formatRelativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '从未'
  const diff = now - new Date(iso).getTime()
  // 客户端时钟可能比服务端慢，diff < 0 时按「刚刚」处理，不显示负数
  if (diff < MINUTE_MS) return '刚刚'
  if (diff < 60 * MINUTE_MS) return `${Math.floor(diff / MINUTE_MS)} 分钟前`
  if (diff < 24 * 60 * MINUTE_MS) return `${Math.floor(diff / (60 * MINUTE_MS))} 小时前`
  const days = Math.floor(diff / (24 * 60 * MINUTE_MS))
  if (days < 30) return `${days} 天前`
  return formatDate(iso)
}