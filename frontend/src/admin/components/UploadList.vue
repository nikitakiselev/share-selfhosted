<script setup lang="ts">
import type { UploadItem } from '@/upload/engine'
import UploadRow from './UploadRow.vue'

defineProps<{ items: UploadItem[] }>()
</script>

<template>
  <ul v-if="items.length" class="divide-y">
    <UploadRow v-for="item in items" :key="item.key" :item="item" />
  </ul>
</template>
