<script setup lang="ts">
import { CircleUser, Download, KeyRound, LogOut, MonitorSmartphone, Users } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { authApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { session, signedOut } from '../session'
import { currentUsage } from '../usage'
import ChangePasswordDialog from './ChangePasswordDialog.vue'

const router = useRouter()
const passwordOpen = ref(false)
// The menu bar app for macOS: the zip attached to the latest GitHub release under a fixed name
const MAC_APP_URL = 'https://github.com/nikitakiselev/share-selfhosted/releases/latest/download/Share-macOS.zip'

const usageLine = computed(() => {
  const u = currentUsage.value
  if (!u) return ''
  return u.quota === null
    ? t('account.usageUnlimited', { used: formatSize(u.used) })
    : t('common.xOfY', { x: formatSize(u.used), y: formatSize(u.quota) })
})

// The menu closes and returns focus to its button — the dialog opens after that.
function openPassword() {
  window.setTimeout(() => (passwordOpen.value = true), 0)
}

async function logout(everywhere: boolean) {
  try {
    await (everywhere ? authApi.logoutAll() : authApi.logout())
  } catch (e) {
    if (everywhere) {
      toast.error(e instanceof Error ? e.message : t('account.logoutFailed'))
      return
    }
  }
  signedOut()
}
</script>

<template>
  <DropdownMenu v-if="session.user">
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="sm" class="max-w-40 gap-1.5 px-2" :aria-label="t('account.label', { login: session.user.login })">
        <CircleUser />
        <span class="hidden truncate sm:inline">{{ session.user.login }}</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent class="w-60">
      <DropdownMenuLabel>
        <p class="truncate font-medium">{{ session.user.login }}</p>
        <p v-if="session.user.email" class="truncate text-muted-foreground" :title="session.user.email">
          {{ session.user.email }}
        </p>
        <p v-if="session.user.role === 'admin'" class="mt-0.5 text-muted-foreground">{{ t('account.admin') }}</p>
        <p v-if="usageLine" class="tabular text-muted-foreground">{{ usageLine }}</p>
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem v-if="session.user.role === 'admin'" class="sm:hidden" @select="router.push({ name: 'users' })">
        <Users />
        {{ t('page.users') }}
      </DropdownMenuItem>
      <DropdownMenuItem @select="openPassword">
        <KeyRound />
        {{ t('password.title') }}
      </DropdownMenuItem>
      <DropdownMenuItem as="a" :href="MAC_APP_URL">
        <Download />
        {{ t('account.macApp') }}
      </DropdownMenuItem>
      <DropdownMenuItem @select="logout(true)">
        <MonitorSmartphone />
        {{ t('account.logoutAll') }}
      </DropdownMenuItem>
      <DropdownMenuItem @select="logout(false)">
        <LogOut />
        {{ t('account.logout') }}
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
  <ChangePasswordDialog v-model:open="passwordOpen" />
</template>
