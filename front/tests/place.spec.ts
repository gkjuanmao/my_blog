import { describe, expect, it } from 'vitest'

import { shortPlace } from '../utils/place'

describe('shortPlace', () => {
  it('四级地名取末两段', () => {
    expect(shortPlace('中国 · 江苏省 · 南京市 · 玄武区')).toBe('南京市 · 玄武区')
  })

  it('三级地名去掉「中国」后原样返回', () => {
    expect(shortPlace('中国 · 江苏省 · 南京市')).toBe('江苏省 · 南京市')
  })

  it('只有省级时去掉「中国」', () => {
    expect(shortPlace('中国 · 江苏省')).toBe('江苏省')
  })

  it('港澳台保留分区 + 区县', () => {
    expect(shortPlace('中国香港 · 香港岛 · 中西区')).toBe('香港岛 · 中西区')
  })

  it('境外两地名保持不变', () => {
    expect(shortPlace('瑞士 · 因特拉肯')).toBe('瑞士 · 因特拉肯')
  })

  it('老数据是没有分隔符的自由文本，原样返回', () => {
    expect(shortPlace('瑞士蒙特勒 日内瓦')).toBe('瑞士蒙特勒 日内瓦')
    expect(shortPlace('青海祁连 峨堡镇 西宁')).toBe('青海祁连 峨堡镇 西宁')
    expect(shortPlace('罗马')).toBe('罗马')
  })

  it('首尾空格不进入展示', () => {
    expect(shortPlace('  中国 · 云南省 · 大理白族自治州  ')).toBe('云南省 · 大理白族自治州')
  })

  it('空字符串安全返回', () => {
    expect(shortPlace('')).toBe('')
    expect(shortPlace('   ')).toBe('')
  })
})
