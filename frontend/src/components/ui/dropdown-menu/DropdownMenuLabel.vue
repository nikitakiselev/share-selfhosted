<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { DropdownMenuLabel } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DropdownMenuLabel :class="cn('px-2.5 py-1.5 text-sm', props.class)">
    <slot />
  </DropdownMenuLabel>
</template>
