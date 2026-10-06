import type { ApiError, ApiResponse, RefreshResponse } from '~/types/api'

interface ApiOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: Record<string, unknown> | BodyInit | null
  params?: Record<string, unknown>
}

const ACCESS_TOKEN_KEY = 'access_token'
const REFRESH_TOKEN_KEY = 'refresh_token'

export function clearAuthTokens(): void {
  if (!import.meta.client) return
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

/** 同一时刻只保留一个刷新请求：并发的多个 401 共享同一次刷新，避免轮换互相踢下线 */
let refreshInFlight: Promise<boolean> | null = null

/**
 * 统一错误形状：同时提供 `message` 与 `data.message`，值优先取后端信封里的中文提示。
 * 这样公开页（`e?.message`）与后台（`e?.data?.message`）共用同一口径；
 * 后端未给 message 时回落本地化文案，而不是 ofetch 的技术串（如 `[GET] .../ 500`）。
 */
function normalizeApiError(error: unknown): ApiError {
  const source = (error ?? {}) as ApiError
  const status = source.status ?? source.response?.status ?? 0
  const backendMessage = source.data?.message
  const message =
    typeof backendMessage === 'string' && backendMessage
      ? backendMessage
      : status === 0
        ? '网络错误或服务不可用'
        : '请求失败，请稍后重试'
  return { status, response: { status }, data: { message }, message }
}

/**
 * 从任意抛出物里取中文错误文案：优先后端 message，其次调用方给的兜底文案。
 * 页面统一用 `catch (e) { errorMsg.value = errorMessage(e, '…') }` 即可，无需 any。
 */
export function errorMessage(error: unknown, fallback = '请求失败，请稍后重试'): string {
  const source = (error ?? {}) as ApiError
  return source.data?.message ?? source.message ?? fallback
}

export interface UploadProgress {
  loaded: number
  total: number
  percent: number
}

interface UploadOptions {
  onProgress?: (progress: UploadProgress) => void
  signal?: AbortSignal
}

/** 与 `$fetch` 抛出的错误形状对齐，便于调用方统一用 `e?.data?.message` / `e?.message` */
interface UploadError {
  status: number
  response: { status: number }
  data: { message?: string }
  message?: string
}

export function useApi() {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase as string

  function resolveUrl(url: string): string {
    if (/^https?:\/\//.test(url)) return url
    return `${apiBase}${url.replace(/^\//, '')}`
  }

  /**
   * 用 refresh_token 换新令牌（后端会轮换 refresh + 旧 token 进黑名单）。
   * 并发 401 共享同一次刷新；刷新失败则清空两个 token，返回 false。
   */
  function refreshTokens(): Promise<boolean> {
    if (refreshInFlight) return refreshInFlight
    refreshInFlight = (async () => {
      try {
        const refresh = localStorage.getItem(REFRESH_TOKEN_KEY)
        if (!refresh) return false
        const result = await $fetch<ApiResponse<RefreshResponse>>(`${apiBase}token/refresh/`, {
          method: 'POST',
          body: { refresh },
        })
        localStorage.setItem(ACCESS_TOKEN_KEY, result.data.access)
        localStorage.setItem(REFRESH_TOKEN_KEY, result.data.refresh)
        return true
      } catch {
        clearAuthTokens()
        return false
      } finally {
        refreshInFlight = null
      }
    })()
    return refreshInFlight
  }

  async function request<T>(url: string, options: ApiOptions = {}, allowRetry = true): Promise<T> {
    const headers: Record<string, string> = {}
    const isFormData = options.body instanceof FormData
    if (!isFormData) headers['Content-Type'] = 'application/json'
    if (import.meta.client) {
      const token = localStorage.getItem(ACCESS_TOKEN_KEY)
      if (token) headers.Authorization = `Bearer ${token}`
    }
    try {
      const resolved = resolveUrl(url)
      // SSR: resolve relative /api/v1/... against the visitor's request origin so the
      // request hits nginx (which forwards to Django); client keeps same-origin relative.
      const target = import.meta.server ? new URL(resolved, useRequestURL()).toString() : resolved
      const data = await $fetch<T>(target, {
        method: options.method ?? 'GET',
        body: options.body,
        query: options.params,
        headers,
      })
      return data
    } catch (caught) {
      const error = normalizeApiError(caught)
      if (error.status === 401) {
        if (import.meta.client) {
          // access 过期时先尝试用 refresh 续期并重放本次请求（仅重试一次）
          if (allowRetry && localStorage.getItem(REFRESH_TOKEN_KEY)) {
            const ok = await refreshTokens()
            if (ok) return request<T>(url, options, false)
          }
          clearAuthTokens()
          await navigateTo('/administrator/login')
        } else {
          // SSR 阶段调用 navigateTo 不合法，抛 Nuxt 错误交给 useAsyncData/错误页处理
          throw createError({ statusCode: 401, statusMessage: '未登录' })
        }
      }
      throw error
    }
  }

  /**
   * 带进度的 multipart 上传。
   *
   * 为什么不用 `$fetch`：Fetch API 不暴露上传进度，而导入包可能很大，
   * 没进度条用户无法判断是否卡死。
   */
  function uploadWithProgress<T>(
    url: string,
    body: FormData,
    options: UploadOptions = {},
  ): Promise<ApiResponse<T>> {
    const resolved = resolveUrl(url)
    const target = import.meta.server
      ? new URL(resolved, useRequestURL()).toString()
      : resolved

    return new Promise<ApiResponse<T>>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', target)
      if (import.meta.client) {
        const token = localStorage.getItem(ACCESS_TOKEN_KEY)
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      }
      xhr.upload.onprogress = (event) => {
        if (!options.onProgress || !event.lengthComputable) return
        options.onProgress({
          loaded: event.loaded,
          total: event.total,
          percent: Math.round((event.loaded / event.total) * 100),
        })
      }
      xhr.onload = () => {
        let payload: ApiResponse<T> | null = null
        try {
          payload = JSON.parse(xhr.responseText) as ApiResponse<T>
        } catch {
          payload = null
        }
        if (xhr.status >= 200 && xhr.status < 300 && payload) {
          resolve(payload)
          return
        }
        const backendMessage = payload?.message
        const message =
          typeof backendMessage === 'string' && backendMessage
            ? backendMessage // 后端信封里的中文提示
            : '请求失败，请稍后重试'
        const failure: UploadError = {
          status: xhr.status,
          response: { status: xhr.status },
          data: { message },
          message,
        }
        if (xhr.status === 401 && import.meta.client) {
          clearAuthTokens()
          navigateTo('/administrator/login')
        }
        reject(failure)
      }
      xhr.onerror = () =>
        reject({ status: 0, response: { status: 0 }, data: { message: '网络错误或服务不可用' } })
      xhr.onabort = () =>
        reject({ status: 0, response: { status: 0 }, data: { message: '上传已取消' } })
      options.signal?.addEventListener('abort', () => xhr.abort())
      xhr.send(body)
    })
  }

  /**
   * 用浏览器原生方式打开后端返回的**站内绝对路径**（归档票据下载）。
   * 注意：不要拼 apiBase——后端返回的已是 `/api/v1/...`，再拼会变成双重前缀。
   */
  function openUrl(absolutePath: string): void {
    if (import.meta.client) window.location.assign(absolutePath)
  }

  return {
    get<T = unknown>(url: string, params?: Record<string, unknown>) {
      return request<ApiResponse<T>>(url, { method: 'GET', params })
    },
    post<T = unknown>(url: string, body?: Record<string, unknown> | BodyInit | null) {
      return request<ApiResponse<T>>(url, { method: 'POST', body })
    },
    put<T = unknown>(url: string, body?: Record<string, unknown> | BodyInit | null) {
      return request<ApiResponse<T>>(url, { method: 'PUT', body })
    },
    del<T = unknown>(url: string) {
      return request<ApiResponse<T>>(url, { method: 'DELETE' })
    },
    uploadWithProgress,
    openUrl,
  }
}
