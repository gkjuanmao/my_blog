<script setup lang="ts">
/**
 * 批量转移文章归属（仅超管）。
 *
 * 场景：别人代传的稿件先挂在代传者名下，事后要一次性划回真正的作者。
 * 单篇转移在编辑台的「作者」下拉里做；这里是「选中一批 → 统一划走」。
 *
 * 只列**启用中**的用户：停用账号无法登录，把稿子划过去等于让它消失。
 */
import type { AdminUser } from '~/types/api'

const visible = defineModel<boolean>({ required: true })

const props = defineProps<{
  /** 当前勾选的稿件 id */
  ids: number[]
}>()

const emit = defineEmits<{ done: [] }>()

const api = useApi()
const users = ref<AdminUser[]>([])
const targetId = ref<number | null>(null)
const loading = ref(false)
const submitting = ref(false)
const errorMsg = ref('')

watch(visible, async (open) => {
  if (!open) return
  targetId.value = null
  errorMsg.value = ''
  loading.value = true
  try {
    const { data } = await api.get<AdminUser[] | { items: AdminUser[] }>('/admin/users/', {
      page_size: 100,
      ordering: 'username',
    })
    // 列表端点是分页信封；这里做一次兼容，避免依赖具体形状
    const list = Array.isArray(data) ? data : data.items
    users.value = list.filter(user => user.is_active)
  } catch (e) {
    errorMsg.value = errorMessage(e, '用户列表加载失败')
  } finally {
    loading.value = false
  }
})

async function submit() {
  if (targetId.value == null) {
    errorMsg.value = '请选择目标作者'
    return
  }
  const target = users.value.find(user => user.id === targetId.value)
  try {
    await ElMessageBox.confirm(
      `确定把选中的 ${props.ids.length} 篇稿件划给「${target?.username ?? ''}」吗？`,
      '转移归属',
      { type: 'warning', confirmButtonText: '确认转移', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  submitting.value = true
  errorMsg.value = ''
  try {
    const { data } = await api.post<{ moved: number; author_name: string; not_found: number[] }>(
      '/admin/articles/bulk-author/',
      { ids: props.ids, author_id: targetId.value },
    )
    if (data.not_found?.length) {
      ElMessage.warning(
        `已转移 ${data.moved} 篇给「${data.author_name}」；${data.not_found.length} 篇已不存在`,
      )
    } else {
      ElMessage.success(`已把 ${data.moved} 篇转给「${data.author_name}」`)
    }
    visible.value = false
    emit('done')
  } catch (e) {
    errorMsg.value = errorMessage(e, '转移失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="转移文章归属" width="min(460px, 92vw)">
    <p class="ad-note">
      选中的 <b>{{ ids.length }}</b> 篇会划给下面这个作者；原作者会失去这些稿件的归属。
      操作会记入审计（谁在什么时候改的）。
    </p>

    <el-select
      v-model="targetId"
      filterable
      placeholder="选择目标作者"
      :loading="loading"
      style="width: 100%; margin-top: 14px"
    >
      <el-option
        v-for="user in users"
        :key="user.id"
        :label="`${user.username}（${user.article_count} 篇）`"
        :value="user.id"
      />
    </el-select>

    <p v-if="errorMsg" class="ad-note ad-note--bad">{{ errorMsg }}</p>

    <template #footer>
      <el-button :disabled="submitting" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认转移</el-button>
    </template>
  </el-dialog>
</template>
