<script setup lang="ts">
/**
 * 管理登录：独立整页（不套公开页外壳），与后台共用纸张 + 墨青 + 印章语汇。
 * 登录接口仍走 users 的 POST /login/，成功后把两个 token 写进 localStorage。
 */
import type { LoginResponse } from '~/types/api'

definePageMeta({ layout: false })

const { site } = useAppConfig()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const errorMsg = ref('')
const sealChar = computed(() => site.name.trim().charAt(0) || '编')

async function handleLogin() {
  if (!form.username.trim()) {
    errorMsg.value = '请填写用户名'
    return
  }
  if (!form.password) {
    errorMsg.value = '请填写密码'
    return
  }
  errorMsg.value = ''
  loading.value = true
  try {
    const { data } = await useApi().post<LoginResponse>('/login/', { ...form })
    setAuthTokens(data.access, data.refresh)
    await navigateTo('/administrator/dashboard')
  } catch (e) {
    errorMsg.value = errorMessage(e, '用户名或密码错误')
  } finally {
    loading.value = false
  }
}

useHead({
  title: '管理登录',
  bodyAttrs: { class: 'ad-body' },
})
</script>

<template>
  <div class="ad-desk ad-login">
    <div class="ad-login__card">
      <div class="ad-login__seal" aria-hidden="true">{{ sealChar }}</div>
      <p class="ad-login__brand">{{ site.name }}</p>
      <p class="ad-login__eyebrow">编辑部 · Editor's Desk</p>

      <form class="ad-login__form" novalidate @submit.prevent="handleLogin">
        <label class="ad-field">
          <span>用户名</span>
          <input
            v-model="form.username"
            type="text"
            autocomplete="username"
            placeholder="请输入用户名"
            @input="errorMsg = ''"
          >
        </label>
        <label class="ad-field">
          <span>密码</span>
          <input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            @input="errorMsg = ''"
          >
        </label>

        <p v-if="errorMsg" class="ad-error" role="alert">{{ errorMsg }}</p>

        <button class="ad-btn ad-btn--primary ad-login__submit" type="submit" :disabled="loading">
          {{ loading ? '正在登录…' : '登录' }}
        </button>
      </form>

      <div class="ad-login__foot">
        <NuxtLink to="/">← 返回首页</NuxtLink>
        <span>仅限博主本人使用</span>
      </div>
    </div>
  </div>
</template>
