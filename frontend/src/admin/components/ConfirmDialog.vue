<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { t } from '@/lib/i18n'

const props = withDefaults(
  defineProps<{
    title: string
    description?: string
    confirmLabel: string
    busyLabel?: string
    action: () => Promise<void> | void
  }>(),
  { description: '' },
)
const open = defineModel<boolean>('open', { default: false })
const busy = ref(false)

async function confirm() {
  busy.value = true
  try {
    await props.action()
    open.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogTitle>{{ title }}</DialogTitle>
      <DialogDescription v-if="description">{{ description }}</DialogDescription>
      <DialogFooter class="mt-2">
        <Button variant="outline" :disabled="busy" @click="open = false">{{ t('common.cancel') }}</Button>
        <Button variant="destructive" :disabled="busy" @click="confirm">{{ busy ? (busyLabel ?? t('common.deleting')) : confirmLabel }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
