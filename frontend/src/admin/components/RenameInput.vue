<script setup lang="ts">
// File rename field. The name without the extension is selected, like in Finder: type a new
// one right away without losing ".mp4". Enter or blur saves, Escape cancels.
import { nextTick, onMounted, ref } from 'vue'
import { Input } from '@/components/ui/input'
import { t } from '@/lib/i18n'

const props = defineProps<{ name: string }>()
const emit = defineEmits<{ save: [name: string]; cancel: [] }>()

const value = ref(props.name)
const input = ref<InstanceType<typeof Input> | null>(null)
// Enter followed by blur on unmount must not save twice
let finished = false

onMounted(async () => {
  await nextTick()
  const el = input.value?.$el as HTMLInputElement | undefined
  if (!el) return
  el.focus()
  const dot = props.name.lastIndexOf('.')
  el.setSelectionRange(0, dot > 0 ? dot : props.name.length)
})

function save() {
  if (finished) return
  finished = true
  emit('save', value.value.trim())
}

function cancel() {
  if (finished) return
  finished = true
  emit('cancel')
}
</script>

<template>
  <Input
    ref="input"
    v-model="value"
    :aria-label="t('file.name')"
    maxlength="255"
    class="h-8 font-medium"
    @blur="save"
    @keydown.enter.prevent="save"
    @keydown.esc.prevent="cancel"
  />
</template>
