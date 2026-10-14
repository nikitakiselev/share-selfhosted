<script setup lang="ts">
import { computed } from 'vue'
import { EXPIRY_PRESETS, type ExpiryPreset, fromLocalInput, nowSeconds, toLocalInput } from '@/lib/expiry'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const props = defineProps<{ preset: ExpiryPreset | null; customAt: number | null; disabled?: boolean }>()
const emit = defineEmits<{ change: [preset: ExpiryPreset, customAt: number | null] }>()

const options = [
  ...EXPIRY_PRESETS.map((p) => ({ id: p.id as ExpiryPreset, label: t(p.label) })),
  { id: 'custom' as ExpiryPreset, label: t('expiry.custom') },
]

const customValue = computed(() => (props.customAt ? toLocalInput(props.customAt) : ''))
const minValue = computed(() => toLocalInput(nowSeconds() + 60))

function choose(id: ExpiryPreset) {
  if (id === 'custom') {
    emit('change', 'custom', props.customAt ?? nowSeconds() + 3 * 86400)
  } else {
    emit('change', id, null)
  }
}

function onCustom(event: Event) {
  const ts = fromLocalInput((event.target as HTMLInputElement).value)
  if (ts && ts > nowSeconds()) emit('change', 'custom', ts)
}
</script>

<template>
  <div>
    <div role="radiogroup" :aria-label="t('settings.expiry')" class="flex flex-wrap gap-1.5">
      <button
        v-for="option in options"
        :key="option.id"
        type="button"
        role="radio"
        :aria-checked="preset === option.id"
        :disabled="disabled"
        :class="
          cn(
            'h-8 rounded-md border px-3 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50',
            preset === option.id
              ? 'border-foreground bg-foreground text-background'
              : 'border-input bg-card hover:bg-muted',
          )
        "
        @click="choose(option.id)"
      >
        {{ option.label }}
      </button>
    </div>
    <input
      v-if="preset === 'custom'"
      type="datetime-local"
      :value="customValue"
      :min="minValue"
      :disabled="disabled"
      :aria-label="t('expiry.customLabel')"
      class="mt-2.5 h-9 w-full rounded-md border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
      @change="onCustom"
    />
  </div>
</template>
