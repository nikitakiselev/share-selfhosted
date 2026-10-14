<script setup lang="ts">
import { t } from '@/lib/i18n'
import StatusScreen from '@/public/components/StatusScreen.vue'
</script>

<template>
  <StatusScreen :title="t('notFound.title')" :text="t('notFound.text')" />
</template>
