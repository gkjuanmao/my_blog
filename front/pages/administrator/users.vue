<script setup lang="ts">
/**
 * 用户管理：账号台账（筛选 + 分页）与右侧操作面板。
 *
 * 权限口径：后端 `/admin/users/**` 只对 is_superuser 开放，staff 会收到 403；
 * 这里只负责把 403 显示成明确提示，不做本地权限猜测（真正的门在服务端）。
 *
 * 在线状态由服务端算好（`online` 字段），前端只负责展示「多久没活跃」，
 * 并且每 30 秒刷新一次 —— 窗口是 900 秒，刷新间隔比窗口小一个量级即可。
 */
import type { AdminUser, PaginatedResponse } from '~/types/api'

definePageMeta({ layout: 'admin' })

const api = useApi()

const users = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const errorMsg = ref('')

const keyword = ref('')
const activeFilter = ref<'all' | 'yes' | 'no'>('all')

async function fetchUsers() {
  loading.value = true
  errorMsg.value = ''
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize.value,
      // 默认按最近活跃倒序：谁刚用过后台，一眼就能看到
      ordering: '-last_seen_at',
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (activeFilter.value !== 'all') params.is_active = activeFilter.value === 'yes'

    const { data } = await api.get<PaginatedResponse<AdminUser>>('/admin/users/', params)
    users.value = data.items
    total.value = data.total
  } catch (e) {
    users.value = []
    total.value = 0
    errorMsg.value = errorMessage(e, '加载用户失败')
  } finally {
    loading.value = false
  }
}

const onlineCount = computed(() => users.value.filter(user => user.online).length)
const articleSum = computed(() => users.value.reduce((sum, user) => sum + user.article_count, 0))
const meta = computed(
  () =>
    `${total.value} 个账号 · 本页 ${onlineCount.value} 人在线 · 本页名下 ${articleSum.value} 篇稿件`,
)

watch([page, pageSize, activeFilter], fetchUsers)

// 30 秒轮询：登录态是会被动的（对方可能刚退出），不刷新就看不出「在线」变化。
// 标签页不可见时跳过，避免后台标签页白发请求。
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  fetchUsers()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') fetchUsers()
  }, 30_000)
})
onBeforeUnmount(() => clearInterval(timer))

function changeFilter(value: 'all' | 'yes' | 'no') {
  if (activeFilter.value === value) return
  activeFilter.value = value
  page.value = 1
}

function onSearch() {
  page.value = 1
  fetchUsers()
}
</script>

<template>
  <div class="ad-page">
    <AdminMasthead eyebrow="用户" eyebrow-en="Accounts" title="用户管理" :meta="meta">
      <template #actions>
        <button class="ad-btn ad-btn--ghost" type="button" :disabled="loading" @click="fetchUsers">
          <AdminIcon name="refresh" :size="14" />刷新
        </button>
      </template>
    </AdminMasthead>

    <div class="ad-toolbar">
      <label class="ad-tool" style="width: 220px">
        <AdminIcon name="search" :size="14" />
        <input
          v-model="keyword"
          type="search"
          placeholder="用户名或邮箱"
          aria-label="搜索账号"
          @keyup.enter="onSearch"
        >
      </label>

      <div class="ad-segs" role="group" aria-label="按启用状态筛选">
        <button class="ad-seg" type="button" :aria-pressed="activeFilter === 'all'" @click="changeFilter('all')">
          全部
        </button>
        <button class="ad-seg" type="button" :aria-pressed="activeFilter === 'yes'" @click="changeFilter('yes')">
          启用中
        </button>
        <button class="ad-seg" type="button" :aria-pressed="activeFilter === 'no'" @click="changeFilter('no')">
          已停用
        </button>
      </div>

      <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="onSearch">查询</button>

      <span class="ad-toolbar__spacer" />
      <span class="ad-toolbar__note">在线判定：最近 15 分钟有操作 · 每 30 秒刷新</span>
    </div>

    <div v-if="errorMsg" class="ad-void" style="flex: 1">
      <p class="ad-error" role="alert">{{ errorMsg }}</p>
      <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="fetchUsers">重试</button>
    </div>

    <template v-else>
      <UserDirectory :users="users" :total="total" :loading="loading" @changed="fetchUsers" />
      <AdminPager v-model:page="page" v-model:page-size="pageSize" :total="total" unit="个" />
    </template>
  </div>
</template>
