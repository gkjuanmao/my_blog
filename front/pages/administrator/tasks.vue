<script setup lang="ts">
/**
 * 导入任务页：把归档导入的异步执行结果集中在一处。
 *
 * 只做一个壳（布局 + 标题），台账在 `components/admin/ImportTaskList.vue`；
 * 轮询由 `composables/useImportTasks.ts` 的单例负责，与本页是否可见无关——
 * 关掉这个页面，右下角的完成通知照样会来。
 *
 * 注意组件标签：本项目 `components` 配了 `pathPrefix: false`，
 * `components/admin/ImportTaskList.vue` 的标签是 `<ImportTaskList>`。
 */
definePageMeta({ layout: 'admin' })
</script>

<template>
  <ImportTaskList />
</template>
