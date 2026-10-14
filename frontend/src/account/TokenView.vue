<script setup lang="ts">
// Links from the administrator: an invitation (the email is fixed, the person picks a username
// and a password) and a password reset. Success signs in right away.
import { LoaderCircle } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '@/api/auth'
import type { TokenInfo } from '@/api/types'
import InfoHint from '@/components/InfoHint.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Wordmark from '@/components/Wordmark.vue'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'
import { LOGIN_RE, normalizeLogin, PASSWORD_MIN } from '@/lib/quota'
import StatusScreen from '@/public/components/StatusScreen.vue'
import { session } from '@/admin/session'

const props = defineProps<{ token: string; kind: 'invite' | 'reset' }>()
const router = useRouter()

type State = 'loading' | 'form' | 'not-found' | 'expired' | 'offline'

const state = ref<State>('loading')
const info = ref<TokenInfo | null>(null)
const login = ref('')
const password = ref('')
const repeat = ref('')
const busy = ref(false)
const error = ref('')

// the server knows what kind of link it is better than the address does
const isInvite = computed(() => (info.value?.kind ?? props.kind) === 'invite')

function fail(e: unknown): boolean {
  if (!(e instanceof ApiError)) return false
  if (e.status === 404) state.value = 'not-found'
  else if (e.status === 410) state.value = 'expired'
  else return false
  return true
}

async function load() {
  state.value = 'loading'
  try {
    info.value = await authApi.token(props.token)
    state.value = 'form'
  } catch (e) {
    if (!fail(e)) state.value = 'offline'
  }
}

onMounted(load)

function validate(): string {
  if (isInvite.value && !LOGIN_RE.test(normalizeLogin(login.value))) return t('token.badUsername')
  if (password.value.length < PASSWORD_MIN) return t('password.tooShort', { min: PASSWORD_MIN })
  if (password.value !== repeat.value) return t('password.mismatch')
  return ''
}

async function submit() {
  error.value = validate()
  if (error.value || busy.value) return
  busy.value = true
  try {
    await authApi.useToken(
      props.token,
      isInvite.value ? { login: normalizeLogin(login.value), password: password.value } : { password: password.value },
    )
    // the admin asks who signed in when it opens; the previous user must not flash
    session.user = null
    session.status = 'loading'
    await router.replace({ name: 'new' })
  } catch (e) {
    if (fail(e)) return
    if (e instanceof ApiError && e.code === 'email_taken') error.value = t('token.emailTaken')
    else error.value = e instanceof Error ? e.message : t('common.saveFailed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="state === 'loading'" class="flex min-h-dvh items-center justify-center text-muted-foreground">
    <LoaderCircle class="size-6 animate-spin" :aria-label="t('common.loading')" />
  </div>

  <StatusScreen
    v-else-if="state === 'not-found'"
    :title="t('common.linkNotFound')"
    :text="t('token.notFoundText')"
  />

  <StatusScreen
    v-else-if="state === 'expired'"
    :title="isInvite ? t('token.inviteInvalid') : t('token.resetInvalid')"
    :text="isInvite ? t('token.inviteInvalidText') : t('token.resetInvalidText')"
  />

  <StatusScreen v-else-if="state === 'offline'" :title="t('common.serverDown')" :text="t('common.serverDownText')">
    <Button variant="outline" @click="load">{{ t('common.retry') }}</Button>
  </StatusScreen>

  <main v-else class="mx-auto flex min-h-dvh max-w-sm flex-col px-5 py-6">
    <Wordmark />
    <form class="flex flex-1 flex-col justify-center pb-[14vh]" @submit.prevent="submit">
      <h1 class="font-display text-2xl font-semibold tracking-[-0.015em]">
        {{ isInvite ? t('token.inviteTitle') : t('page.reset') }}
      </h1>
      <p class="mt-2 text-muted-foreground">
        <template v-if="isInvite">{{ t('common.tagline') }}</template>
        <template v-else-if="info?.email || info?.login">
          {{ t('token.for', { who: info.email ?? t('token.forUser', { login: info.login ?? '' }) }) }}
        </template>
      </p>

      <div class="mt-6 grid gap-4">
        <!-- the administrator set the email and it can't be changed; autocomplete="username" makes the
             password manager save the password for the sign-in email, not for the username -->
        <div v-if="isInvite && info?.email" class="space-y-2">
          <Label for="email">{{ t('common.email') }}</Label>
          <Input
            id="email"
            type="email"
            :model-value="info.email"
            autocomplete="username"
            readonly
            class="h-11 bg-muted/50 text-muted-foreground"
          />
        </div>
        <input v-else type="email" autocomplete="username" :value="info?.email ?? info?.login ?? ''" class="hidden" readonly />
        <div v-if="isInvite" class="space-y-2">
          <div class="flex items-center gap-1.5">
            <Label for="login">{{ t('token.username') }}</Label>
            <InfoHint :label="t('token.usernameHintLabel')">{{ t('token.usernameHint') }}</InfoHint>
          </div>
          <Input
            id="login"
            v-model="login"
            autocomplete="nickname"
            autocapitalize="none"
            spellcheck="false"
            autofocus
            class="h-11"
          />
        </div>
        <div class="space-y-2">
          <Label for="password">{{ isInvite ? t('common.password') : t('password.new') }}</Label>
          <Input
            id="password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            :autofocus="!isInvite"
            :placeholder="t('password.minLength', { min: PASSWORD_MIN })"
            class="h-11"
          />
        </div>
        <div class="space-y-2">
          <Label for="repeat">{{ t('password.repeat') }}</Label>
          <Input id="repeat" v-model="repeat" type="password" autocomplete="new-password" class="h-11" />
        </div>
      </div>

      <p v-if="error" class="mt-3 text-sm text-destructive" role="alert">{{ error }}</p>
      <Button
        type="submit"
        size="lg"
        class="mt-5"
        :disabled="busy || !password || !repeat || (isInvite && !login.trim())"
      >
        {{ busy ? t('common.saving') : isInvite ? t('token.createAccount') : t('token.saveAndSignIn') }}
      </Button>
    </form>
  </main>
</template>
