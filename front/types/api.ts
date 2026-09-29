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

/** 文章详情（articles/schemas.py ArticleDetailOut，作者为字符串） */
export interface ArticleDetail extends Article {
  author: string
}
