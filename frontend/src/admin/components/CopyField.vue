<script setup lang="ts">
// A finished link (invitation, password reset): shown in full and copied with one button.
import { Check, Copy } from '@lucide/vue'
import { ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import { t } from '@/lib/i18n'

const props = defineProps<{ value: string; label?: string }>()
const copied = ref(false)
let timer: number | null = null

async function copy() {
  if (!(await copyText(props.value))) {
    toast.error(t('common.copyFailed'))
    return
  }
  copied.value = true
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => (copied.value = false), 2000)
}
</script>

<template>
  <div class="flex gap-2">
    <input
      :value="value"
      readonly
      :aria-label="label ?? t('common.link')"
      class="tabular h-9 min-w-0 flex-1 rounded-md border border-input bg-muted/50 px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
      @focus="($event.target as HTMLInputElement).select()"
    />
    <Button type="button" class="w-32" @click="copy">
      <Check v-if="copied" />
      <Copy v-else />
      {{ copied ? t('common.copied') : t('common.copy') }}
    </Button>
  </div>
</template>
