<script setup lang="ts">
// Header: how much of the limit is used. Without a limit, the whole disk is shown.
import { computed } from 'vue'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { isOverQuota, quotaRatio } from '@/lib/quota'
import { cn } from '@/lib/utils'
import { currentUsage } from '../usage'

type Tone = 'normal' | 'warning' | 'danger'

const view = computed(() => {
  const u = currentUsage.value
  if (!u) return null
  if (u.quota === null) {
    const d = u.disk
    if (!d?.total) return null
    return {
      left: t('usage.disk', { size: formatSize(d.used) }),
      right: t('common.ofY', { y: formatSize(d.total) }),
      ratio: Math.min(1, d.used / d.total),
      tone: (d.free / d.total < 0.1 ? 'danger' : 'normal') as Tone,
      title: t('usage.diskTitle', { free: formatSize(d.free), used: formatSize(u.used) }),
    }
  }
  const ratio = quotaRatio(u) ?? 0
  return {
    left: formatSize(u.used),
    right: t('common.ofY', { y: formatSize(u.quota) }),
    ratio,
    tone: (isOverQuota(u) || ratio >= 0.95 ? 'danger' : ratio >= 0.8 ? 'warning' : 'normal') as Tone,
    title: t('common.free', { size: formatSize(u.free) }),
  }
})
</script>

<template>
  <div v-if="view" class="w-36 sm:w-44" :title="view.title">
    <p class="tabular flex justify-between gap-2 text-xs text-muted-foreground">
      <span>{{ view.left }}</span>
      <span>{{ view.right }}</span>
    </p>
    <div
      class="mt-1 h-1 overflow-hidden rounded-full bg-muted"
      role="meter"
      :aria-valuenow="Math.round(view.ratio * 100)"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="view.title"
    >
      <div
        :class="
          cn(
            'h-full rounded-full',
            view.tone === 'danger' ? 'bg-destructive' : view.tone === 'warning' ? 'bg-warning' : 'bg-foreground/45',
          )
        "
        :style="{ width: `${view.ratio * 100}%` }"
      />
    </div>
  </div>
</template>
