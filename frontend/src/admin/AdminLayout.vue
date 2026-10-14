<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { Button } from '@/components/ui/button'
import Wordmark from '@/components/Wordmark.vue'
import { t } from '@/lib/i18n'
import StatusScreen from '@/public/components/StatusScreen.vue'
import { useUploads } from '@/upload/engine'
import LoginForm from './components/LoginForm.vue'
import UsageMeter from './components/UsageMeter.vue'
import UserMenu from './components/UserMenu.vue'
import { newShareRequests } from './draft'
import { checkSession, refreshUser, session } from './session'
import { refreshUsage, usage } from './usage'

const route = useRoute()
const { overall } = useUploads()

const percent = computed(() => (overall.value.size ? Math.floor((overall.value.uploaded / overall.value.size) * 100) : 0))

let usageTimer: number | null = null

onMounted(() => {
  void checkSession()
})
onBeforeUnmount(() => {
  if (usageTimer !== null) window.clearInterval(usageTimer)
})

watch(
  () => session.status,
  (status) => {
    if (status === 'ok') {
      void refreshUsage()
      usageTimer ??= window.setInterval(() => void refreshUsage(), 60_000)
    } else {
      // another user signing in must not see someone else's storage even for a moment
      usage.value = null
    }
  },
  { immediate: true },
)

// Upload percentage in the browser tab — visible even when the window is minimized.
watch(
  () => [overall.value.active, percent.value, route.meta.title] as const,
  ([active, pct, title]) => {
    document.title = `${active ? t('page.uploading', { percent: pct }) : title ? t(title) : 'Share'} — Share`
  },
)

// When uploads finish, used space changes.
watch(
  () => overall.value.finished,
  () => void refreshUsage(),
)

// The limit may have changed while the tab was in the background.
function onVisible() {
  if (document.visibilityState === 'visible' && session.status === 'ok') {
    void refreshUser()
    void refreshUsage()
  }
}
onMounted(() => document.addEventListener('visibilitychange', onVisible))
onBeforeUnmount(() => document.removeEventListener('visibilitychange', onVisible))

// Already on "New link" with a finished link — clicking it again starts a new one
function onNavClick(name: string) {
  if (name === 'new' && route.name === 'new') newShareRequests.value++
}

const nav = computed(() => [
  { to: { name: 'new' }, label: t('page.new'), name: 'new', class: '' },
  { to: { name: 'shares' }, label: t('page.shares'), name: 'shares', class: '' },
  // the third item doesn't fit on a phone — it's in the account menu there
  ...(session.user?.role === 'admin'
    ? [{ to: { name: 'users' }, label: t('page.users'), name: 'users', class: 'hidden sm:block' }]
    : []),
])
</script>

<template>
  <div v-if="session.status === 'loading'" class="flex min-h-dvh items-center justify-center text-muted-foreground">
    <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
  </div>

  <StatusScreen
    v-else-if="session.status === 'forbidden'"
    :title="t('common.noAccess')"
    :text="t('admin.forbiddenText')"
  />

  <StatusScreen
    v-else-if="session.status === 'offline'"
    :title="t('common.serverDown')"
    :text="t('common.serverDownText')"
  >
    <Button variant="outline" @click="checkSession">{{ t('common.retry') }}</Button>
  </StatusScreen>

  <LoginForm v-else-if="session.status === 'login'" />

  <div v-else class="min-h-dvh">
    <header class="border-b bg-card/70 backdrop-blur supports-[backdrop-filter]:bg-card/60">
      <div class="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:gap-6 sm:px-8">
        <RouterLink
          :to="{ name: 'new' }"
          class="rounded outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          @click="onNavClick('new')"
        >
          <Wordmark />
        </RouterLink>
        <nav class="flex gap-1">
          <RouterLink
            v-for="item in nav"
            :key="item.name"
            :to="item.to"
            @click="onNavClick(item.name)"
            class="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 sm:px-3"
            :class="[
              item.class,
              (route.name === item.name || (item.name === 'shares' && route.name === 'share')) && 'bg-muted text-foreground',
            ]"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
        <div class="ml-auto flex items-center gap-3 sm:gap-5">
          <p v-if="overall.active" class="tabular hidden items-center gap-1.5 text-sm text-primary sm:flex">
            <LoaderCircle class="size-3.5 animate-spin" />
            {{ percent }}%
          </p>
          <UsageMeter class="hidden md:block" />
          <UserMenu />
        </div>
      </div>
    </header>
    <RouterView />
  </div>
</template>
