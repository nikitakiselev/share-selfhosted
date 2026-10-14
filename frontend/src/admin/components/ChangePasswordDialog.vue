<script setup lang="ts">
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { authApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import { PASSWORD_MIN } from '@/lib/quota'
import { handleAuthError, session } from '../session'

const open = defineModel<boolean>('open', { default: false })

const current = ref('')
const next = ref('')
const repeat = ref('')
const busy = ref(false)
const error = ref('')

watch(open, (value) => {
  if (!value) return
  current.value = next.value = repeat.value = error.value = ''
})

function validate(): string {
  if (next.value.length < PASSWORD_MIN) return t('password.newTooShort', { min: PASSWORD_MIN })
  if (next.value !== repeat.value) return t('password.mismatch')
  return ''
}

async function submit() {
  error.value = validate()
  if (error.value || busy.value) return
  busy.value = true
  try {
    await authApi.changePassword(current.value, next.value)
    open.value = false
    toast.success(t('password.changed'))
  } catch (e) {
    if (handleAuthError(e)) return
    if (e instanceof ApiError && e.code === 'wrong_password') error.value = t('password.wrongCurrent')
    else error.value = e instanceof Error ? e.message : t('password.changeFailed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogTitle>{{ t('password.title') }}</DialogTitle>
      <form class="grid gap-4" @submit.prevent="submit">
        <!-- the password manager updates the entry for the email used to sign in -->
        <input
          type="email"
          autocomplete="username"
          :value="session.user?.email ?? session.user?.login ?? ''"
          class="hidden"
          readonly
        />
        <div class="space-y-2">
          <Label for="pw-current">{{ t('password.current') }}</Label>
          <Input id="pw-current" v-model="current" type="password" autocomplete="current-password" />
        </div>
        <div class="space-y-2">
          <Label for="pw-new">{{ t('password.new') }}</Label>
          <Input id="pw-new" v-model="next" type="password" autocomplete="new-password" :placeholder="t('password.minLength', { min: PASSWORD_MIN })" />
        </div>
        <div class="space-y-2">
          <Label for="pw-repeat">{{ t('password.repeat') }}</Label>
          <Input id="pw-repeat" v-model="repeat" type="password" autocomplete="new-password" />
        </div>
        <p v-if="error" class="text-sm text-destructive" role="alert">{{ error }}</p>
        <DialogFooter>
          <Button type="button" variant="outline" :disabled="busy" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button type="submit" :disabled="busy || !current || !next || !repeat">{{ busy ? t('common.saving') : t('password.submit') }}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>
