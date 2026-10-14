<script setup lang="ts">
import { Download, LoaderCircle } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'
import type { PublicFile } from '@/api/types'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'

const props = defineProps<{ file: PublicFile; autoplay?: boolean }>()
const emit = defineEmits<{ played: [fileId: string] }>()

const video = ref<HTMLVideoElement | null>(null)
const failed = ref(false)

watch(
  () => props.file.id,
  () => {
    failed.value = false
  },
)

watch(
  () => [props.file.id, props.autoplay, props.file.play_url] as const,
  async ([, autoplay, url]) => {
    if (!autoplay || !url) return
    await nextTick()
    video.value?.play().catch(() => {})
  },
)

const aspect = computed(() => {
  const { width, height } = props.file
  return width && height ? `${width} / ${height}` : '16 / 9'
})

type Mode = 'play' | 'pending' | 'unsupported'
const mode = computed<Mode>(() => {
  if (props.file.status === 'uploading' || props.file.media_status === 'pending') return 'pending'
  if (!props.file.play_url || failed.value) return 'unsupported'
  return 'play'
})

function onMetadata() {
  // HEVC without a hardware decoder: sound but no picture. Treat it as a failure.
  const el = video.value
  if (el && props.file.width && el.videoWidth === 0) failed.value = true
}
</script>

<template>
  <div
    class="relative mx-auto w-full max-h-[78vh] overflow-hidden bg-black sm:rounded-xl"
    :style="{ aspectRatio: aspect, maxWidth: `calc(78vh * ${aspect.replace(' / ', '/')})` }"
  >
    <video
      v-if="mode === 'play'"
      :key="file.id"
      ref="video"
      class="size-full bg-black object-contain"
      controls
      playsinline
      preload="metadata"
      :poster="file.poster_url ?? undefined"
      :src="file.play_url ?? undefined"
      @play="emit('played', file.id)"
      @error="failed = true"
      @loadedmetadata="onMetadata"
    />
    <template v-else>
      <img
        v-if="file.poster_url"
        :src="file.poster_url"
        alt=""
        class="absolute inset-0 size-full object-contain opacity-50"
      />
      <div class="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/55 px-6 text-center text-white">
        <template v-if="mode === 'pending'">
          <LoaderCircle class="size-7 animate-spin opacity-80" />
          <p class="max-w-[34ch] text-base sm:text-lg">
            {{ file.status === 'uploading' ? t('video.uploading') : t('video.processing') }}
          </p>
          <p class="text-sm text-white/60">{{ t('video.autoRefresh') }}</p>
        </template>
        <template v-else>
          <p class="max-w-[36ch] text-base sm:text-lg">{{ t('video.unsupported') }}</p>
          <a
            v-if="file.download_url"
            :href="file.download_url"
            download
            class="inline-flex h-10 items-center gap-2 rounded-md bg-white px-4 text-sm font-medium text-black hover:bg-white/90 focus-visible:ring-[3px] focus-visible:ring-white/50 focus-visible:outline-none"
          >
            <Download class="size-4" />
            {{ t('file.downloadSize', { size: formatSize(file.size) }) }}
          </a>
        </template>
      </div>
    </template>
  </div>
</template>
