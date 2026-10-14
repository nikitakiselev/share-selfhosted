<script setup lang="ts">
// A user's limit — stays until it's changed here.
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { adminApi } from '@/api/admin'
import type { AdminUser } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { parseQuotaGb, quotaToGb } from '@/lib/quota'
import { handleAuthError } from '../session'
import QuotaInput from './QuotaInput.vue'

const props = defineProps<{ user: AdminUser | null }>()
const emit = defineEmits<{ saved: [user: AdminUser] }>()
const open = defineModel<boolean>('open', { default: false })

const gb = ref<string | number>('')
const unlimited = ref(false)
const busy = ref(false)

watch(open, (value) => {
  if (!value || !props.user) return
  unlimited.value = props.user.quota === null
  gb.value = props.user.quota === null ? '' : quotaToGb(props.user.quota)
})

const quota = computed(() => parseQuotaGb(String(gb.value), unlimited.value))
const changed = computed(() => !!props.user && quota.value !== undefined && quota.value !== props.user.quota)

async function save() {
  const user = props.user
  if (!user || busy.value || quota.value === undefined) return
  busy.value = true
  try {
    const saved = await adminApi.updateUser(user.id, { quota: quota.value })
    open.value = false
    toast.success(
      saved.quota === null
        ? t('quota.savedUnlimited', { login: saved.login })
        : t('quota.savedLimit', { login: saved.login, size: formatSize(saved.quota) }),
    )
    emit('saved', saved)
  } catch (e) {
    if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t('quota.saveFailed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <form class="grid gap-4" novalidate @submit.prevent="save">
        <DialogTitle>{{ t('quota.dialogTitle', { login: user?.login ?? '' }) }}</DialogTitle>
        <DialogDescription v-if="user">{{ t('quota.used', { size: formatSize(user.used) }) }}</DialogDescription>
        <QuotaInput id="user-quota" v-model:gb="gb" v-model:unlimited="unlimited" :disabled="busy" />
        <DialogFooter class="mt-2">
          <Button type="button" variant="outline" :disabled="busy" @click="open = false">{{ t('common.cancel') }}</Button>
          <Button type="submit" :disabled="busy || !changed">{{ busy ? t('common.saving') : t('common.save') }}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>
