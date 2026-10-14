<script setup lang="ts">
// Users and invitations. Administrator only, and only from the internal network —
// other users' files aren't visible here, only storage, limit and link count.
import {
  Ban,
  CircleCheck,
  HardDrive,
  KeyRound,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  Trash2,
  UserPlus,
} from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { adminApi } from '@/api/admin'
import type { AdminUser, Invite, UsersResponse } from '@/api/types'
import InfoHint from '@/components/InfoHint.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatDate, formatRelative, formatSize } from '@/lib/format'
import { ApiError } from '@/lib/http'
import { type MessageKey, t } from '@/lib/i18n'
import { isOverQuota, quotaRatio } from '@/lib/quota'
import { cn } from '@/lib/utils'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CopyField from './components/CopyField.vue'
import InviteDialog from './components/InviteDialog.vue'
import QuotaDialog from './components/QuotaDialog.vue'
import { handleAuthError, session } from './session'

const data = ref<UsersResponse | null>(null)
const invites = ref<Invite[] | null>(null)
const forbidden = ref(false)
const error = ref('')

const allowed = computed(() => session.user?.role === 'admin' && session.user.admin_panel && !forbidden.value)

async function load() {
  try {
    const [users, list] = await Promise.all([adminApi.users(), adminApi.invites()])
    data.value = users
    invites.value = list.invites
    error.value = ''
  } catch (e) {
    if (handleAuthError(e)) return
    if (e instanceof ApiError && e.status === 403) forbidden.value = true
    else error.value = e instanceof Error ? e.message : t('common.loadListFailed')
  }
}

// admin_panel is re-read on returning to the tab: once on the internal network, the page comes alive
watch(
  () => session.user?.admin_panel,
  (panel) => {
    if (!panel) return
    forbidden.value = false
    void load()
  },
  { immediate: true },
)

const disk = computed(() => {
  const d = data.value?.disk
  if (!d?.total) return null
  return { ...d, ratio: Math.min(1, d.used / d.total), low: d.free / d.total < 0.1 }
})

const sorted = computed(() => {
  // the administrator first, then by used space
  return [...(data.value?.users ?? [])].sort((a, b) =>
    a.role !== b.role ? (a.role === 'admin' ? -1 : 1) : b.used - a.used,
  )
})

// --- actions ----------------------------------------------------------------

const quotaUser = ref<AdminUser | null>(null)
const quotaOpen = ref(false)
const inviteOpen = ref(false)
// a finished link — password reset or a new invitation: shown in full and copyable
interface Link {
  title: string
  description: string
  label: string
  url: string
}
const link = ref<Link | null>(null)
const linkOpen = ref(false)
const renewing = ref<number | null>(null)

interface Confirm {
  title: string
  description: string
  confirmLabel: string
  busyLabel: string
  action: () => Promise<void>
}
const confirm = ref<Confirm | null>(null)
const confirmOpen = ref(false)

function ask(value: Confirm) {
  confirm.value = value
  // the menu closes and returns focus to its button — the dialog opens after that
  window.setTimeout(() => (confirmOpen.value = true), 0)
}

function openQuota(user: AdminUser) {
  quotaUser.value = user
  window.setTimeout(() => (quotaOpen.value = true), 0)
}

function failed(e: unknown, fallback: MessageKey) {
  if (!handleAuthError(e)) toast.error(e instanceof Error ? e.message : t(fallback))
}

async function makeResetLink(user: AdminUser) {
  try {
    const reset = await adminApi.resetLink(user.id)
    link.value = {
      title: t('users.resetTitle', { login: user.login }),
      description: t('users.resetText', { date: formatDate(reset.expires_at) }),
      label: t('users.resetLink'),
      url: reset.url,
    }
    linkOpen.value = true
  } catch (e) {
    failed(e, 'common.createLinkFailed')
  }
}

async function setBlocked(user: AdminUser, blocked: boolean) {
  try {
    await adminApi.updateUser(user.id, { blocked })
    toast.success(t(blocked ? 'users.blocked' : 'users.unblocked', { login: user.login }))
    await load()
  } catch (e) {
    failed(e, 'common.failed')
  }
}

function askBlock(user: AdminUser) {
  ask({
    title: t('users.blockTitle', { login: user.login }),
    description: t('users.blockText'),
    confirmLabel: t('users.block'),
    busyLabel: t('users.blocking'),
    action: () => setBlocked(user, true),
  })
}

function askDelete(user: AdminUser) {
  ask({
    title: t('users.deleteTitle', { login: user.login }),
    description: user.share_count
      ? t('users.deleteText', { count: user.share_count, size: formatSize(user.used) })
      : t('users.deleteEmpty'),
    confirmLabel: t('common.delete'),
    busyLabel: t('common.deleting'),
    action: async () => {
      try {
        await adminApi.deleteUser(user.id)
        toast.success(t('users.deleted', { login: user.login }))
        await load()
      } catch (e) {
        failed(e, 'common.deleteFailed')
      }
    },
  })
}

