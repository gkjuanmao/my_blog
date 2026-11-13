<script setup lang="ts">
/**
 * 修改自己的密码（后台侧栏入口）。
 *
 * 三个决定：
 * 1. 必须填当前密码——后端也强制，前端不填只是个更快的 400；
 * 2. 成功后把后端返回的新令牌写回本地：当前这台设备继续可用，其他设备全部掉线
 *    （后端改了 password_changed_at 并拉黑旧 refresh）；
 * 3. 不改密码强度规则，只做「长度 ≥ 8 + 两次一致」这类表单级校验，
 *    真正的规则（常见密码/纯数字/与用户名相似）交给后端统一裁定，避免两处规则漂移。
 */
import type { ChangePasswordPayload, LoginResponse } from '~/types/api'

const visible = defineModel<boolean>({ required: true })

const api = useApi()

const form = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const submitting = ref(false)
const errorMsg = ref('')

function reset() {
  form.oldPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  errorMsg.value = ''
}

/** 表单级预检：只挡明显填错，强度规则一律以后端为准 */
function precheck(): string {
  if (!form.oldPassword) return '请填写当前密码'
  if (form.newPassword.length < 8) return '新密码至少 8 位'
  if (form.newPassword === form.oldPassword) return '新密码不能与当前密码相同'
  if (form.newPassword !== form.confirmPassword) return '两次输入的新密码不一致'
  return ''
}

async function handleSubmit() {
  const problem = precheck()
  if (problem) {
    errorMsg.value = problem
    return
  }
  errorMsg.value = ''
  submitting.value = true
  try {
    const payload: ChangePasswordPayload = {
      old_password: form.oldPassword,
      new_password: form.newPassword,
    }
    const { data } = await api.post<LoginResponse>('/password/change/', {
      ...payload,
    })
    setAuthTokens(data.access, data.refresh)
    ElMessage.success('密码已更新，其他设备需重新登录')
    visible.value = false
    reset()
  } catch (e) {
    errorMsg.value = errorMessage(e, '修改失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="min(430px, 94vw)"
    :close-on-click-modal="false"
    @closed="reset"
  >
    <form class="ad-form" @submit.prevent="handleSubmit">
      <label class="ad-field">
        <span>当前密码</span>
        <input
          v-model="form.oldPassword"
          type="password"
          autocomplete="current-password"
          placeholder="用来确认是你本人"
          @input="errorMsg = ''"
        >
      </label>
      <label class="ad-field">
        <span>新密码</span>
        <input
          v-model="form.newPassword"
          type="password"
          autocomplete="new-password"
          placeholder="至少 8 位，不要用纯数字"
          @input="errorMsg = ''"
        >
      </label>
      <label class="ad-field">
        <span>再输一次新密码</span>
        <input
          v-model="form.confirmPassword"
          type="password"
          autocomplete="new-password"
          placeholder="防止手滑输错"
          @input="errorMsg = ''"
        >
      </label>
      <span v-if="errorMsg" class="ad-error">{{ errorMsg }}</span>
      <p class="ad-form__note">
        改完这台设备保持登录，其他设备上的登录状态会立即失效，需要用新密码重新登录。
      </p>
    </form>

    <template #footer>
      <div class="ad-form__acts">
        <button class="ad-btn" type="button" :disabled="submitting" @click="visible = false">
          取消
        </button>
        <button class="ad-btn ad-btn--primary" type="button" :disabled="submitting" @click="handleSubmit">
          {{ submitting ? '正在保存…' : '保存新密码' }}
        </button>
      </div>
    </template>
  </el-dialog>
</template>
