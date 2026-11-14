<script setup lang="ts">
/**
 * 用户台账：左侧账号列表 + 右侧常驻操作面板（新建 / 重置密码 / 转移稿件 / 删除）。
 *
 * 三个交互决定值得说明：
 * 1. 选中行才显示该用户的危险操作，避免「每行三个按钮 + 二次确认」把列表变成地雷阵；
 * 2. 删除遇到 409（对方还有稿件）时，不当成失败处理，而是接着问「强制删除」——
 *    这正是后端要求的显式授权，前端不该把它藏成一个红色 toast；
 * 3. 转移目标只从「已加载的用户」里选。个人博客账号数个位数，翻页找目标属于过度设计，
 *    真到多账号规模时再换成服务端候选接口。
 */
import type { AdminUser } from '~/types/api'

const props = defineProps<{
  users: AdminUser[]
  total: number
  loading: boolean
}>()

const emit = defineEmits<{ changed: [] }>()

const api = useApi()

type Role = 'viewer' | 'editor' | 'owner'

const ROLE_OPTIONS: Array<{ value: Role; label: string; hint: string }> = [
  { value: 'viewer', label: '普通用户', hint: '只能登录，看不到管理台' },
  { value: 'editor', label: '编辑', hint: '可管理文章、分类、标签' },
  { value: 'owner', label: '超级管理员', hint: '可管理账号（等同于你）' },
]

const selectedId = ref<number | null>(null)
const selected = computed(() => props.users.find(user => user.id === selectedId.value) ?? null)

const form = reactive({ username: '', password: '', email: '', role: 'editor' as Role })
const creating = ref(false)
const createError = ref('')

const newPassword = ref('')
const resetting = ref(false)
const resetError = ref('')

const transferTarget = ref<number | null>(null)
const busy = ref(false)

const transferCandidates = computed(() =>
  props.users.filter(user => user.id !== selected.value?.id && user.is_active),
)

function roleLabel(user: AdminUser): string {
  if (user.is_superuser) return '超级管理员'
  return user.is_staff ? '编辑' : '普通用户'
}

function select(id: number) {
  selectedId.value = selectedId.value === id ? null : id
  newPassword.value = ''
  resetError.value = ''
  transferTarget.value = null
}

function roleFlags(role: Role) {
  // 超管必须同时是 staff，否则进不了 Django admin 却又能管理账号，语义混乱（后端同口径）
  return { is_staff: role !== 'viewer', is_superuser: role === 'owner' }
}

async function handleCreate() {
  if (!form.username.trim()) {
    createError.value = '请填写用户名'
    return
  }
  if (form.password.length < 8) {
    createError.value = '初始密码至少 8 位'
    return
  }
  createError.value = ''
  creating.value = true
  const username = form.username.trim()
  try {
    const payload: Record<string, unknown> = {
      username,
      password: form.password,
      email: form.email.trim(),
      is_active: true,
      ...roleFlags(form.role),
    }
    await api.post('/admin/users/', payload)
    ElMessage.success(`用户「${username}」已创建`)
    form.username = ''
    form.password = ''
    form.email = ''
    form.role = 'editor'
    emit('changed')
  } catch (e) {
    createError.value = errorMessage(e, '创建失败')
  } finally {
    creating.value = false
  }
}

async function handleResetPassword() {
  if (!selected.value) return
  if (newPassword.value.length < 8) {
    resetError.value = '新密码至少 8 位'
    return
  }
  resetError.value = ''
  resetting.value = true
  try {
    await api.post(`/admin/users/${selected.value.id}/reset-password/`, {
      password: newPassword.value,
    })
    ElMessage.success('密码已重置，对方的登录状态已失效')
    newPassword.value = ''
  } catch (e) {
    resetError.value = errorMessage(e, '重置失败')
  } finally {
    resetting.value = false
  }
}

async function confirmAndCall(message: string, title: string, run: () => Promise<void>) {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  busy.value = true
  try {
    await run()
  } finally {
    busy.value = false
  }
}

