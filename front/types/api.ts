export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface ErrorResponse {
  code: number
  message: string | Record<string, unknown> | string[]
  data: null
}

/**
 * useApi 统一抛出的错误形状（见 composables/useApi.ts 的 normalizeApiError）：
 * `message` 与 `data.message` 都是后端中文提示，二者同值，便于不同页面取用。
 * 用它替换 `catch (e: any)` 里的 any。
 */
export interface ApiError {
  status?: number
  response?: { status: number }
  data?: { message?: string }
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface LoginResponse {
  access: string
  refresh: string
}

export interface RefreshResponse {
  access: string
  refresh: string
}

export interface UserInfo {
  id: number
  username: string
  email: string
  avatar: string | null
  avatar_name: string | null
  date_joined: string
}

export interface Category {
  id: number
  name: string
  slug: string
  description: string
}

export interface Tag {
  id: number
  name: string
  slug: string
}

/** 文章（articles/schemas.py ArticleOut） */
export interface Article {
  id: number
  title: string
  slug: string
  summary: string
  publish_time: string
  location: string
  category: Category | null
  tags: Tag[]
  cover_image_name: string
  cover_image_url: string | null
  file_name: string
  file_url: string | null
  is_published: boolean
  views: number
  created_at: string
  updated_at: string
}

/** 文章详情（articles/schemas.py ArticleDetailOut）：正文为服务端渲染并消毒后的 HTML */
export interface ArticleDetail extends Article {
  author: string
  content_html: string
}

/** 管理端文章详情（articles/schemas.py AdminArticleDetailOut）：额外带原始 Markdown */
export interface AdminArticleDetail extends ArticleDetail {
  content: string
}

/* ------------------------------------------------------------------ 归档（导入/导出） */

/** 导出预估（articles/archive/export.py ExportEstimate） */
export interface ArchiveEstimate {
  count: number
  source_bytes: number
  entries: number
  /** 是否可被本系统再次导入（超出导入上限时为 false） */
  importable: boolean
  blocking_reasons: string[]
  warnings: string[]
}

/** 导出票据（一次性下载链接） */
export interface ArchiveExportTicket {
  ticket: string
  download_url: string
  expires_at: string
  filename: string
  count: number
  bytes: number
  warnings: string[]
}

/** 批量删除结果（POST /admin/articles/bulk-delete/） */
export interface BulkDeleteResult {
  /** 去重后的请求数量 */
  requested: number
  deleted: number
  /** 请求里已不存在的 id（不算错误） */
  not_found: number[]
}

export type ArchiveStrategy = 'skip' | 'update' | 'create_new'

export type ArchiveAction = 'create' | 'update' | 'skip' | 'failed'

/** 报告里的单篇结果 */
export interface ArchiveReportItem {
  path: string
  slug: string
  title: string
  action: ArchiveAction
  effective_action: string
  /** 仅 action=skip 时有值：strategy | identical */
  skip_reason: string | null
  target_id: number | null
  final_slug: string
  warnings: string[]
  errors: string[]
}

/** 预检 / 执行报告 */
export interface ArchiveReport {
  dry_run: boolean
  schema: string
  staged_id?: string
  package: { entries: number; bytes_uncompressed: number; sha256: string }
  totals: {
    total: number
    create: number
    update: number
    skip: number
    failed: number
    categories_to_create: string[]
    tags_to_create: string[]
    skipped_identical: number
  }
  items: ArchiveReportItem[]
  rollback_package?: {
    count: number
    ticket: string
    download_url: string
    expires_at: string
  } | null
}

/** 导入上限（供前端上传递前本地预检） */
export interface ArchiveLimits {
  max_upload_bytes: number
  max_entries: number
  max_total_uncompressed: number
  max_member_bytes: number
  max_articles_per_export: number
  max_ids_per_request: number
  cover_extensions: string[]
  attachment_extensions: string[]
  attachment_legacy_extensions: string[]
  cover_max_bytes: number
  attachment_max_bytes: number
}
