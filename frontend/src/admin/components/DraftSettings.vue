<script setup lang="ts">
import { Input } from '@/components/ui/input'
import InfoHint from '@/components/InfoHint.vue'
import { Label } from '@/components/ui/label'
import type { ExpiryPreset } from '@/lib/expiry'
import { t } from '@/lib/i18n'
import type { Draft } from '../draft'
import ExpiryPicker from './ExpiryPicker.vue'
import PasswordField from './PasswordField.vue'

const draft = defineModel<Draft>({ required: true })

function setExpiry(preset: ExpiryPreset, customAt: number | null) {
  draft.value = { ...draft.value, preset, customAt }
}
</script>

<template>
  <div class="space-y-6">
    <div class="space-y-2">
      <div class="flex items-center gap-1">
        <Label for="draft-title">
          {{ t('settings.title') }} <span class="font-normal text-muted-foreground">· {{ t('common.optional') }}</span>
        </Label>
        <InfoHint :label="t('settings.titleHintLabel')">{{ t('settings.titleHint') }}</InfoHint>
      </div>
      <Input id="draft-title" v-model="draft.title" :placeholder="t('settings.titlePlaceholder')" maxlength="200" />
    </div>
    <div class="space-y-2">
      <p class="text-sm font-medium">{{ t('settings.expiry') }}</p>
      <ExpiryPicker :preset="draft.preset" :custom-at="draft.customAt" @change="setExpiry" />
    </div>
    <div class="space-y-2">
      <Label for="draft-password">
        {{ t('common.password') }} <span class="font-normal text-muted-foreground">· {{ t('common.optional') }}</span>
      </Label>
      <PasswordField id="draft-password" v-model="draft.password" />
    </div>
  </div>
</template>
