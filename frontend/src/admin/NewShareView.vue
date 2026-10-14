<script setup lang="ts">
import { Link2, LoaderCircle, Plus } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { appApi } from '@/api/app'
import type { AdminShareSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { expiresAtFor, loadPreset, savePreset } from '@/lib/expiry'
import { formatEta, formatSize, formatSpeed } from '@/lib/format'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import { addFiles, clearFinished, hasUnfinished, matchesWaiting, totalsOf, useUploads, whenRestored } from '@/upload/engine'
import type { PickedFile } from '@/upload/handles'
import DraftSettings from './components/DraftSettings.vue'
import DropZone from './components/DropZone.vue'
import LinkCard from './components/LinkCard.vue'
import LiveSettings from './components/LiveSettings.vue'
import QuotaBanner from './components/QuotaBanner.vue'
import ResumeBanner from './components/ResumeBanner.vue'
import UploadList from './components/UploadList.vue'
import { type Draft, newShareRequests } from './draft'
import { admitFiles } from './quotaGate'
import { handleAuthError } from './session'
import { overQuota } from './usage'

// The link files are being added to survives a page reload — while it has unfinished
// uploads. Once everything is uploaded, the page is for a new link again, and the finished
// one is in "My files".
const CURRENT_KEY = 'share:current'

const { state, waiting } = useUploads()

const freshDraft = (): Draft => ({ title: '', preset: loadPreset(), customAt: null, password: '' })
const draft = ref<Draft>(freshDraft())
const share = ref<AdminShareSummary | null>(null)
const restoring = ref(true)
const creating = ref(false)
let pendingCreate: Promise<AdminShareSummary> | null = null
const dropzone = ref<InstanceType<typeof DropZone> | null>(null)

const items = computed(() =>
  share.value ? state.items.filter((i) => i.shareSlug === share.value!.slug && i.status !== 'needs-file') : [],
)
const totals = computed(() => totalsOf(items.value))

// The link is created on the server on the first drop (otherwise there is nowhere to upload
// and nothing to restore after a reload), but is shown only once everything is uploaded:
// sending a link to a half-uploaded file is pointless. A shown link stays visible even if
// more files are added — recipients only see uploaded ones anyway.
const revealed = ref(false)
const allUploaded = computed(() => {
  const slug = share.value?.slug
  if (!slug) return false
  const mine = state.items.filter((i) => i.shareSlug === slug)
  const finished = (i: (typeof mine)[number]) => i.status === 'done' || i.status === 'processing'
  return mine.some(finished) && mine.every((i) => finished(i) || i.status === 'error')
})
watch(allUploaded, (all) => {
  if (all) revealed.value = true
})
const percent = computed(() => (totals.value.size ? (totals.value.uploaded / totals.value.size) * 100 : 0))

function remember(slug: string | null) {
  try {
    if (slug) localStorage.setItem(CURRENT_KEY, slug)
    else localStorage.removeItem(CURRENT_KEY)
  } catch {
    // without localStorage the card just won't be restored after a reload
  }
}

onMounted(async () => {
  let slug: string | null = null
  try {
    slug = localStorage.getItem(CURRENT_KEY)
  } catch {
    slug = null
  }
  if (slug) {
    await whenRestored()
    if (!hasUnfinished(slug)) {
      remember(null)
      slug = null
    }
  }
  if (slug) {
    try {
      share.value = await appApi.share(slug)
    } catch (e) {
      if (!handleAuthError(e) && e instanceof ApiError && e.status === 404) remember(null)
    }
  }
  restoring.value = false
})

watch(newShareRequests, () => {
  if (share.value) newShare()
})

// Files finished uploading — refresh the card: title from the first file, size, counters.
watch(
  () => totals.value.finished,
  async () => {
    const slug = share.value?.slug
    if (!slug) return
    try {
      const fresh = await appApi.share(slug)
      if (share.value?.slug === slug) share.value = fresh
    } catch (e) {
      handleAuthError(e)
    }
  },
)

function ensureShare(): Promise<AdminShareSummary> {
  if (share.value) return Promise.resolve(share.value)
  if (!pendingCreate) {
    creating.value = true
    const d = draft.value
    pendingCreate = appApi
      .createShare({
        title: d.title.trim() || null,
        expires_at: expiresAtFor(d.preset, d.customAt),
        password: d.password || null,
      })
      .then((created) => {
        share.value = created
        remember(created.slug)
        savePreset(d.preset)
        return created
      })
      .finally(() => {
        pendingCreate = null
        creating.value = false
      })
  }
  return pendingCreate
}

// The limit is used up — no new files, but resuming interrupted uploads isn't blocked.
const blocked = computed(() => overQuota.value && !waiting.value.length)

async function onFiles(all: PickedFile[]) {
  const picked = admitFiles(all)
  if (!picked.length) return
  let slug = share.value?.slug ?? ''
  // If all files resume interrupted uploads, no new link is needed.
  if (matchesWaiting(picked) < picked.length) {
    try {
      slug = (await ensureShare()).slug
    } catch (e) {
      if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('common.createLinkFailed'))
      return
    }
  }
  const { resumed } = addFiles(slug, picked)
  if (resumed) toast.success(resumed === 1 ? t('upload.resumedOne') : t('upload.resumedMany', { count: resumed }))
}

