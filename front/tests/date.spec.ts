import { describe, expect, it } from 'vitest'

import { formatDate, formatDateTime } from '../utils/date'

describe('date utils', () => {
  it('formatDate 统一按 Asia/Shanghai 输出中文日期', () => {
    // UTC 的 2026-07-18T00:00:00Z 在上海是 7/18 08:00
    expect(formatDate('2026-07-18T00:00:00Z')).toBe('2026年7月18日')
  })

  it('formatDateTime 输出日期 + 时分（24 小时制）', () => {
    expect(formatDateTime('2026-07-18T00:00:00Z')).toBe('2026/07/18 08:00')
  })
})