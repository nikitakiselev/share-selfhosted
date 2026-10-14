<script setup lang="ts">
// Settings of an existing link: every change goes to the server right away.
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { appApi } from '@/api/app'
import type { AdminShareSummary, ShareSettingsInput } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import InfoHint from '@/components/InfoHint.vue'
import { Label } from '@/components/ui/label'
import { type ExpiryPreset, expiresAtFor, GRACE_SECONDS, savePreset } from '@/lib/expiry'
import { formatDate, formatRelative } from '@/lib/format'
import { t } from '@/lib/i18n'
import { handleAuthError } from '../session'
import ExpiryPicker from './ExpiryPicker.vue'
import PasswordField from './PasswordField.vue'

const props = defineProps<{ share: AdminShareSummary }>()
const emit = defineEmits<{ updated: [share: AdminShareSummary] }>()

const title = ref(props.share.title ?? '')
const preset = ref<ExpiryPreset | null>(props.share.expires_at === null ? 'never' : null)
const customAt = ref<number | null>(null)
const editingPassword = ref(false)
const password = ref('')
const saving = ref(false)

watch(
  () => props.share,
  (share) => {
    if (document.activeElement?.id !== `title-${share.slug}`) title.value = share.title ?? ''
    if (share.expires_at === null) preset.value = 'never'
    else if (preset.value === 'never') preset.value = null
  },
)

async function save(input: ShareSettingsInput, message?: string): Promise<boolean> {
  saving.value = true
  try {
    const updated = await appApi.updateShare(props.share.slug, input)
    emit('updated', updated)
    if (message) toast.success(message)
    return true
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('common.saveFailed'))
    return false
  } finally {
    saving.value = false
  }
}

function saveTitle() {
  const value = title.value.trim()
  if (value === (props.share.title ?? '')) return
  void save({ title: value || null })
}

async function setExpiry(next: ExpiryPreset, at: number | null) {
  preset.value = next
  customAt.value = at
  savePreset(next)
  const expiresAt = expiresAtFor(next, at)
  await save(
    { expires_at: expiresAt },
    expiresAt === null ? t('settings.nowNever') : t('settings.nowUntil', { date: formatDate(expiresAt) }),
  )
}

async function savePassword() {
  if (!password.value) return
  if (await save({ password: password.value }, t('settings.passwordSet'))) {
    editingPassword.value = false
    password.value = ''
  }
}

function removePassword() {
  void save({ password: null }, t('settings.passwordRemoved'))
}
</script>

<template>
  <div class="space-y-6">
    <div class="space-y-2">
      <div class="flex items-center gap-1">
        <Label :for="`title-${share.slug}`">
          {{ t('settings.title') }} <span class="font-normal text-muted-foreground">· {{ t('common.optional') }}</span>
        </Label>
        <InfoHint :label="t('settings.titleHintLabel')">{{ t('settings.titleHint') }}</InfoHint>
      </div>
      <Input
        :id="`title-${share.slug}`"
        v-model="title"
        :placeholder="share.display_title"
        maxlength="200"
        @blur="saveTitle"
        @keydown.enter="($event.target as HTMLInputElement).blur()"
      />
    </div>

    <div class="space-y-2">
      <p class="text-sm font-medium">{{ t('settings.expiry') }}</p>
      <p v-if="share.expired && share.expires_at" class="text-sm text-destructive">
        {{
          t('settings.expiredAt', {
            date: formatDate(share.expires_at),
            deleteAt: formatDate(share.expires_at + GRACE_SECONDS),
          })
        }}
      </p>
      <p v-else-if="share.expires_at" class="text-sm text-muted-foreground">
        {{ t('settings.until', { date: formatDate(share.expires_at), relative: formatRelative(share.expires_at) }) }}
      </p>
      <p v-else class="text-sm text-muted-foreground">{{ t('settings.noExpiry') }}</p>
      <ExpiryPicker :preset="preset" :custom-at="customAt" :disabled="saving" @change="setExpiry" />
    </div>

    <div class="space-y-2">
      <Label :for="`password-${share.slug}`">
        {{ t('common.password') }} <span class="font-normal text-muted-foreground">· {{ t('common.optional') }}</span>
      </Label>
      <template v-if="share.protected && !editingPassword">
        <div class="flex flex-wrap items-center gap-2">
          <p class="mr-auto text-sm text-muted-foreground">{{ t('settings.passwordIsSet') }}</p>
          <Button variant="outline" size="sm" :disabled="saving" @click="editingPassword = true">{{ t('settings.changePassword') }}</Button>
          <Button variant="ghost" size="sm" :disabled="saving" @click="removePassword">{{ t('settings.removePassword') }}</Button>
        </div>
      </template>
      <form v-else class="flex gap-2" @submit.prevent="savePassword">
        <PasswordField :id="`password-${share.slug}`" v-model="password" class="flex-1" :placeholder="share.protected ? t('password.new') : t('common.noPassword')" />
        <Button type="submit" variant="outline" :disabled="!password || saving">{{ t('settings.setPassword') }}</Button>
        <Button v-if="editingPassword" type="button" variant="ghost" @click="(editingPassword = false), (password = '')">
          {{ t('common.cancel') }}
        </Button>
      </form>
    </div>
  </div>
</template>