async function deleteUser(user: AdminUser, query = '') {
  try {
    await api.del(`/admin/users/${user.id}/${query}`)
    ElMessage.success(`用户「${user.username}」已删除`)
    if (selectedId.value === user.id) selectedId.value = null
    emit('changed')
  } catch (e) {
    const message = errorMessage(e, '删除失败')
    // 409 是后端的「显式授权」提示：有稿件时必须转移或强制删除
    if (!query && message.includes('篇文章')) {
      await confirmAndCall(
        `${message}。强制删除会连同这些文章的封面与附件一起消失，且不可恢复。`,
        '该用户还有稿件',
        () => deleteUser(user, '?force=true'),
      )
      return
    }
    ElMessage.error(message)
  }
}

function handleDelete(user: AdminUser) {
  return confirmAndCall(
    `删除「${user.username}」后无法恢复，该账号的登录状态会立即失效。`,
    '删除用户',
    () => deleteUser(user),
  )
}

function handleTransferAndDelete(user: AdminUser) {
  const target = transferCandidates.value.find(item => item.id === transferTarget.value)
  if (!target) {
    ElMessage.warning('请选择接收稿件的用户')
    return
  }
  return confirmAndCall(
    `把「${user.username}」名下的 ${user.article_count} 篇稿件转给「${target.username}」，然后删除该账号。`,
    '转移并删除',
    () => deleteUser(user, `?reassign_to=${target.id}`),
  )
}
</script>