function newShare() {
  const stillActive = totals.value.active
  if (share.value) clearFinished(share.value.slug)
  share.value = null
  revealed.value = false
  remember(null)
  draft.value = freshDraft()
  if (stillActive) toast(t('new.stillUploading'))
}
</script>

<template>
  <main class="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8">
    <ResumeBanner @pick="dropzone?.choose()" />
    <QuotaBanner />

    <template v-if="restoring" />

    <div v-else-if="!share" class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <DropZone ref="dropzone" page :disabled="creating || blocked" @files="onFiles" />
      <aside class="h-fit rounded-xl border bg-card p-5">
        <h2 class="mb-5 font-semibold">{{ t('settings.heading') }}</h2>
        <DraftSettings v-model="draft" />
      </aside>
    </div>

    <template v-else>
      <LinkCard v-if="revealed" :url="share.url" />
      <div
        v-else
        class="flex items-center gap-3 rounded-xl border border-dashed bg-card/50 p-5 text-muted-foreground sm:p-6"
        aria-live="polite"
      >
        <LoaderCircle v-if="totals.active" class="size-5 shrink-0 animate-spin" />
        <Link2 v-else class="size-5 shrink-0" />
        <p>{{ t('new.linkPending') }}</p>
      </div>
      <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section class="min-w-0 space-y-5">
          <div v-if="items.length" class="rounded-xl border bg-card px-5 pt-5 pb-2">
            <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <h2 class="font-semibold">
                <template v-if="totals.active">
                  {{ t('new.uploadedCount', { done: totals.finished, total: totals.count }) }}
                </template>
                <template v-else>{{ t('new.allUploaded') }}</template>
              </h2>
              <p v-if="totals.active" class="tabular text-sm text-muted-foreground">
                {{ t('common.xOfY', { x: formatSize(totals.uploaded), y: formatSize(totals.size) }) }}<template v-if="totals.speed">,
                  {{ formatSpeed(totals.speed) }}</template
                ><template v-if="totals.eta">, {{ formatEta(totals.eta) }}</template>
              </p>
              <p class="tabular ml-auto text-sm font-medium">{{ Math.floor(percent) }}%</p>
            </div>
            <Progress v-if="totals.active" :model-value="percent" class="mt-3 h-2" />
            <UploadList :items="items" class="mt-2" />
          </div>
          <DropZone
            ref="dropzone"
            page
            compact
            :label="items.length ? t('new.dropMore') : t('new.dropInto')"
            :disabled="blocked"
            @files="onFiles"
          />
        </section>
        <aside class="h-fit rounded-xl border bg-card p-5">
          <LiveSettings :share="share" @updated="share = $event" />
          <Button variant="outline" class="mt-7 w-full" @click="newShare">
            <Plus />
            {{ t('page.new') }}
          </Button>
        </aside>
      </div>
    </template>
  </main>
</template>
