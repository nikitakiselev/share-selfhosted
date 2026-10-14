<script setup lang="ts">
// Drop zone. In page mode it accepts files dropped anywhere in the window and shows
// a "Release…" overlay over the page.
import { FolderOpen, Upload } from '@lucide/vue'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { collectDropped, hasFiles, type PickedFile, pickFiles } from '@/upload/handles'

const props = withDefaults(defineProps<{ page?: boolean; compact?: boolean; label?: string; disabled?: boolean }>(), {
  page: false,
  compact: false,
})
const emit = defineEmits<{ files: [files: PickedFile[]] }>()

const over = ref(false)
let depth = 0

async function handleDrop(event: DragEvent) {
  event.preventDefault()
  over.value = false
  depth = 0
  if (props.disabled || !event.dataTransfer) return
  const { files, skippedDirectories } = collectDropped(event.dataTransfer)
  if (skippedDirectories) toast.warning(t('drop.noFolders'))
  const picked = await files
  if (picked.length) emit('files', picked)
}

async function choose() {
  const picked = await pickFiles()
  if (picked?.length) emit('files', picked)
}

function onWindowDragEnter(event: DragEvent) {
  if (!hasFiles(event) || props.disabled) return
  depth++
  over.value = true
}
function onWindowDragLeave() {
  depth = Math.max(0, depth - 1)
  if (depth === 0) over.value = false
}
function onWindowDragOver(event: DragEvent) {
  if (!hasFiles(event)) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = props.disabled ? 'none' : 'copy'
}
function onWindowDrop(event: DragEvent) {
  if (!hasFiles(event)) return
  void handleDrop(event)
}

onMounted(() => {
  if (!props.page) return
  window.addEventListener('dragenter', onWindowDragEnter)
  window.addEventListener('dragleave', onWindowDragLeave)
  window.addEventListener('dragover', onWindowDragOver)
  window.addEventListener('drop', onWindowDrop)
})
onBeforeUnmount(() => {
  window.removeEventListener('dragenter', onWindowDragEnter)
  window.removeEventListener('dragleave', onWindowDragLeave)
  window.removeEventListener('dragover', onWindowDragOver)
  window.removeEventListener('drop', onWindowDrop)
})

// Without page mode the zone catches files only on itself.
function onLocalDragOver(event: DragEvent) {
  if (props.page || !hasFiles(event)) return
  event.preventDefault()
  over.value = true
}
function onLocalDrop(event: DragEvent) {
  if (props.page) return
  event.stopPropagation()
  void handleDrop(event)
}

defineExpose({ choose })
</script>

<template>
  <div
    :class="
      cn(
        'relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-input text-center transition-colors',
        compact ? 'gap-3 px-5 py-6 sm:flex-row sm:justify-between sm:text-left' : 'min-h-[min(56vh,520px)] gap-5 px-6 py-12',
        over && 'border-primary bg-accent/60',
        disabled && 'opacity-60',
      )
    "
    @dragover="onLocalDragOver"
    @dragleave="!page && (over = false)"
    @drop="onLocalDrop"
  >
    <template v-if="compact">
      <p class="flex items-center gap-3 text-muted-foreground">
        <Upload class="size-5 shrink-0" />
        {{ label ?? t('drop.label') }}
      </p>
      <Button variant="outline" :disabled="disabled" @click="choose">
        <FolderOpen />
        {{ t('drop.choose') }}
      </Button>
    </template>
    <template v-else>
      <Upload class="size-9 text-primary" stroke-width="1.5" />
      <div>
        <p class="font-display text-[clamp(1.25rem,3vw,1.75rem)] leading-tight font-semibold tracking-[-0.015em]">
          {{ label ?? t('drop.label') }}
        </p>
        <p class="mx-auto mt-3 max-w-[44ch] text-muted-foreground">
          {{ t('drop.hint') }}
        </p>
      </div>
      <Button size="lg" :disabled="disabled" @click="choose">
        <FolderOpen />
        {{ t('drop.choose') }}
      </Button>
    </template>
  </div>

  <Teleport to="body">
    <div
      v-if="page && over"
      class="pointer-events-none fixed inset-3 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/85 backdrop-blur-sm"
    >
      <p class="font-display text-2xl font-semibold tracking-[-0.015em]">{{ t('drop.release') }}</p>
    </div>
  </Teleport>
</template>
