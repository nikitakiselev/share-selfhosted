<script setup lang="ts">
import { Copy, Download, ExternalLink, Eye, LoaderCircle, LockKeyhole, Play, Plus, Trash2 } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'
import { appApi } from '@/api/app'
import type { AdminShareSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import { GRACE_SECONDS, nowSeconds } from '@/lib/expiry'
import { filesCount, formatDate, formatRelative, formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { dropShare } from '@/upload/engine'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { handleAuthError } from './session'
import { setUsage } from './usage'

type Filter = 'all' | 'live'
const FILTER_KEY = 'share:files-filter'

const shares = ref<AdminShareSummary[] | null>(null)
const filter = ref<Filter>(loadFilter())
const error = ref('')
const toDelete = ref<AdminShareSummary | null>(null)
const confirmOpen = computed({
  get: () => toDelete.value !== null,
  set: (open) => {
    if (!open) toDelete.value = null
  },
})
let timer: number | null = null

async function load() {
  try {
    const data = await appApi.shares()
    shares.value = data.shares
    setUsage(data.usage)
    error.value = ''
  } catch (e) {
    if (!handleAuthError(e)) error.value = e instanceof Error ? e.message : t('common.loadListFailed')
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(), 30_000)
})
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})

function loadFilter(): Filter {
  try {
    return localStorage.getItem(FILTER_KEY) === 'live' ? 'live' : 'all'
  } catch {
    return 'all'
  }
}

function setFilter(next: Filter) {
  filter.value = next
  try {
    localStorage.setItem(FILTER_KEY, next)
  } catch {
    // without localStorage the filter just isn't remembered
  }
}

/** A recipient can open it right now: not expired and at least one file is uploaded. */
const isLive = (share: AdminShareSummary) => !share.expired && share.file_count > share.uploading_count

const liveCount = computed(() => (shares.value ?? []).filter(isLive).length)
const visible = computed(() => (filter.value === 'live' ? (shares.value ?? []).filter(isLive) : (shares.value ?? [])))
const filters = computed(() => [
  { value: 'all' as const, label: t('shares.filterAll'), count: shares.value?.length ?? 0 },
  { value: 'live' as const, label: t('shares.filterLive'), count: liveCount.value },
])

interface ShareStatus {
  label: string
  tone: 'success' | 'warning' | 'destructive' | 'secondary'
  detail: string
  urgent?: boolean
}

function status(share: AdminShareSummary): ShareStatus {
  if (share.expired)
    return {
      label: t('shares.expired'),
      tone: 'destructive',
      detail: share.expires_at ? t('shares.deletesOn', { date: formatDate(share.expires_at + GRACE_SECONDS, false) }) : '',
    }
  if (share.file_count === share.uploading_count) {
    return share.uploading_count
      ? { label: t('shares.uploading'), tone: 'warning', detail: t('shares.recipientsSeeNothing') }
      : { label: t('shares.empty'), tone: 'secondary', detail: t('shares.noFiles') }
  }
  if (share.expires_at === null) return { label: t('shares.live'), tone: 'success', detail: t('settings.noExpiry') }
  return {
    label: t('shares.live'),
    tone: 'success',
    detail: t('shares.expires', { relative: formatRelative(share.expires_at) }),
    urgent: share.expires_at - nowSeconds() < 86400,
  }
}

async function copy(share: AdminShareSummary) {
  if (await copyText(share.url)) toast.success(t('common.linkCopied'))
  else toast.error(t('common.copyFailedShort'))
}

