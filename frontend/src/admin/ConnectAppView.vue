<script setup lang="ts">
// Opened by the desktop app as /connect?challenge=<base64url sha256 of its PKCE verifier>.
// After sign-in (AdminLayout shows the form first) the user confirms, the server issues a
// one-time code and the browser hands it to the app through its URL scheme.
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { authApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { handleAuthError, session } from './session'

const APP_SCHEME = 'share-app'
const CHALLENGE_RE = /^[A-Za-z0-9_-]{43}$/

const route = useRoute()
const challenge = computed(() => {
  const raw = route.query.challenge
  return typeof raw === 'string' && CHALLENGE_RE.test(raw) ? raw : null
})

const busy = ref(false)
const error = ref('')
const appUrl = ref('')

async function connect() {
  if (!challenge.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { code } = await authApi.appConnect(challenge.value)
    appUrl.value = `${APP_SCHEME}://connect?code=${encodeURIComponent(code)}`
    window.location.assign(appUrl.value)
  } catch (e) {
    if (!handleAuthError(e)) error.value = e instanceof Error ? e.message : t('connect.failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <!-- inside the admin layout (it already has the header), so no wordmark of its own -->
  <main class="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-xl flex-col justify-center px-5 py-10 sm:px-8">
    <template v-if="!challenge">
      <h1 class="font-display text-[clamp(1.6rem,5vw,2.4rem)] leading-[1.1] font-semibold tracking-[-0.015em]">
        {{ t('page.connect') }}
      </h1>
      <p class="mt-4 max-w-[46ch] text-lg leading-relaxed text-muted-foreground">{{ t('connect.badRequest') }}</p>
    </template>

    <template v-else-if="appUrl">
      <h1 class="font-display text-[clamp(1.6rem,5vw,2.4rem)] leading-[1.1] font-semibold tracking-[-0.015em]">
        {{ t('connect.done') }}
      </h1>
      <p class="mt-4 max-w-[46ch] text-lg leading-relaxed text-muted-foreground">{{ t('connect.doneText') }}</p>
      <div class="mt-8">
        <Button as="a" :href="appUrl" variant="outline">{{ t('connect.open') }}</Button>
      </div>
    </template>

    <template v-else>
      <h1 class="font-display text-[clamp(1.6rem,5vw,2.4rem)] leading-[1.1] font-semibold tracking-[-0.015em]">
        {{ t('connect.title') }}
      </h1>
      <p class="mt-4 max-w-[46ch] text-lg leading-relaxed text-muted-foreground">
        {{ t('connect.text', { email: session.user?.email ?? '' }) }}
      </p>
      <div class="mt-8">
        <Button size="lg" :disabled="busy" @click="connect">
          {{ busy ? t('connect.submitting') : t('connect.submit') }}
        </Button>
      </div>
      <p v-if="error" class="mt-4 text-sm text-destructive" role="alert">{{ error }}</p>
    </template>
  </main>
</template>
