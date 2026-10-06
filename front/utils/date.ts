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

/** 仅日期，如「2026年7月18日」（公开页卡片/详情） */
export function formatDate(iso: string): string {
  return DATE_FORMATTER.format(new Date(iso))
}

/** 日期 + 时分，如「2026/07/18 16:00」（后台列表） */
export function formatDateTime(iso: string): string {
  return DATETIME_FORMATTER.format(new Date(iso))
}