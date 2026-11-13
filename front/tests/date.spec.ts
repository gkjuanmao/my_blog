import { describe, expect, it } from 'vitest'

import { formatDate, formatDateCompact, formatDateTime, formatRelativeTime } from '../utils/date'

describe('date utils', () => {
  it('formatDate 统一按 Asia/Shanghai 输出中文日期', () => {
    // UTC 的 2026-07-18T00:00:00Z 在上海是 7/18 08:00
    expect(formatDate('2026-07-18T00:00:00Z')).toBe('2026年7月18日')
  })

  it('formatDateCompact 输出补零的紧凑日期，口径同 Asia/Shanghai', () => {
    expect(formatDateCompact('2026-07-18T00:00:00Z')).toBe('2026.07.18')
    // UTC 20:00 在上海已是次日，验证与 formatDate 同一口径
    expect(formatDateCompact('2026-07-18T20:00:00Z')).toBe('2026.07.19')
  })

  it('formatDateTime 输出日期 + 时分（24 小时制）', () => {
    expect(formatDateTime('2026-07-18T00:00:00Z')).toBe('2026/07/18 08:00')
  })

  it('formatRelativeTime 按分钟/小时/天分档，超 30 天回落日期', () => {
    const now = new Date('2026-07-18T12:00:00Z').getTime()

    expect(formatRelativeTime(null, now)).toBe('从未')
    expect(formatRelativeTime('2026-07-18T11:59:30Z', now)).toBe('刚刚')
    expect(formatRelativeTime('2026-07-18T11:48:00Z', now)).toBe('12 分钟前')
    expect(formatRelativeTime('2026-07-18T09:00:00Z', now)).toBe('3 小时前')
    expect(formatRelativeTime('2026-07-16T12:00:00Z', now)).toBe('2 天前')
    expect(formatRelativeTime('2026-05-01T12:00:00Z', now)).toBe('2026年5月1日')
  })

  it('formatRelativeTime 对客户端时钟偏慢（未来时间）不输出负数', () => {
    const now = new Date('2026-07-18T12:00:00Z').getTime()

    expect(formatRelativeTime('2026-07-18T12:05:00Z', now)).toBe('刚刚')
  })
})