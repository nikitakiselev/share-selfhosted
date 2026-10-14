<script setup lang="ts">
import { Toaster as Sonner } from 'vue-sonner'
import 'vue-sonner/style.css'
</script>

<template>
  <Sonner
    class="toaster group"
    position="bottom-center"
    theme="system"
    :style="{
      '--normal-bg': 'var(--popover)',
      '--normal-text': 'var(--popover-foreground)',
      '--normal-border': 'var(--border)',
      '--border-radius': 'var(--radius)',
    }"
  />
</template>
