import { describe, expect, it } from 'vitest'

import { useRequestGuard } from '../composables/useRequestGuard'

describe('useRequestGuard', () => {
  it('只有最后一次 begin() 的序号算最新', () => {
    const guard = useRequestGuard()
    const first = guard.begin()
    const second = guard.begin()

    expect(guard.isLatest(first)).toBe(false)
    expect(guard.isLatest(second)).toBe(true)
  })

  it('每个实例各自计数，互不干扰', () => {
    const a = useRequestGuard()
    const b = useRequestGuard()

    const seqA = a.begin()
    b.begin()

    expect(a.isLatest(seqA)).toBe(true)
  })
})