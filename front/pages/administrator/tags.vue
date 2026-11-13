<script setup lang="ts">
/**
 * 标签管理：索引卡 + 编辑面板（视图见 components/admin/TagIndex.vue）。
 * 标签数量少、没有分页与计数接口，所以不使用列表分页。
 */
import { useCrudTable } from '~/composables/useCrudTable'

definePageMeta({ layout: 'admin' })

const { list, loading, fetchList, submit, remove } = useCrudTable({
  listUrl: '/tags/',
  baseUrl: '/admin/tags',
})

const meta = computed(() => `${list.value.length} 条标签 · 点击标签可直接编辑`)

const tagIndex = ref<{ startCreate: () => void } | null>(null)

onMounted(fetchList)
</script>

<template>
  <div>
    <AdminMasthead eyebrow="标签" eyebrow-en="Index" title="标签管理" :meta="meta">
      <template #actions>
        <button class="ad-btn ad-btn--primary" type="button" @click="tagIndex?.startCreate()">
          新建标签
        </button>
      </template>
    </AdminMasthead>

    <TagIndex
      ref="tagIndex"
      :list="list"
      :loading="loading"
      :submit="submit"
      :remove="remove"
      @changed="fetchList"
    />
  </div>
</template>
