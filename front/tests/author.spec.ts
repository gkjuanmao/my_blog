import { describe, expect, it } from 'vitest'

import { authorQueryValue, buildAuthorQuery, parseAuthorId } from '../utils/author'

describe('author query utils', () => {
  it('parseAuthorId 只接受正整数，其余一律 null', () => {
    expect(parseAuthorId('3')).toBe(3)
    expect(parseAuthorId(['7', '9'])).toBe(7) // 数组取第一个（重复参数）
    expect(parseAuthorId(undefined)).toBeNull()
    expect(parseAuthorId('')).toBeNull()
    expect(parseAuthorId('abc')).toBeNull()
    expect(parseAuthorId('0')).toBeNull()
    expect(parseAuthorId('-1')).toBeNull()
    expect(parseAuthorId('2.5')).toBeNull()
  })

  it('authorQueryValue：null 表示「全部」，不写 URL', () => {
    expect(authorQueryValue(null)).toBeUndefined()
    expect(authorQueryValue(12)).toBe('12')
  })

  it('切作者写入 author 并删除 page（否则第 5 页会变空页）', () => {
    const next = buildAuthorQuery({ page: '5', page_size: '10', author: '3' }, 9)
    expect(next).toEqual({ page_size: '10', author: '9' })
    expect(next.page).toBeUndefined()
  })

  it('切回「全部」时删除 author 键，URL 保持干净', () => {
    const next = buildAuthorQuery({ page: '2', author: '9' }, null)
    expect(next).toEqual({})
    expect('author' in next).toBe(false)
  })

  it('不动其它无关 query（未来的筛选参数不会被误删）', () => {
    const next = buildAuthorQuery({ category_slug: 'travel', page: '3' }, 4)
    expect(next).toEqual({ category_slug: 'travel', author: '4' })
  })
})
