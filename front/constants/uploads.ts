/**
 * 上传阈值与尺寸的**单一来源**。
 *
 * 与后端 `config/settings/base.py`（`*_MAX_BYTES` / `*_MAX_LONG_EDGE`）保持一致；
 * 改动时请同步后端处理管线 `articles/covers.py`、`articles/images.py`，
 * 以及 `docker/nginx/nginx.conf` 的 `client_max_body_size`（普通 /api/ 为 60m）。
 */

/** 封面源文件上限（后端 COVER 上传校验） */
export const COVER_MAX_BYTES = 20 * 1024 ** 2
/** 附件源文件上限 */
export const ATTACHMENT_MAX_BYTES = 50 * 1024 ** 2
/** 正文内联图源文件上限（后端 INLINE_IMAGE_MAX_BYTES） */
export const INLINE_IMAGE_MAX_BYTES = 10 * 1024 ** 2
/** HTML 导入单文件上限（后端 HTML_IMPORT_MAX_BYTES） */
export const HTML_IMPORT_MAX_BYTES = 100 * 1024 ** 2
/** nginx 对普通 /api/ 的上传上限：封面 + 附件合计不能超过它 */
export const API_UPLOAD_LIMIT_BYTES = 60 * 1024 ** 2

/** 内联图落盘后的最长边上限（后端 INLINE_IMAGE_MAX_LONG_EDGE，只缩不放） */
export const INLINE_IMAGE_MAX_LONG_EDGE = 1920

/** 字节数 → 整数 MB 文案（如 20971520 → "20MB"），用于提示语，避免硬编码数字 */
export function formatMB(bytes: number): string {
  return `${Math.round(bytes / 1024 ** 2)}MB`
}