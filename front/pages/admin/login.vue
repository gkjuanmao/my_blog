<script setup lang="ts">
import type { LoginResponse } from '~/types/api'

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  loading.value = true
  try {
    const { data } = await useApi().post<LoginResponse>('/login/', { ...form })
    if (import.meta.client) {
      localStorage.setItem('access_token', data.access)
      localStorage.setItem('refresh_token', data.refresh)
    }
    await navigateTo('/admin/dashboard')
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-[80vh] items-center justify-center px-4">
    <el-card class="w-full max-w-md">
      <template #header>
        <div class="text-center text-xl font-serif font-bold text-brand-600 dark:text-amber-500">旅行游记 · 管理登录</div>
      </template>
      <el-form :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" @keyup.enter="handleLogin" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" @keyup.enter="handleLogin" />
        </el-form-item>
        <el-button type="warning" class="w-full" :loading="loading" @click="handleLogin">登录</el-button>
      </el-form>
    </el-card>
  </div>
</template>
