import { describe, expect, it } from 'vitest'

import { errorMessage } from '../composables/useApi'

describe('errorMessage', () => {
  it('优先取后端信封里的 data.message', () => {
    expect(errorMessage({ data: { message: '分类不存在' } }, '兜底')).toBe('分类不存在')
  })

  it('退回顶层 message', () => {
    expect(errorMessage({ message: '令牌无效' }, '兜底')).toBe('令牌无效')
  })

  it('都没有时使用调用方兜底文案（非 ofetch 技术串）', () => {
    expect(errorMessage(null, '加载失败')).toBe('加载失败')
    expect(errorMessage('cancel', '导出失败')).toBe('导出失败')
    expect(errorMessage({ data: {} }, '搜索失败')).toBe('搜索失败')
  })
})