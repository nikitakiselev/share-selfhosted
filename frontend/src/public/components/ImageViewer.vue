<script setup lang="ts">
import { ChevronLeft, ChevronRight, Download, X } from '@lucide/vue'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { computed } from 'vue'
import type { PublicFile } from '@/api/types'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'

const props = defineProps<{ images: PublicFile[] }>()
const index = defineModel<number | null>('index', { default: null })

const open = computed({
  get: () => index.value !== null,
  set: (value) => {
    if (!value) index.value = null
  },
})
const current = computed(() => (index.value === null ? null : (props.images[index.value] ?? null)))

const BROWSER_IMAGES = /^image\/(jpeg|png|gif|webp|avif)$/
const src = computed(() => {
  const f = current.value
  if (!f) return null
  if (f.url && BROWSER_IMAGES.test(f.mime)) return f.url
  return f.poster_url
})

function step(delta: number) {
  if (index.value === null || props.images.length < 2) return
  index.value = (index.value + delta + props.images.length) % props.images.length
}

let touchX: number | null = null
function onTouchStart(event: TouchEvent) {
  touchX = event.touches[0]?.clientX ?? null
}
function onTouchEnd(event: TouchEvent) {
  const endX = event.changedTouches[0]?.clientX
  if (touchX === null || endX === undefined) return
  const dx = endX - touchX
  touchX = null
  if (Math.abs(dx) > 50) step(dx < 0 ? 1 : -1)
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'ArrowRight') step(1)
  if (event.key === 'ArrowLeft') step(-1)
}
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/92 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogContent
        class="fixed inset-0 z-50 flex flex-col text-white outline-none"
        :aria-describedby="undefined"
        @keydown="onKey"
        @touchstart.passive="onTouchStart"
        @touchend="onTouchEnd"
      >
        <header class="flex items-center gap-3 px-4 py-3 sm:px-6">
          <DialogTitle class="min-w-0 flex-1 truncate text-sm font-medium">{{ current?.name }}</DialogTitle>
          <a
            v-if="current?.download_url"
            :href="current.download_url"
            download
            class="inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm hover:bg-white/10 focus-visible:ring-[3px] focus-visible:ring-white/40 focus-visible:outline-none"
          >
            <Download class="size-4" />
            <span class="hidden sm:inline">{{ t('file.downloadSize', { size: formatSize(current.size) }) }}</span>
          </a>
          <DialogClose
            class="flex size-9 items-center justify-center rounded-md hover:bg-white/10 focus-visible:ring-[3px] focus-visible:ring-white/40 focus-visible:outline-none"
            :aria-label="t('common.close')"
          >
            <X class="size-5" />
          </DialogClose>
        </header>
        <div class="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-4 sm:px-16">
          <img v-if="src" :key="src" :src="src" :alt="current?.name" class="max-h-full max-w-full object-contain" />
          <p v-else class="text-white/70">{{ t('image.unsupported') }}</p>
          <template v-if="images.length > 1">
            <button
              type="button"
              class="absolute top-1/2 left-2 hidden size-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 hover:bg-white/20 focus-visible:ring-[3px] focus-visible:ring-white/40 focus-visible:outline-none sm:flex"
              :aria-label="t('image.prev')"
              @click="step(-1)"
            >
              <ChevronLeft class="size-6" />
            </button>
            <button
              type="button"
              class="absolute top-1/2 right-2 hidden size-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 hover:bg-white/20 focus-visible:ring-[3px] focus-visible:ring-white/40 focus-visible:outline-none sm:flex"
              :aria-label="t('image.next')"
              @click="step(1)"
            >
              <ChevronRight class="size-6" />
            </button>
          </template>
        </div>
        <footer v-if="images.length > 1" class="tabular pb-4 text-center text-sm text-white/60">
          {{ t('common.xOfY', { x: (index ?? 0) + 1, y: images.length }) }}
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
