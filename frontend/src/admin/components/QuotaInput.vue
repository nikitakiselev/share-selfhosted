<script setup lang="ts">
// A user's limit: whole GB or "Unlimited" — in the invitation and the limit dialog.
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'

defineProps<{ id: string; disabled?: boolean }>()
// type="number" yields a number, an empty field yields a string
const gb = defineModel<string | number>('gb', { required: true })
const unlimited = defineModel<boolean>('unlimited', { required: true })
</script>

<template>
  <div class="space-y-2">
    <Label :for="id">{{ t('quota.label') }}</Label>
    <div class="flex items-center gap-4">
      <Input
        :id="id"
        v-model="gb"
        type="number"
        inputmode="numeric"
        min="1"
        step="1"
        class="tabular w-28"
        :disabled="disabled || unlimited"
      />
      <label class="flex items-center gap-2 text-sm">
        <input v-model="unlimited" type="checkbox" class="size-4 accent-primary" :disabled="disabled" />
        {{ t('common.unlimited') }}
      </label>
    </div>
  </div>
</template>
