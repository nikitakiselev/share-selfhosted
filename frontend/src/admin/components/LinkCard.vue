<script setup lang="ts">
// The link itself is the main thing on the page: large, with a Copy button.
import { Check, Copy, ExternalLink } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import { t } from '@/lib/i18n'

const props = defineProps<{ url: string }>()
const copied = ref(false)
let timer: number | null = null

const parts = computed(() => {
  try {
    const u = new URL(props.url)
    const path = u.pathname
    const slugStart = path.lastIndexOf('/') + 1
    return { head: `${u.host}${path.slice(0, slugStart)}`, slug: path.slice(slugStart) }
  } catch {
    return { head: '', slug: props.url }
  }
})

async function copy() {
  if (await copyText(props.url)) {
    copied.value = true
    toast.success(t('common.linkCopied'))
    if (timer !== null) window.clearTimeout(timer)
    timer = window.setTimeout(() => (copied.value = false), 2000)
  } else {
    toast.error(t('common.copyFailed'))
  }
}
</script>

<template>
  <div class="flex flex-col gap-4 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:p-6">
    <a
      :href="url"
      target="_blank"
      rel="noopener"
      class="tabular min-w-0 flex-1 text-[clamp(1.05rem,2.4vw,1.6rem)] leading-tight tracking-[-0.01em] break-all outline-none hover:underline focus-visible:underline"
    >
      <span class="text-muted-foreground">{{ parts.head }}</span><span class="font-semibold">{{ parts.slug }}</span>
    </a>
    <div class="flex shrink-0 gap-2">
      <Button size="lg" class="flex-1 sm:flex-none" @click="copy">
        <Check v-if="copied" />
        <Copy v-else />
        {{ copied ? t('common.copied') : t('common.copy') }}
      </Button>
      <Button as="a" :href="url" target="_blank" rel="noopener" variant="outline" size="lg" :aria-label="t('common.openLink')" :title="t('common.openLink')" class="px-3">
        <ExternalLink />
      </Button>
    </div>
  </div>
</template>
