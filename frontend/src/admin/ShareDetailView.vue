<script setup lang="ts">
import { ArrowLeft, LoaderCircle, Pencil, Trash2 } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { appApi } from '@/api/app'
import type { AdminFile, AdminShareDetail, AdminShareSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { filesCount, formatDuration, formatRelative, formatSize } from '@/lib/format'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import { addFiles, cancelUpload, dropShare, useUploads } from '@/upload/engine'
import type { PickedFile } from '@/upload/handles'
import ConfirmDialog from './components/ConfirmDialog.vue'
import DropZone from './components/DropZone.vue'
import EventLog from './components/EventLog.vue'
import LinkCard from './components/LinkCard.vue'
import LiveSettings from './components/LiveSettings.vue'
import QuotaBanner from './components/QuotaBanner.vue'
import RenameInput from './components/RenameInput.vue'
import ResumeBanner from './components/ResumeBanner.vue'
import UploadList from './components/UploadList.vue'
import { admitFiles } from './quotaGate'
import { handleAuthError } from './session'
import { overQuota } from './usage'

const props = defineProps<{ slug: string }>()
const router = useRouter()
const { state, waiting } = useUploads()

const detail = ref<AdminShareDetail | null>(null)
const notFound = ref(false)
const error = ref('')
const fileToDelete = ref<AdminFile | null>(null)
const renamingId = ref<string | null>(null)
const deleteShareOpen = ref(false)
const dropzone = ref<InstanceType<typeof DropZone> | null>(null)
let timer: number | null = null

/** This link's uploads that are still running (or waiting) — the engine shows them. */
const localItems = computed(() =>
  state.items.filter(
    (i) => i.shareSlug === props.slug && i.status !== 'done' && i.status !== 'processing' && i.status !== 'needs-file',
  ),
)
const localFileIds = computed(() => new Set(localItems.value.map((i) => i.fileId).filter(Boolean)))
const files = computed(() => (detail.value?.files ?? []).filter((f) => !localFileIds.value.has(f.id)))

const busy = computed(
  () =>
    localItems.value.length > 0 ||
    (detail.value?.files ?? []).some((f) => f.status === 'uploading' || f.media_status === 'pending'),
)

async function load() {
  try {
    detail.value = await appApi.share(props.slug)
    document.title = `${detail.value.display_title} — Share`
    error.value = ''
  } catch (e) {
    if (handleAuthError(e)) return
    if (e instanceof ApiError && e.status === 404) notFound.value = true
    else error.value = e instanceof Error ? e.message : t('detail.loadFailed')
  } finally {
    schedule()
  }
}

function schedule() {
  if (timer !== null) window.clearTimeout(timer)
  timer = notFound.value ? null : window.setTimeout(() => void load(), busy.value ? 5000 : 30_000)
}

watch(
  () => props.slug,
  () => {
    detail.value = null
    notFound.value = false
    void load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})

// An upload finished — refresh the file list and counters right away.
watch(
  () => state.items.filter((i) => i.shareSlug === props.slug && (i.status === 'processing' || i.status === 'done')).length,
  () => void load(),
)

function onUpdated(summary: AdminShareSummary) {
  if (detail.value) detail.value = { ...detail.value, ...summary }
}

// The limit is used up — no new files, but resuming interrupted uploads isn't blocked.
const blocked = computed(() => overQuota.value && !waiting.value.length)

function onFiles(all: PickedFile[]) {
  const picked = admitFiles(all)
  if (!picked.length) return
  const { resumed } = addFiles(props.slug, picked)
  if (resumed) toast.success(resumed === 1 ? t('upload.resumedOne') : t('upload.resumedMany', { count: resumed }))
}

type Tone = 'success' | 'accent' | 'secondary' | 'warning' | 'destructive'
function fileBadge(file: AdminFile): { text: string; tone: Tone; spin?: boolean } | null {
  if (file.status === 'uploading') {
    const pct = file.uploaded && file.size ? Math.floor((file.uploaded / file.size) * 100) : 0
    return { text: t('detail.partial', { percent: pct }), tone: 'warning' }
  }
  if (file.media_status === 'pending') return { text: t('detail.processing'), tone: 'warning', spin: true }
  if (file.media_status === 'failed') return { text: t('detail.processingFailed'), tone: 'destructive' }
  if (file.kind !== 'video' && file.kind !== 'audio') return null
  if (file.play === 'original') return { text: t('detail.playsOriginal'), tone: 'success' }
  if (file.play === 'remux') return { text: t('detail.remuxed'), tone: 'accent' }
  return { text: t('detail.downloadOnly'), tone: 'secondary' }
}

function fileMeta(file: AdminFile): string {
  const parts = [formatSize(file.size)]
  if (file.duration) parts.push(formatDuration(file.duration))
  if (file.width && file.height) parts.push(`${file.width}×${file.height}`)
  const codecs = [file.video_codec, file.audio_codec].filter(Boolean).join(' + ')
  if (codecs) parts.push(codecs)
  return parts.join(', ')
}

async function renameFile(file: AdminFile, name: string) {
  renamingId.value = null
  if (!name || name === file.name) return
  try {
    const updated = await appApi.renameFile(props.slug, file.id, name)
    if (detail.value) detail.value.files = detail.value.files.map((f) => (f.id === file.id ? updated : f))
    // the first file name is the link's default title
    await load()
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('file.renameFailed'))
  }
}

