<script setup lang="ts">
import { Download, FileText, LoaderCircle, Music, Play } from '@lucide/vue'
import { computed } from 'vue'
import type { PublicFile } from '@/api/types'
import { fileExtension, formatDuration, formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const props = defineProps<{ file: PublicFile; selected?: boolean }>()
const emit = defineEmits<{ open: [file: PublicFile] }>()

const uploading = computed(() => props.file.status === 'uploading')
const openable = computed(
  () => !uploading.value && (props.file.kind === 'video' || (props.file.kind === 'image' && !!(props.file.poster_url || props.file.url))),
)
// A file that is not opened in the viewer is downloaded: the whole card (tile and caption) is one link.
const downloadable = computed(() => !openable.value && !uploading.value && !!props.file.download_url)
const ext = computed(() => fileExtension(props.file.name) || t('file.extFallback'))
const downloadTitle = computed(() => t('file.downloadSize', { size: formatSize(props.file.size) }))
</script>

<template>
  <article :class="cn('group flex min-w-0 flex-col', uploading && 'opacity-60')">
    <component
      :is="downloadable ? 'a' : 'div'"
      :href="downloadable ? file.download_url : undefined"
      :download="downloadable ? '' : undefined"
      :class="
        cn(
          'flex min-w-0 flex-col rounded-lg outline-none',
          downloadable &&
            'cursor-pointer transition-transform duration-200 ease-out hover:-translate-y-0.5 focus-visible:ring-[3px] focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        )
      "
      :aria-label="downloadable ? t('file.download', { name: file.name }) : undefined"
      :title="downloadable ? downloadTitle : undefined"
    >
      <component
        :is="openable ? 'button' : 'div'"
        :type="openable ? 'button' : undefined"
        :class="
          cn(
            'relative aspect-video w-full overflow-hidden rounded-lg bg-muted text-left outline-none',
            openable && 'cursor-pointer focus-visible:ring-[3px] focus-visible:ring-ring/60',
            downloadable && 'transition-colors duration-200 group-hover:bg-accent',
            selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
          )
        "
        :aria-label="openable ? t(file.kind === 'video' ? 'file.watch' : 'file.open', { name: file.name }) : undefined"
        @click="openable && emit('open', file)"
      >
        <img
          v-if="file.poster_url"
          :src="file.poster_url"
          alt=""
          loading="lazy"
          class="size-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
        />
        <div v-else class="flex size-full flex-col items-start justify-end p-3">
          <Music
            v-if="file.kind === 'audio'"
            class="mb-auto size-5 text-muted-foreground transition-colors duration-200"
            :class="downloadable && 'group-hover:text-accent-foreground'"
          />
          <FileText
            v-else
            class="mb-auto size-5 text-muted-foreground transition-colors duration-200"
            :class="downloadable && 'group-hover:text-accent-foreground'"
          />
          <span
            class="font-display text-2xl font-semibold tracking-[-0.02em] text-foreground/80 transition-colors duration-200"
            :class="downloadable && 'group-hover:text-accent-foreground'"
          >
            {{ ext }}
          </span>
        </div>

        <span
          v-if="file.kind === 'video' && file.duration"
          class="tabular absolute right-2 bottom-2 rounded bg-black/75 px-1.5 py-0.5 text-xs font-medium text-white"
        >
          {{ formatDuration(file.duration) }}
        </span>
        <span
          v-if="file.kind === 'video' && file.poster_url && !uploading"
          class="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100"
          :class="selected && 'opacity-0!'"
        >
          <span class="flex size-11 items-center justify-center rounded-full bg-black/60 text-white">
            <Play class="ml-0.5 size-5 fill-current" />
          </span>
        </span>
        <span
          v-if="downloadable"
          aria-hidden="true"
          class="absolute right-3 bottom-3 flex translate-y-1 items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground opacity-0 shadow-sm transition-[opacity,transform] duration-200 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100"
        >
          <Download class="size-3.5" />
          {{ t('file.downloadAction') }}
        </span>
        <span
          v-if="uploading"
          class="absolute inset-0 flex items-center justify-center gap-2 bg-background/40 text-sm font-medium"
        >
          <LoaderCircle class="size-4 animate-spin" />
          {{ t('file.uploading') }}
        </span>
      </component>

      <div class="mt-2.5 flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <p class="line-clamp-2 text-sm leading-snug font-medium break-words" :title="downloadable ? undefined : file.name">
            {{ file.name }}
          </p>
          <p class="tabular mt-0.5 text-sm text-muted-foreground">{{ formatSize(file.size) }}</p>
        </div>
        <span
          v-if="downloadable"
          aria-hidden="true"
          class="-mt-1 flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 group-hover:bg-accent group-hover:text-accent-foreground"
        >
          <Download class="size-4" />
        </span>
        <a
          v-else-if="file.download_url"
          :href="file.download_url"
          download
          class="-mt-1 flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          :aria-label="t('file.download', { name: file.name })"
          :title="downloadTitle"
        >
          <Download class="size-4" />
        </a>
      </div>
    </component>
    <audio
      v-if="file.kind === 'audio' && file.play_url"
      :src="file.play_url"
      controls
      preload="none"
      class="mt-2 h-9 w-full"
    />
  </article>
</template>
