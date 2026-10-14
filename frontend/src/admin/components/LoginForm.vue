<script setup lang="ts">
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import Wordmark from '@/components/Wordmark.vue'
import { t } from '@/lib/i18n'
import { checkSession } from '../session'

const email = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  if (!email.value.trim() || !password.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await authApi.login(email.value.trim(), password.value)
    await checkSession()
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('login.failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-sm flex-col px-5 py-6">
    <Wordmark />
    <form class="flex flex-1 flex-col justify-center pb-[14vh]" novalidate @submit.prevent="submit">
      <h1 class="font-display text-2xl font-semibold tracking-[-0.015em]">{{ t('login.title') }}</h1>
      <p class="mt-2 text-muted-foreground">{{ t('common.tagline') }}</p>
      <label for="email" class="sr-only">{{ t('common.email') }}</label>
      <!-- autocomplete="username": the password manager saved the email as the sign-in name at registration -->
      <Input
        id="email"
        v-model="email"
        type="email"
        inputmode="email"
        autocomplete="username"
        autocapitalize="none"
        spellcheck="false"
        autofocus
        :placeholder="t('common.email')"
        class="mt-6 h-11"
        :aria-invalid="!!error"
      />
      <label for="password" class="sr-only">{{ t('common.password') }}</label>
      <Input
        id="password"
        v-model="password"
        type="password"
        autocomplete="current-password"
        :placeholder="t('common.password')"
        class="mt-3 h-11"
        :aria-invalid="!!error"
      />
      <p v-if="error" class="mt-2 text-sm text-destructive" role="alert">{{ error }}</p>
      <Button type="submit" size="lg" class="mt-4" :disabled="!email.trim() || !password || busy">
        {{ busy ? t('login.submitting') : t('login.submit') }}
      </Button>
      <p class="mt-6 text-sm text-muted-foreground">{{ t('login.inviteOnly') }}</p>
    </form>
  </main>
</template>