async function deleteFile() {
  const file = fileToDelete.value
  if (!file) return
  try {
    const local = state.items.find((i) => i.fileId === file.id)
    if (local) await cancelUpload(local.key)
    await appApi.deleteFile(props.slug, file.id)
    toast.success(t('detail.fileDeleted'))
    await load()
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('detail.deleteFileFailed'))
  }
}

async function deleteShare() {
  try {
    await appApi.deleteShare(props.slug)
    await dropShare(props.slug)
    toast.success(t('common.linkDeleted'))
    await router.push({ name: 'shares' })
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('detail.deleteLinkFailed'))
  }
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-4 py-8 sm:px-8">
    <RouterLink
      :to="{ name: 'shares' }"
      class="mb-5 inline-flex items-center gap-1.5 rounded text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <ArrowLeft class="size-4" />
      {{ t('page.shares') }}
    </RouterLink>

    <div v-if="notFound" class="rounded-xl border border-dashed px-6 py-16 text-center">
      <p class="font-medium">{{ t('detail.notFoundTitle') }}</p>
      <p class="mt-1 text-muted-foreground">{{ t('detail.notFoundText') }}</p>
    </div>

    <p v-else-if="error && !detail" class="text-destructive">{{ error }}</p>

    <div v-else-if="!detail" class="flex justify-center py-16 text-muted-foreground">
      <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
    </div>

    <div v-else class="space-y-6">
      <h1 class="font-display text-[clamp(1.4rem,3vw,2rem)] leading-tight font-semibold tracking-[-0.015em] break-words">
        {{ detail.display_title }}
      </h1>
      <LinkCard :url="detail.url" />
      <ResumeBanner @pick="dropzone?.choose()" />
      <QuotaBanner />

      <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div class="min-w-0 space-y-6">
          <section class="rounded-xl border bg-card px-5 pt-5 pb-2">
            <h2 class="font-semibold">
              {{ filesCount(detail.file_count) }}, {{ formatSize(detail.total_size) }}
            </h2>
            <UploadList :items="localItems" class="mt-2" />
            <ul class="divide-y" :class="localItems.length ? 'border-t' : ''">
              <li v-for="file in files" :key="file.id" class="flex items-start gap-3 py-3.5">
                <div class="min-w-0 flex-1">
                  <RenameInput
                    v-if="renamingId === file.id"
                    :name="file.name"
                    @save="(name: string) => renameFile(file, name)"
                    @cancel="renamingId = null"
                  />
                  <a
                    v-else-if="file.url"
                    :href="file.url"
                    target="_blank"
                    rel="noopener"
                    class="block truncate rounded font-medium outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    :title="file.name"
                  >
                    {{ file.name }}
                  </a>
                  <p v-else class="truncate font-medium" :title="file.name">{{ file.name }}</p>
                  <p class="tabular mt-0.5 text-sm text-muted-foreground">{{ fileMeta(file) }}</p>
                  <div v-if="fileBadge(file)" class="mt-1.5 flex flex-wrap items-center gap-2">
                    <Badge :variant="fileBadge(file)!.tone">
                      <LoaderCircle v-if="fileBadge(file)!.spin" class="animate-spin" />
                      {{ fileBadge(file)!.text }}
                    </Badge>
                    <span v-if="file.playable === 'maybe' && file.play !== 'none'" class="text-xs text-muted-foreground">
                      {{ t('detail.hevc') }}
                    </span>
                  </div>
                  <Progress
                    v-if="file.status === 'uploading' && file.uploaded"
                    :model-value="file.uploaded"
                    :max="file.size"
                    class="mt-2"
                    indicator-class="bg-muted-foreground/50"
                  />
                </div>
                <div class="flex shrink-0 gap-1">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-muted-foreground"
                    :aria-label="t('file.renameNamed', { name: file.name })"
                    :title="t('file.rename')"
                    @click="renamingId = file.id"
                  >
                    <Pencil />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-muted-foreground hover:text-destructive"
                    :aria-label="t('file.deleteNamed', { name: file.name })"
                    :title="t('file.delete')"
                    @click="fileToDelete = file"
                  >
                    <Trash2 />
                  </Button>
                </div>
              </li>
            </ul>
            <p v-if="!files.length && !localItems.length" class="py-4 text-sm text-muted-foreground">
              {{ t('detail.noFiles') }}
            </p>
          </section>

          <DropZone
            ref="dropzone"
            page
            compact
            :label="t('detail.dropLabel')"
            :disabled="blocked"
            @files="onFiles"
          />

          <section class="rounded-xl border bg-card p-5">
            <h2 class="mb-4 font-semibold">{{ t('detail.log') }}</h2>
            <EventLog :events="detail.events" />
          </section>
        </div>

        <aside class="h-fit space-y-6">
          <div class="rounded-xl border bg-card p-5">
            <LiveSettings :share="detail" @updated="onUpdated" />
          </div>

          <dl class="tabular grid grid-cols-3 gap-4 rounded-xl border bg-card p-5">
            <div>
              <dt class="text-sm text-muted-foreground">{{ t('stats.views') }}</dt>
              <dd class="mt-1 text-2xl font-semibold">{{ detail.views }}</dd>
            </div>
            <div>
              <dt class="text-sm text-muted-foreground">{{ t('stats.downloads') }}</dt>
              <dd class="mt-1 text-2xl font-semibold">{{ detail.downloads }}</dd>
            </div>
            <div>
              <dt class="text-sm text-muted-foreground">{{ t('stats.plays') }}</dt>
              <dd class="mt-1 text-2xl font-semibold">{{ detail.plays }}</dd>
            </div>
            <p class="col-span-3 text-sm text-muted-foreground">
              {{
                detail.last_access_at
                  ? t('detail.lastOpened', { relative: formatRelative(detail.last_access_at) })
                  : t('detail.neverOpened')
              }}
            </p>
          </dl>

          <Button variant="outline" class="w-full text-destructive hover:text-destructive" @click="deleteShareOpen = true">
            <Trash2 />
            {{ t('shares.deleteLink') }}
          </Button>
        </aside>
      </div>
    </div>

    <ConfirmDialog
      :open="fileToDelete !== null"
      :title="t('shares.deleteTitle', { name: fileToDelete?.name ?? '' })"
      :description="t('detail.deleteFileText')"
      :confirm-label="t('common.delete')"
      :action="deleteFile"
      @update:open="(open: boolean) => !open && (fileToDelete = null)"
    />
    <ConfirmDialog
      v-model:open="deleteShareOpen"
      :title="t('shares.deleteTitle', { name: detail?.display_title ?? '' })"
      :description="
        detail?.file_count
          ? t('shares.deleteWithFiles', { files: filesCount(detail.file_count), size: formatSize(detail.total_size) })
          : t('shares.deleteEmpty')
      "
      :confirm-label="t('common.delete')"
      :action="deleteShare"
    />
  </main>
</template>
