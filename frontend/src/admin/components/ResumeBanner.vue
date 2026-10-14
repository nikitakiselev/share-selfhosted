<script setup lang="ts">
// After a page reload: unfinished uploads wait for access to their files.
import { History } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { cancelWaiting, resumeWithHandles, useUploads } from '@/upload/engine'

const emit = defineEmits<{ pick: [] }>()
const { waiting, waitingWithHandles } = useUploads()
const busy = ref(false)

const withoutHandles = computed(() => waiting.value.filter((i) => !i.handle))

async function resume() {
  busy.value = true
  try {
    const { resumed, failed } = await resumeWithHandles()
    if (resumed) toast.success(resumed === 1 ? t('upload.resumedOne') : t('upload.resumedMany', { count: resumed }))
    if (failed) toast.warning(t('resume.noAccess'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="waiting.length" class="rounded-xl border border-warning/40 bg-warning/8 p-5" aria-live="polite">
    <div class="flex items-start gap-3">
      <History class="mt-0.5 size-5 shrink-0 text-warning" />
      <div class="min-w-0 flex-1">
        <h2 class="font-semibold">{{ t('resume.title') }}</h2>
        <p class="mt-1 text-sm text-muted-foreground">
          <template v-if="waitingWithHandles.length && !withoutHandles.length">
            {{ t('resume.reloaded') }}
          </template>
          <template v-else>
            {{ t('resume.pickAgain') }}
          </template>
        </p>
        <ul class="mt-3 space-y-1 text-sm">
          <li v-for="item in waiting" :key="item.key" class="flex gap-3">
            <span class="min-w-0 flex-1 truncate">{{ item.name }}</span>
            <span class="tabular shrink-0 text-muted-foreground">
              {{ t('common.xOfY', { x: formatSize(item.bytesUploaded), y: formatSize(item.size) }) }}
            </span>
          </li>
        </ul>
        <div class="mt-4 flex flex-wrap gap-2">
          <Button v-if="waitingWithHandles.length" :disabled="busy" @click="resume">{{ t('resume.continue') }}</Button>
          <Button v-if="withoutHandles.length" variant="outline" @click="emit('pick')">{{ t('drop.choose') }}</Button>
          <Button variant="ghost" @click="cancelWaiting">{{ t('resume.cancel') }}</Button>
        </div>
      </div>
    </div>
  </section>
</template>
