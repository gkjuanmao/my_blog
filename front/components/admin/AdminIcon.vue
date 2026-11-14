<script setup lang="ts">
/**
 * 后台图标（18×18 网格、1.5 描边、纯 path）。
 *
 * 为什么不用雪碧图 + `<use>`：`<use>` 引用 `<g>` 时若宿主 `<svg>` 没写 viewBox，
 * 用户坐标等于 CSS 像素，14px 的图标里超出 14 单位的笔画会被直接裁掉（刷新图标的
 * 半圈和箭头就是这么丢的）。这里每个图标都自带 viewBox，按需缩放都完整。
 */
import type { AdminIconName } from '~/types/admin'

const props = withDefaults(defineProps<{ name: AdminIconName; size?: number }>(), { size: 16 })

const ICONS: Record<AdminIconName, string[]> = {
  grid: [
    'M3.5 2.5h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
    'M11.5 2.5h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
    'M3.5 10.5h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
    'M11.5 10.5h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
  ],
  doc: ['M4 2.5h6.5L14 6v9.5H4z', 'M10.5 2.5V6H14', 'M6.5 9.5h5M6.5 12.5h3.5'],
  folder: [
    'M2.5 5.5A1.5 1.5 0 0 1 4 4h3l1.5 2H14a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 14 14H4a1.5 1.5 0 0 1-1.5-1.5z',
  ],
  hash: ['M6.5 2.5 4.5 15.5M13.5 2.5l-2 13M2.5 6.5h13M1.8 11.5h13'],
  clock: ['M15.5 9a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0', 'M9 5.2V9l2.6 1.6'],
  users: [
    'M9.6 6.4a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0',
    'M2.4 15c0-2.4 2-4.1 4.6-4.1s4.6 1.7 4.6 4.1',
    'M12.6 4.2a2.4 2.4 0 0 1 0 4.6',
    'M14 14.9c0-1.5-.5-2.6-1.4-3.3',
  ],
  search: ['M13.2 8a5.2 5.2 0 1 1-10.4 0 5.2 5.2 0 0 1 10.4 0', 'm12 12 4 4'],
  plus: ['M9 3.5v11M3.5 9h11'],
  menu: ['M2.5 4.5h13M2.5 9h13M2.5 13.5h9'],
  ext: ['M7 3.5H3.5v11h11V11', 'M10.5 3.5H16V9M16 3.5 8.5 11'],
  key: [
    'M8.2 12.8a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    'm7.3 10.7 6.4-6.4M11.9 6.1l1.7 1.7M13.5 4.5l1.7 1.7',
  ],
  out: ['M11 2.5H3.5v13H11', 'M7.8 9h8.2M13.2 6.1 16.1 9l-2.9 2.9'],
  close: ['m4 4 10 10M14 4 4 14'],
  download: ['M9 3v8m0 0 3-3m-3 3L6 8', 'M3.5 13.5v1h11v-1'],
  refresh: ['M15.2 9a6.2 6.2 0 1 1-1.9-4.5', 'M15.4 2.6v3.6h-3.6'],
}

const paths = computed(() => ICONS[props.name] ?? [])
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 18 18"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, index) in paths" :key="index" :d="d" />
  </svg>
</template>
