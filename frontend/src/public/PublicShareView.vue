<script setup lang="ts">
import { Download, LoaderCircle } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { publicApi } from '@/api/public'
import type { PublicFile, PublicShare } from '@/api/types'
import { Button } from '@/components/ui/button'
import Wordmark from '@/components/Wordmark.vue'
import { filesCount, formatDate, formatSize } from '@/lib/format'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import FileTile from './components/FileTile.vue'
import ImageViewer from './components/ImageViewer.vue'
import PasswordGate from './components/PasswordGate.vue'
import StatusScreen from './components/StatusScreen.vue'
import VideoStage from './components/VideoStage.vue'

const props = defineProps<{ slug: string }>()

type Phase = 'loading' | 'ready' | 'locked' | 'not-found' | 'expired' | 'error'

const phase = ref<Phase>('loading')
const share = ref<PublicShare | null>(null)
const expiredAt = ref<number | null>(null)
const errorText = ref('')
const selectedId = ref<string | null>(null)
const autoplay = ref(false)
const imageIndex = ref<number | null>(null)
const playedIds = new Set<string>()
let pollTimer: number | null = null

const POLL_MS = 7000

async function load(quiet = false) {
  if (!quiet) phase.value = 'loading'
  try {
    const data = await publicApi.share(props.slug)
    share.value = data
    if (data.protected && !data.unlocked) {
      phase.value = 'locked'
      return
    }
    phase.value = 'ready'
    if (data.title) document.title = `${data.title} — Share`
    schedulePoll()
  } catch (e) {
    if (quiet && !(e instanceof ApiError && [401, 404, 410].includes(e.status))) {
      schedulePoll()
      return
    }
    if (e instanceof ApiError && e.status === 404) phase.value = 'not-found'
    else if (e instanceof ApiError && e.status === 410) {
      expiredAt.value = typeof e.data.expired_at === 'number' ? e.data.expired_at : null
      phase.value = 'expired'
    } else if (e instanceof ApiError && e.status === 401) phase.value = 'locked'
    else {
      errorText.value = e instanceof Error ? e.message : ''
      phase.value = 'error'
    }
  }
}

function schedulePoll() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
  const list = share.value?.files ?? []
  const busy = !list.length || list.some((f) => f.status === 'uploading' || f.media_status === 'pending')
  if (busy) pollTimer = window.setTimeout(() => void load(true), POLL_MS)
}

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})

watch(
  () => props.slug,
  () => {
    selectedId.value = null
    void load()
  },
  { immediate: true },
)

const files = computed(() => share.value?.files ?? [])
const videos = computed(() => files.value.filter((f) => f.kind === 'video'))
const images = computed(() => files.value.filter((f) => f.kind === 'image' && f.status === 'ready'))
const readyCount = computed(() => files.value.filter((f) => f.status === 'ready').length)

const current = computed<PublicFile | null>(() => {
  if (!videos.value.length) return null
  return videos.value.find((v) => v.id === selectedId.value) ?? videos.value[0] ?? null
})

/** A single image without video is shown large on the stage. */
const soloImage = computed(() => (files.value.length === 1 && images.value.length === 1 ? images.value[0] : null))
const showGrid = computed(() => files.value.length > 1 || (!current.value && !soloImage.value))

const meta = computed(() => {
  const s = share.value
  if (!s) return ''
  return `${filesCount(s.file_count ?? files.value.length)}, ${formatSize(s.total_size ?? 0)}`
})

const expiry = computed(() => {
  const s = share.value
  if (!s) return ''
  return s.expires_at ? t('public.availableUntil', { date: formatDate(s.expires_at) }) : t('public.noExpiry')
})

function open(file: PublicFile) {
  if (file.kind === 'video') {
    selectedId.value = file.id
    autoplay.value = true
    document.getElementById('stage')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } else if (file.kind === 'image') {
    imageIndex.value = images.value.findIndex((i) => i.id === file.id)
  }
}

function onPlayed(fileId: string) {
  if (playedIds.has(fileId)) return
  playedIds.add(fileId)
  publicApi.played(props.slug, fileId)
}
</script>

