import type { ApiResponse } from '~/types/api'

interface ApiOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: Record<string, unknown> | BodyInit | null
  params?: Record<string, unknown>
}

export function useApi() {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase as string

  function resolveUrl(url: string): string {
    if (/^https?:\/\//.test(url)) return url
    return `${apiBase}${url.replace(/^\//, '')}`
  }

  async function request<T>(url: string, options: ApiOptions = {}): Promise<T> {
    const headers: Record<string, string> = {}
    const isFormData = options.body instanceof FormData
    if (!isFormData) headers['Content-Type'] = 'application/json'
    if (import.meta.client) {
      const token = localStorage.getItem('access_token')
      if (token) headers.Authorization = `Bearer ${token}`
    }
    try {
      const data = await $fetch<T>(resolveUrl(url), {
        method: options.method ?? 'GET',
        body: options.body,
        query: options.params,
        headers,
      })
      return data
    } catch (error: any) {
      if (error?.response?.status === 401) {
        if (import.meta.client) localStorage.removeItem('access_token')
        await navigateTo('/administrator/login')
      }
      throw error
    }
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
  }
}
