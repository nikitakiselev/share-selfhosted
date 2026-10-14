<script setup lang="ts">
import { CircleAlert, CircleCheck, LoaderCircle, Pencil, RotateCw, WifiOff, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { formatEta, formatSize, formatSpeed } from '@/lib/format'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { cancelUpload, renameUpload, retryUpload, type UploadItem, useUploads } from '@/upload/engine'
import { handleAuthError } from '../session'
import RenameInput from './RenameInput.vue'

const props = defineProps<{ item: UploadItem }>()
const { state } = useUploads()

const percent = computed(() => (props.item.size ? (Math.min(props.item.bytesUploaded, props.item.size) / props.item.size) * 100 : 100))

const status = computed(() => {
  const i = props.item
  switch (i.status) {
    case 'queued':
      return t('upload.queued')
    case 'uploading': {
      if (!i.speed) return t('upload.uploading')
      const eta = i.speed > 0 ? formatEta((i.size - i.bytesUploaded) / i.speed) : ''
      return [formatSpeed(i.speed), eta].filter(Boolean).join(', ')
    }
    case 'paused':
      return t('upload.paused')
    case 'retrying': {
      const left = i.retryAt ? Math.max(0, Math.ceil((i.retryAt - state.now) / 1000)) : 0
      return left > 0 ? t('upload.retryIn', { n: left }) : t('upload.retrying')
    }
    case 'processing':
      return t('upload.processing')
    case 'done':
      if (i.media === 'download-only') return t('upload.doneDownloadOnly')
      if (i.media === 'failed') return t('upload.doneMediaFailed')
      return t('common.done')
    case 'error':
      return i.error ?? t('upload.error')
    case 'needs-file':
      return i.error ?? (i.handle ? t('upload.waiting') : t('upload.dragAgain'))
  }
  return ''
})

const finished = computed(() => props.item.status === 'done' || props.item.status === 'processing')
const shownName = computed(() => props.item.displayName ?? props.item.name)
const renaming = ref(false)

async function rename(name: string) {
  renaming.value = false
  if (!name || name === shownName.value) return
  try {
    await renameUpload(props.item.key, name)
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('file.renameFailed'))
  }
}
</script>

<template>
  <li class="py-3.5">
    <div class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <RenameInput v-if="renaming" :name="shownName" @save="rename" @cancel="renaming = false" />
        <p v-else class="truncate font-medium" :title="shownName">{{ shownName }}</p>
        <p
          :class="
            cn(
              'tabular mt-0.5 flex items-center gap-1.5 text-sm text-muted-foreground',
              item.status === 'error' && 'text-destructive',
              item.status === 'retrying' && 'text-warning',
            )
          "
        >
          <LoaderCircle v-if="item.status === 'processing'" class="size-3.5 animate-spin" />
          <CircleCheck v-else-if="item.status === 'done'" class="size-3.5 text-success" />
          <WifiOff v-else-if="item.status === 'paused'" class="size-3.5" />
          <CircleAlert v-else-if="item.status === 'error'" class="size-3.5" />
          <span class="truncate">{{ status }}</span>
        </p>
      </div>
      <p class="tabular shrink-0 pt-0.5 text-right text-sm text-muted-foreground">
        <template v-if="finished">{{ formatSize(item.size) }}</template>
        <template v-else>{{ t('common.xOfY', { x: formatSize(item.bytesUploaded), y: formatSize(item.size) }) }}</template>
      </p>
      <div class="flex shrink-0 gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          class="text-muted-foreground"
          :aria-label="t('file.renameNamed', { name: shownName })"
          :title="t('file.rename')"
          @click="renaming = true"
        >
          <Pencil />
        </Button>
        <Button
          v-if="item.status === 'error' && item.file"
          variant="ghost"
          size="icon-sm"
          :aria-label="t('common.retry')"
          :title="t('common.retry')"
          @click="retryUpload(item.key)"
        >
          <RotateCw />
        </Button>
        <Button
          v-if="!finished"
          variant="ghost"
          size="icon-sm"
          :aria-label="t('upload.cancel')"
          :title="t('upload.cancel')"
          @click="cancelUpload(item.key)"
        >
          <X />
        </Button>
      </div>
    </div>
    <Progress
      v-if="!finished"
      :model-value="percent"
      class="mt-2.5"
      :indicator-class="cn(item.status === 'error' && 'bg-destructive', (item.status === 'paused' || item.status === 'needs-file') && 'bg-muted-foreground/50')"
    />
  </li>
</template>