<template>
  <div v-if="phase === 'loading'" class="flex min-h-dvh items-center justify-center text-muted-foreground">
    <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
  </div>

  <PasswordGate v-else-if="phase === 'locked'" :slug="slug" @unlocked="load()" />

  <StatusScreen
    v-else-if="phase === 'not-found'"
    :title="t('common.linkNotFound')"
    :text="t('public.notFoundText')"
  />

  <StatusScreen
    v-else-if="phase === 'expired'"
    :title="t('public.expiredTitle')"
    :text="expiredAt ? t('public.expiredAt', { date: formatDate(expiredAt) }) : t('public.expiredText')"
  />

  <StatusScreen v-else-if="phase === 'error'" :title="t('public.errorTitle')" :text="errorText || t('public.noConnection')">
    <Button variant="outline" @click="load()">{{ t('common.retry') }}</Button>
  </StatusScreen>

  <main v-else-if="share" class="min-h-dvh pb-16">
    <header class="mx-auto max-w-6xl px-5 pt-6 sm:px-8">
      <Wordmark class="text-muted-foreground" />
    </header>

    <section class="mx-auto max-w-6xl px-5 pt-10 pb-8 sm:px-8 sm:pt-14">
      <h1
        class="max-w-[22ch] font-display text-[clamp(1.75rem,4.6vw,3.1rem)] leading-[1.06] font-semibold tracking-[-0.022em] break-words"
      >
        {{ share.title || t('public.files') }}
      </h1>
      <div class="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3">
        <p class="tabular text-muted-foreground">{{ meta }}</p>
        <p class="text-muted-foreground">{{ expiry }}</p>
        <Button v-if="readyCount > 1" as="a" :href="publicApi.zipUrl(slug)" download variant="outline" class="sm:ml-auto">
          <Download />
          {{ t('public.downloadAll') }}
        </Button>
      </div>
    </section>

    <section v-if="current" id="stage" class="scroll-mt-4 bg-stage sm:py-8">
      <div class="mx-auto max-w-6xl sm:px-8">
        <VideoStage :file="current" :autoplay="autoplay" @played="onPlayed" />
      </div>
    </section>
    <div v-if="current" class="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 pt-4 sm:px-8">
      <p class="min-w-0 flex-1 font-medium break-words">{{ current.name }}</p>
      <Button v-if="current.download_url" as="a" :href="current.download_url" download variant="secondary">
        <Download />
        {{ t('file.downloadSize', { size: formatSize(current.size) }) }}
      </Button>
    </div>

    <template v-else-if="soloImage">
      <section class="bg-stage sm:py-8">
        <button
          type="button"
          class="mx-auto block max-w-6xl outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60 sm:px-8"
          :aria-label="t('public.openFullscreen', { name: soloImage.name })"
          @click="imageIndex = 0"
        >
          <img
            :src="(/^image\/(jpeg|png|gif|webp|avif)$/.test(soloImage.mime) ? soloImage.url : soloImage.poster_url) ?? undefined"
            :alt="soloImage.name"
            class="mx-auto max-h-[78vh] w-auto object-contain"
          />
        </button>
      </section>
      <div class="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 pt-4 sm:px-8">
        <p class="min-w-0 flex-1 font-medium break-words">{{ soloImage.name }}</p>
        <Button v-if="soloImage.download_url" as="a" :href="soloImage.download_url" download variant="secondary">
          <Download />
          {{ t('file.downloadSize', { size: formatSize(soloImage.size) }) }}
        </Button>
      </div>
    </template>

    <section v-if="showGrid" class="mx-auto max-w-6xl px-5 sm:px-8" :class="current || soloImage ? 'pt-12' : 'pt-2'">
      <h2 v-if="current && files.length > 1" class="sr-only">{{ t('public.allFiles') }}</h2>
      <div class="grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-4">
        <FileTile v-for="file in files" :key="file.id" :file="file" :selected="file.id === current?.id" @open="open" />
      </div>
    </section>

    <p v-if="!files.length" class="mx-auto max-w-6xl px-5 text-muted-foreground sm:px-8">
      {{ t('public.empty') }}
    </p>

    <ImageViewer v-model:index="imageIndex" :images="images" />
  </main>
</template>