async function remove() {
  const share = toDelete.value
  if (!share) return
  try {
    await appApi.deleteShare(share.slug)
    await dropShare(share.slug)
    toast.success(t('common.linkDeleted'))
    await load()
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('common.deleteFailed'))
  }
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-4 py-8 sm:px-8">
    <div class="mb-6 flex items-center justify-between gap-4">
      <h1 class="font-display text-2xl font-semibold tracking-[-0.015em]">{{ t('page.shares') }}</h1>
      <Button as-child variant="outline">
        <RouterLink :to="{ name: 'new' }">
          <Plus />
          {{ t('page.new') }}
        </RouterLink>
      </Button>
    </div>

    <div
      v-if="shares?.length"
      class="mb-4 inline-flex rounded-lg border bg-muted p-0.5"
      role="group"
      :aria-label="t('shares.filterLabel')"
    >
      <button
        v-for="f in filters"
        :key="f.value"
        type="button"
        :aria-pressed="filter === f.value"
        :class="
          cn(
            'tabular rounded-md px-3 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50',
            filter === f.value ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
          )
        "
        @click="setFilter(f.value)"
      >
        {{ f.label }}
        <span :class="cn('ml-1', filter === f.value ? 'text-muted-foreground' : 'text-muted-foreground/70')">{{ f.count }}</span>
      </button>
    </div>

    <p v-if="error" class="text-destructive">{{ error }}</p>

    <div v-if="shares === null && !error" class="flex justify-center py-16 text-muted-foreground">
      <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
    </div>

    <div v-else-if="shares && !shares.length" class="rounded-xl border border-dashed px-6 py-16 text-center">
      <p class="font-medium">{{ t('shares.noneTitle') }}</p>
      <p class="mt-1 text-muted-foreground">{{ t('shares.noneText') }}</p>
    </div>

    <div v-else-if="shares && !visible.length" class="rounded-xl border border-dashed px-6 py-16 text-center">
      <p class="font-medium">{{ t('shares.noLiveTitle') }}</p>
      <p class="mt-1 text-muted-foreground">{{ t('shares.noLiveText') }}</p>
    </div>

    <ul v-else-if="shares" class="divide-y rounded-xl border bg-card">
      <li
        v-for="share in visible"
        :key="share.slug"
        :class="
          cn(
            'grid gap-x-6 gap-y-3 p-4 sm:p-5 md:grid-cols-[minmax(0,1fr)_12rem_12rem_auto] md:items-center',
            share.expired && 'bg-muted/40',
          )
        "
      >
        <div class="min-w-0">
          <RouterLink
            :to="{ name: 'share', params: { slug: share.slug } }"
            class="flex items-center gap-2 rounded font-medium outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <span :class="cn('truncate', share.expired && 'text-muted-foreground')">{{ share.display_title }}</span>
            <LockKeyhole v-if="share.protected" class="size-3.5 shrink-0 text-muted-foreground" :aria-label="t('shares.protected')" />
          </RouterLink>
          <p class="tabular mt-1 text-sm text-muted-foreground">
            {{
              t('shares.meta', {
                files: filesCount(share.file_count),
                size: formatSize(share.total_size),
                relative: formatRelative(share.created_at),
              })
            }}
          </p>
          <p v-if="share.uploading_count" class="mt-1 flex items-center gap-1.5 text-sm text-primary">
            <LoaderCircle class="size-3.5 animate-spin" />
            {{ t('shares.uploadingCount', { count: share.uploading_count }) }}
          </p>
        </div>

        <div :title="share.expires_at ? t('shares.expiresTitle', { date: formatDate(share.expires_at) }) : undefined">
          <Badge :variant="status(share).tone">{{ status(share).label }}</Badge>
          <p
            v-if="status(share).detail"
            :class="cn('mt-1 text-sm', status(share).urgent ? 'text-destructive' : 'text-muted-foreground')"
          >
            {{ status(share).detail }}
          </p>
        </div>

        <div class="text-sm">
          <p class="tabular flex gap-3.5 text-foreground">
            <span class="flex items-center gap-1" :title="t('stats.viewsTitle', { count: share.views })">
              <Eye class="size-3.5 text-muted-foreground" />{{ share.views }}
            </span>
            <span class="flex items-center gap-1" :title="t('stats.downloadsTitle', { count: share.downloads })">
              <Download class="size-3.5 text-muted-foreground" />{{ share.downloads }}
            </span>
            <span class="flex items-center gap-1" :title="t('stats.playsTitle', { count: share.plays })">
              <Play class="size-3.5 text-muted-foreground" />{{ share.plays }}
            </span>
          </p>
          <p class="mt-1 text-muted-foreground">
            {{
              share.last_access_at
                ? t('shares.opened', { relative: formatRelative(share.last_access_at) })
                : t('shares.neverOpened')
            }}
          </p>
        </div>

        <div class="flex gap-1 md:justify-end">
          <Button
            variant="ghost"
            size="icon-sm"
            :aria-label="t('common.copyLink')"
            :title="isLive(share) ? t('common.copyLink') : t('shares.inactive')"
            :disabled="!isLive(share)"
            @click="copy(share)"
          >
            <Copy />
          </Button>
          <Button
            as="a"
            :href="share.url"
            target="_blank"
            rel="noopener"
            variant="ghost"
            size="icon-sm"
            :aria-label="t('common.openLink')"
            :title="t('common.openLink')"
          >
            <ExternalLink />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            class="text-muted-foreground hover:text-destructive"
            :aria-label="t('shares.deleteLink')"
            :title="t('shares.deleteLink')"
            @click="toDelete = share"
          >
            <Trash2 />
          </Button>
        </div>
      </li>
    </ul>

    <ConfirmDialog
      v-model:open="confirmOpen"
      :title="t('shares.deleteTitle', { name: toDelete?.display_title ?? '' })"
      :description="
        toDelete?.file_count
          ? t('shares.deleteWithFiles', { files: filesCount(toDelete.file_count), size: formatSize(toDelete.total_size) })
          : t('shares.deleteEmpty')
      "
      :confirm-label="t('common.delete')"
      :action="remove"
    />
  </main>
</template>