<template>
  <div class="ad-split ad-split--wide">
    <div
      class="ad-split__col ad-split__col--flush"
      style="display: flex; flex-direction: column; min-height: 0"
    >
      <div class="ad-tablewrap" style="padding: 0" :class="{ 'ad-loading': loading }" :aria-busy="loading ? 'true' : 'false'">
        <table class="ad-table ad-table--acts">
          <caption class="ad-sr">
            用户列表，共 {{ total }} 个账号
          </caption>
          <thead>
            <tr>
              <th>账号</th>
              <th style="width: 106px">角色</th>
              <th style="width: 92px">状态</th>
              <th class="ad-col-md" style="width: 110px">最近活跃</th>
              <th class="num r" style="width: 62px">稿件</th>
              <th style="width: 72px"><span class="ad-sr">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in users"
              :key="user.id"
              :class="{ 'is-selected': selectedId === user.id }"
            >
              <td>
                <div class="ad-u-cell">
                  <span class="ad-u-avatar" :class="{ 'is-on': user.online && user.is_active }" aria-hidden="true">
                    {{ user.username.charAt(0) }}
                  </span>
                  <span style="min-width: 0">
                    <span class="ad-u-name">{{ user.username }}</span>
                    <span class="ad-u-mail">{{ user.email || '未填邮箱' }}</span>
                  </span>
                </div>
              </td>
              <td>
                <span :class="{ 'ad-role--pine': user.is_superuser }">{{ roleLabel(user) }}</span>
              </td>
              <td>
                <span
                  class="ad-status"
                  :class="{
                    'ad-status--off': user.is_active && !user.online,
                    'ad-status--stop': !user.is_active,
                  }"
                >
                  <i aria-hidden="true" />
                  {{ !user.is_active ? '已停用' : user.online ? '在线' : '离线' }}
                </span>
              </td>
              <td class="ad-table__date ad-col-md">{{ formatRelativeTime(user.last_seen_at) }}</td>
              <td class="num r">{{ user.article_count }}</td>
              <td class="ad-table__acts">
                <button class="ad-link" type="button" @click.stop="select(user.id)">
                  {{ selectedId === user.id ? '收起' : '管理' }}
                </button>
              </td>
            </tr>
            <tr v-if="!users.length">
              <td colspan="6">
                <p class="ad-rows-empty">
                  {{ loading ? '正在加载账号…' : '没有符合条件的账号。' }}
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="users.length" class="ad-void">
        <p>账号按最近活跃排序，每 30 秒自动刷新。</p>
        <span>本项目没有公开注册入口，账号都在右侧创建</span>
      </div>
    </div>

    <aside class="ad-split__aside ad-split__aside--flush">
      <template v-if="selected">
        <p class="ad-panel__eyebrow">账号设置</p>
        <h2 class="ad-panel__title">{{ selected.username }}</h2>
        <p class="ad-panel__hint">
          {{ roleLabel(selected) }} · {{ !selected.is_active ? '已停用' : selected.online ? '在线' : '离线' }}
        </p>

        <dl class="ad-facts">
          <div><dt>注册时间</dt><dd>{{ formatDateCompact(selected.date_joined) }}</dd></div>
          <div><dt>最近登录</dt><dd>{{ formatRelativeTime(selected.last_login) }}</dd></div>
          <div><dt>最近活跃</dt><dd>{{ formatRelativeTime(selected.last_seen_at) }}</dd></div>
          <div><dt>名下稿件</dt><dd>{{ selected.article_count }} 篇</dd></div>
        </dl>

        <form class="ad-form" style="margin-top: 18px" @submit.prevent="handleResetPassword">
          <label class="ad-field">
            <span>重置密码</span>
            <input
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              placeholder="至少 8 位，手动指定"
              @input="resetError = ''"
            >
            <span v-if="resetError" class="ad-error">{{ resetError }}</span>
            <span class="ad-hint">保存后该账号已签发的令牌立即失效</span>
          </label>
          <div class="ad-form__acts">
            <button class="ad-btn ad-btn--primary" type="submit" :disabled="resetting || busy">
              {{ resetting ? '正在重置…' : '重置密码' }}
            </button>
          </div>
        </form>

        <div v-if="selected.article_count" class="ad-panel__danger">
          <p>
            该账号名下有 {{ selected.article_count }} 篇稿件。直接把稿件转给其他人再删除，
            比强制删掉更安全。
          </p>
          <label class="ad-field" style="margin-top: 10px">
            <span>转移稿件给</span>
            <select v-model="transferTarget">
              <option :value="null">选择账号</option>
              <option v-for="user in transferCandidates" :key="user.id" :value="user.id">
                {{ user.username }}
              </option>
            </select>
          </label>
          <div class="ad-form__acts" style="margin-top: 10px">
            <button
              class="ad-btn ad-btn--danger ad-btn--sm"
              type="button"
              :disabled="busy"
              @click="handleTransferAndDelete(selected)"
            >
              转移并删除
            </button>
          </div>
        </div>

        <div v-if="!selected.article_count" class="ad-panel__danger">
          <p>删除后无法恢复，该账号的登录状态会立即失效。</p>
          <div class="ad-form__acts" style="margin-top: 10px">
            <button
              class="ad-btn ad-btn--danger ad-btn--sm"
              type="button"
              :disabled="busy"
              @click="handleDelete(selected)"
            >
              删除该账号
            </button>
          </div>
        </div>

        <p class="ad-panel__note">
          重置密码后，对方已签发的令牌立即失效，需要用新密码重新登录。<br>
          删除或停用当前登录的账号会被服务端拒绝 —— 这是防止把自己锁在门外。
        </p>
      </template>

      <template v-else>
        <p class="ad-panel__eyebrow">新建账号</p>
        <h2 class="ad-panel__title">开一个新账号</h2>
        <p class="ad-panel__hint">本项目没有公开注册，账号只能在这里创建</p>

        <form class="ad-form" style="margin-top: 16px" @submit.prevent="handleCreate">
          <label class="ad-field">
            <span>用户名</span>
            <input
              v-model="form.username"
              type="text"
              autocomplete="off"
              placeholder="字母、数字、汉字，3 位以上"
              @input="createError = ''"
            >
          </label>
          <label class="ad-field">
            <span>初始密码</span>
            <input
              v-model="form.password"
              type="password"
              autocomplete="new-password"
              placeholder="至少 8 位，不要用纯数字"
              @input="createError = ''"
            >
          </label>
          <label class="ad-field">
            <span>邮箱（可选）</span>
            <input
              v-model="form.email"
              type="email"
              autocomplete="off"
              placeholder="用于联系，可留空"
              @input="createError = ''"
            >
          </label>
          <label class="ad-field">
            <span>角色</span>
            <select v-model="form.role">
              <option v-for="option in ROLE_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <span class="ad-hint">{{ ROLE_OPTIONS.find(option => option.value === form.role)?.hint }}</span>
          </label>
          <span v-if="createError" class="ad-error">{{ createError }}</span>
          <div class="ad-form__acts">
            <button class="ad-btn ad-btn--primary" type="submit" :disabled="creating">
              {{ creating ? '创建中…' : '创建账号' }}
            </button>
          </div>
        </form>

        <p class="ad-panel__note">
          选中左侧任一账号可重置密码、转移稿件或删除。
        </p>
      </template>
    </aside>
  </div>
</template>
