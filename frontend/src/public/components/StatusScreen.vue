<script setup lang="ts">
import Wordmark from '@/components/Wordmark.vue'

defineProps<{ title: string; text?: string }>()
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-xl flex-col px-5 py-6 sm:px-8">
    <Wordmark class="text-muted-foreground" />
    <div class="flex flex-1 flex-col justify-center pb-[12vh]">
      <h1 class="font-display text-[clamp(1.6rem,5vw,2.4rem)] leading-[1.1] font-semibold tracking-[-0.015em]">
        {{ title }}
      </h1>
      <p v-if="text" class="mt-4 max-w-[46ch] text-lg leading-relaxed text-muted-foreground">{{ text }}</p>
      <div class="mt-8 empty:hidden"><slot /></div>
    </div>
  </main>
</template>
