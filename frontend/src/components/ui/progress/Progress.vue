<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { ProgressIndicator, ProgressRoot } from 'reka-ui'
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    modelValue?: number | null
    max?: number
    class?: HTMLAttributes['class']
    indicatorClass?: HTMLAttributes['class']
  }>(),
  { modelValue: 0, max: 100 },
)

const percent = computed(() => {
  const v = props.modelValue ?? 0
  return Math.min(100, Math.max(0, (v / props.max) * 100))
})
</script>

<template>
  <ProgressRoot
    data-slot="progress"
    :model-value="modelValue"
    :max="max"
    :class="cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', props.class)"
  >
    <ProgressIndicator
      data-slot="progress-indicator"
      :class="cn('h-full w-full flex-1 rounded-full bg-primary transition-transform duration-300 ease-out', indicatorClass)"
      :style="`transform: translateX(-${100 - percent}%);`"
    />
  </ProgressRoot>
</template>
