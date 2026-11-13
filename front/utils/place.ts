/**
 * 地点字符串的展示辅助。
 *
 * 存储口径有两种并存：
 * - 新数据：`中国 · 江苏省 · 南京市 · 玄武区`（联想选中后填入，` · ` 分隔）
 * - 老数据：`瑞士蒙特勒 日内瓦`、`青海祁连 峨堡镇 西宁`（手输自由文本，没有分隔符）
 *
 * 所以这里的每个函数都必须对「没有分隔符」的输入原样返回，不能假设格式。
 */

/** 层级分隔符，与后端 `common/geo` 生成的 label 保持一致 */
export const PLACE_SEPARATOR = ' · '

/**
 * 卡片上的短地名：只取末两段（省 + 市 或 市 + 区县）。
 *
 * 首页卡片宽度有限，`中国 · 江苏省 · 南京市 · 玄武区` 直接放会被省略号截成
 * 「中国 · 江苏省 · 南…」，反而看不出是哪儿；取末两段是信息密度最高的做法。
 * 详情页仍展示完整地名。
 */
export function shortPlace(location: string): string {
  const text = location.trim()
  if (!text.includes(PLACE_SEPARATOR)) return text

  const segments = text.split(PLACE_SEPARATOR).filter(Boolean)
  // 去掉「中国」这一层：国名对国内地点没有信息量，留着会挤掉真正要显示的末两段
  if (segments[0] === '中国') segments.shift()
  if (segments.length <= 2) return segments.join(PLACE_SEPARATOR)
  return segments.slice(-2).join(PLACE_SEPARATOR)
}
