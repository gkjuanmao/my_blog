/** 后台图标名（与 components/admin/AdminIcon.vue 的 ICONS 一一对应） */
export type AdminIconName =
  | 'grid'
  | 'doc'
  | 'folder'
  | 'hash'
  | 'clock'
  | 'users'
  | 'search'
  | 'plus'
  | 'menu'
  | 'ext'
  | 'key'
  | 'out'
  | 'close'
  | 'download'
  | 'refresh'

/** 后台自绘下拉（components/admin/AdminSelect.vue）的选项 */
export interface SelectOption {
  value: string
  label: string
  /** 右侧等宽小字（如作者名下的稿件数） */
  hint?: string
  /** 「全部 / 不限」这类默认项：文字压一档墨色 */
  muted?: boolean
}
