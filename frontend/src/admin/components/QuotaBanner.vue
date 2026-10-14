<script setup lang="ts">
// The limit is used up: existing files work, new ones can't be uploaded.
import { HardDrive } from '@lucide/vue'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { currentUsage, overQuota } from '../usage'
</script>

<template>
  <section
    v-if="overQuota && currentUsage"
    class="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/6 p-4 sm:p-5"
    role="status"
  >
    <HardDrive class="mt-0.5 size-5 shrink-0 text-destructive" />
    <div>
      <p class="font-medium">{{ t('quota.fullTitle') }}</p>
      <p class="tabular mt-1 text-sm text-muted-foreground">
        {{ t('quota.fullText', { used: formatSize(currentUsage.used), quota: formatSize(currentUsage.quota) }) }}
      </p>
    </div>
  </section>
</template>
