<script setup lang="ts">
// Invitation: email and limit → a one-time link to send to the person.
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { adminApi } from '@/api/admin'
import type { CreatedInvite } from '@/api/types'
import InfoHint from '@/components/InfoHint.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatDate } from '@/lib/format'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import { isEmail, normalizeEmail, parseQuotaGb, quotaToGb } from '@/lib/quota'
import { handleAuthError } from '../session'
import CopyField from './CopyField.vue'
import QuotaInput from './QuotaInput.vue'

const props = defineProps<{ defaultQuota: number | null }>()
const emit = defineEmits<{ created: [] }>()
const open = defineModel<boolean>('open', { default: false })

const email = ref('')
const emailError = ref('')
const gb = ref<string | number>('')
const unlimited = ref(false)
const created = ref<CreatedInvite | null>(null)
const busy = ref(false)

watch(open, (value) => {
  if (!value) return
  email.value = ''
  emailError.value = ''
  unlimited.value = props.defaultQuota === null
  gb.value = props.defaultQuota === null ? '' : quotaToGb(props.defaultQuota)
  created.value = null
})

watch(email, () => (emailError.value = ''))

const quota = computed(() => parseQuotaGb(String(gb.value), unlimited.value))

async function submit() {
  if (busy.value || quota.value === undefined) return
  const address = normalizeEmail(email.value)
  if (!isEmail(address)) {
    emailError.value = t('errors.bad_email')
    return
  }
  busy.value = true
  try {
    created.value = await adminApi.createInvite({ email: address, quota: quota.value })
    emit('created')
  } catch (e) {
    if (e instanceof ApiError && (e.code === 'bad_email' || e.code === 'email_taken')) emailError.value = e.message
    else if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('invite.createFailed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <template v-if="created">
        <DialogTitle>{{ t('invite.ready') }}</DialogTitle>
        <DialogDescription>
          {{ t('invite.readyText', { email: created.email, date: formatDate(created.expires_at) }) }}
        </DialogDescription>
        <CopyField :value="created.url" :label="t('invite.linkLabel')" />
        <DialogFooter class="mt-2">
          <Button variant="outline" @click="open = false">{{ t('common.done') }}</Button>
        </DialogFooter>
      </template>

      <form v-else class="grid gap-4" novalidate @submit.prevent="submit">
        <DialogTitle>{{ t('invite.title') }}</DialogTitle>
        <div class="space-y-2">
          <div class="flex items-center gap-1.5">
            <Label for="invite-email">{{ t('common.email') }}</Label>
            <InfoHint :label="t('invite.emailHintLabel')">{{ t('invite.emailHint') }}</InfoHint>
          </div>
          <Input
            id="invite-email"
            v-model="email"
            type="email"
            inputmode="email"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            maxlength="254"
            :placeholder="t('invite.emailPlaceholder')"
            :aria-invalid="!!emailError"
            aria-describedby="invite-email-error"
          />
          <p v-if="emailError" id="invite-email-error" class="text-sm text-destructive" role="alert">
            {{ emailError }}
          </p>
        </div>
        <QuotaInput id="invite-quota" v-model:gb="gb" v-model:unlimited="unlimited" :disabled="busy" />
        <DialogFooter class="mt-2">
          <Button type="button" variant="outline" :disabled="busy" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button type="submit" :disabled="busy || !email.trim() || quota === undefined">{{ busy ? t('invite.creating') : t('invite.create') }}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>
