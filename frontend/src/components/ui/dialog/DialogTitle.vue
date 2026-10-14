<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { DialogTitle } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DialogTitle :class="cn('pr-6 text-lg leading-snug font-semibold', props.class)">
    <slot />
  </DialogTitle>
</template>
