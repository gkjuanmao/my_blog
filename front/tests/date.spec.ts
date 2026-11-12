import { describe, expect, it } from 'vitest'

import { formatDate, formatDateCompact, formatDateTime } from '../utils/date'

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
})