async function renewInvite(invite: Invite) {
  if (renewing.value !== null) return
  renewing.value = invite.id
  try {
    const renewed = await adminApi.renewInvite(invite.id)
    link.value = {
      title: t('users.renewTitle'),
      description: t('users.renewText', { email: renewed.email, date: formatDate(renewed.expires_at) }),
      label: t('invite.linkLabel'),
      url: renewed.url,
    }
    linkOpen.value = true
    await load()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      toast.error(t('users.inviteGone'))
      await load()
    } else failed(e, 'common.createLinkFailed')
  } finally {
    renewing.value = null
  }
}

function askRevoke(invite: Invite) {
  ask({
    title: t('users.revokeTitle'),
    description: t('users.revokeText', { email: invite.email }),
    confirmLabel: t('users.revoke'),
    busyLabel: t('users.revoking'),
    action: async () => {
      try {
        await adminApi.revokeInvite(invite.id)
        await load()
      } catch (e) {
        failed(e, 'users.revokeFailed')
      }
    },
  })
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-4 py-8 sm:px-8">
    <div class="mb-6 flex items-center justify-between gap-4">
      <h1 class="font-display text-2xl font-semibold tracking-[-0.015em]">{{ t('page.users') }}</h1>
      <Button v-if="allowed && data" variant="outline" :aria-label="t('invite.title')" @click="inviteOpen = true">
        <UserPlus />
        <span class="hidden sm:inline">{{ t('invite.title') }}</span>
      </Button>
    </div>

    <div v-if="session.user?.role !== 'admin'" class="rounded-xl border border-dashed px-6 py-16 text-center">
      <p class="font-medium">{{ t('users.adminOnly') }}</p>
    </div>

    <div v-else-if="!allowed" class="rounded-xl border border-dashed px-6 py-16 text-center">
      <p class="font-medium">{{ t('users.internalOnly') }}</p>
      <p class="mt-1 text-muted-foreground">{{ t('users.uploadAnywhere') }}</p>
    </div>

    <p v-else-if="error && !data" class="text-destructive">{{ error }}</p>

    <div v-else-if="!data" class="flex justify-center py-16 text-muted-foreground">
      <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
    </div>

    <template v-else>
      <!-- disk -->
      <section class="mb-6 grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-3 sm:p-5">
        <div v-if="disk" class="sm:col-span-2">
          <p class="text-sm text-muted-foreground">{{ t('users.disk') }}</p>
          <p class="tabular mt-1 font-medium">
            {{ formatSize(disk.used) }}
            <span class="text-muted-foreground">{{ t('common.ofY', { y: formatSize(disk.total) }) }}</span>
          </p>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              :class="cn('h-full rounded-full', disk.low ? 'bg-destructive' : 'bg-foreground/45')"
              :style="{ width: `${disk.ratio * 100}%` }"
            />
          </div>
          <p :class="cn('tabular mt-1 text-sm', disk.low ? 'text-destructive' : 'text-muted-foreground')">
            {{ t('common.free', { size: formatSize(disk.free) }) }}
          </p>
        </div>
        <div>
          <p class="flex items-center gap-1.5 text-sm text-muted-foreground">
            {{ t('users.allocated') }}
            <InfoHint :label="t('users.allocatedHintLabel')">{{ t('users.allocatedHint') }}</InfoHint>
          </p>
          <p class="tabular mt-1 font-medium">{{ formatSize(data.allocated) }}</p>
        </div>
      </section>

      <!-- users: on a phone, rows "login and menu", "storage", "links"; columns on wide screens -->
      <ul class="divide-y rounded-xl border bg-card">
        <li
          v-for="user in sorted"
          :key="user.id"
          :class="
            cn(
              'grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-3 p-4 sm:p-5 md:grid-cols-[minmax(0,1fr)_12rem_9rem_2rem] md:items-center lg:gap-x-6',
              user.blocked && 'bg-muted/40',
            )
          "
        >
          <div class="min-w-0">
            <p class="flex flex-wrap items-center gap-2">
              <span :class="cn('truncate font-medium', user.blocked && 'text-muted-foreground')">{{ user.login }}</span>
              <Badge v-if="user.role === 'admin'" variant="secondary">{{ t('users.adminBadge') }}</Badge>
              <Badge v-if="user.blocked" variant="destructive">{{ t('users.blockedBadge') }}</Badge>
            </p>
            <p v-if="user.email" class="mt-0.5 truncate text-sm text-muted-foreground" :title="user.email">
              {{ user.email }}
            </p>
            <p class="mt-1 text-sm text-muted-foreground">{{ t('users.since', { date: formatDate(user.created_at, false) }) }}</p>
          </div>

          <div class="col-span-2 md:col-span-1">
            <p :class="cn('tabular text-sm', isOverQuota(user) && 'text-destructive')">
              {{ formatSize(user.used) }}
              <span v-if="user.quota !== null" :class="!isOverQuota(user) && 'text-muted-foreground'">
                {{ t('common.ofY', { y: formatSize(user.quota) }) }}
              </span>
            </p>
            <div v-if="user.quota !== null" class="mt-1.5 h-1 overflow-hidden rounded-full bg-muted">
              <div
                :class="cn('h-full rounded-full', isOverQuota(user) ? 'bg-destructive' : 'bg-foreground/45')"
                :style="{ width: `${(quotaRatio(user) ?? 0) * 100}%` }"
              />
            </div>
            <p v-else class="mt-1 text-sm text-muted-foreground">{{ t('common.unlimited') }}</p>
          </div>

          <div class="col-span-2 text-sm md:col-span-1">
            <p class="tabular">{{ t('count.shares', { count: user.share_count }) }}</p>
            <p class="mt-1 text-muted-foreground" :title="user.last_login_at ? formatDate(user.last_login_at) : undefined">
              {{
                user.last_login_at
                  ? t('users.lastLogin', { relative: formatRelative(user.last_login_at) })
                  : t('users.neverSignedIn')
              }}
            </p>
          </div>

          <!-- on a phone the menu is right of the login, on wide screens it's the last column -->
          <div class="col-start-2 row-start-1 flex justify-end md:col-start-4">
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <Button variant="ghost" size="icon-sm" :aria-label="t('users.actions', { login: user.login })">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" class="w-60">
                <DropdownMenuItem @select="openQuota(user)">
                  <HardDrive />
                  {{ t('users.limit') }}
                </DropdownMenuItem>
                <!-- the administrator can't be blocked or deleted — the server forbids it -->
                <template v-if="user.role !== 'admin'">
                  <DropdownMenuItem @select="makeResetLink(user)">
                    <KeyRound />
                    {{ t('users.resetLink') }}
                  </DropdownMenuItem>
                  <DropdownMenuItem v-if="user.blocked" @select="setBlocked(user, false)">
                    <CircleCheck />
                    {{ t('users.unblock') }}
                  </DropdownMenuItem>
                  <DropdownMenuItem v-else @select="askBlock(user)">
                    <Ban />
                    {{ t('users.block') }}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem destructive @select="askDelete(user)">
                    <Trash2 />
                    {{ t('common.delete') }}
                  </DropdownMenuItem>
                </template>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </li>
      </ul>

      <!-- invitations -->
      <section class="mt-10">
        <h2 class="font-display text-lg font-semibold tracking-[-0.01em]">{{ t('users.invites') }}</h2>
        <p v-if="!invites?.length" class="mt-3 text-muted-foreground">{{ t('users.noInvites') }}</p>
        <ul v-else class="mt-3 divide-y rounded-xl border bg-card">
          <!-- on a phone the email is on its own row, with limit, expiry and actions below it -->
          <li
            v-for="invite in invites"
            :key="invite.id"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:flex-nowrap sm:gap-x-4 sm:px-5"
          >
            <span class="w-full min-w-0 truncate sm:w-auto sm:flex-1" :title="invite.email">{{ invite.email }}</span>
            <Badge variant="secondary">{{ invite.quota === null ? t('common.unlimited') : formatSize(invite.quota) }}</Badge>
            <span class="text-sm whitespace-nowrap text-muted-foreground" :title="formatDate(invite.expires_at)">
              {{ t('users.inviteUntil', { date: formatDate(invite.expires_at, false) }) }}
            </span>
            <span class="ml-auto flex shrink-0 gap-1 sm:ml-0">
              <Button variant="ghost" size="sm" :disabled="renewing !== null" @click="renewInvite(invite)">
                <LoaderCircle v-if="renewing === invite.id" class="animate-spin" />
                <Link2 v-else />
                {{ t('users.renewInvite') }}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="text-muted-foreground hover:text-destructive"
                @click="askRevoke(invite)"
              >
                {{ t('users.revoke') }}
              </Button>
            </span>
          </li>
        </ul>
      </section>
    </template>

    <QuotaDialog v-model:open="quotaOpen" :user="quotaUser" @saved="load" />
    <InviteDialog v-model:open="inviteOpen" :default-quota="data?.default_quota ?? null" @created="load" />

    <Dialog v-model:open="linkOpen">
      <DialogContent>
        <DialogTitle>{{ link?.title }}</DialogTitle>
        <DialogDescription>{{ link?.description }}</DialogDescription>
        <CopyField v-if="link" :value="link.url" :label="link.label" />
        <DialogFooter class="mt-2">
          <Button variant="outline" @click="linkOpen = false">{{ t('common.done') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <ConfirmDialog
      v-if="confirm"
      v-model:open="confirmOpen"
      :title="confirm.title"
      :description="confirm.description"
      :confirm-label="confirm.confirmLabel"
      :busy-label="confirm.busyLabel"
      :action="confirm.action"
    />
  </main>
</template>
