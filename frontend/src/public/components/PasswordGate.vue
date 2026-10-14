<script setup lang="ts">
import { Eye, EyeOff, LockKeyhole } from '@lucide/vue'
import { ref } from 'vue'
import { publicApi } from '@/api/public'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import Wordmark from '@/components/Wordmark.vue'
import { ApiError } from '@/lib/http'
import { t } from '@/lib/i18n'

const props = defineProps<{ slug: string }>()
const emit = defineEmits<{ unlocked: [] }>()

const password = ref('')
const visible = ref(false)
const busy = ref(false)
const error = ref('')

async function submit() {
  if (!password.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await publicApi.unlock(props.slug, password.value)
    emit('unlocked')
  } catch (e) {
    if (e instanceof ApiError && e.code === 'wrong_password') error.value = t('gate.wrong')
    else error.value = e instanceof Error ? e.message : t('gate.failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-md flex-col px-5 py-6 sm:px-8">
    <Wordmark class="text-muted-foreground" />
    <form class="flex flex-1 flex-col justify-center pb-[12vh]" @submit.prevent="submit">
      <LockKeyhole class="size-7 text-primary" stroke-width="1.75" />
      <h1 class="mt-5 font-display text-[1.75rem] leading-[1.15] font-semibold tracking-[-0.015em]">
        {{ t('gate.title') }}
      </h1>
      <p class="mt-3 text-muted-foreground">{{ t('gate.text') }}</p>
      <label for="share-password" class="sr-only">{{ t('common.password') }}</label>
      <div class="relative mt-7">
        <Input
          id="share-password"
          v-model="password"
          :type="visible ? 'text' : 'password'"
          autocomplete="current-password"
          autofocus
          :placeholder="t('common.password')"
          class="h-12 pr-12 text-base"
          :aria-invalid="!!error"
        />
        <button
          type="button"
          class="absolute top-1/2 right-2 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          :aria-label="visible ? t('common.hidePassword') : t('common.showPassword')"
          @click="visible = !visible"
        >
          <EyeOff v-if="visible" class="size-4" />
          <Eye v-else class="size-4" />
        </button>
      </div>
      <p v-if="error" class="mt-3 text-sm text-destructive" role="alert">{{ error }}</p>
      <Button type="submit" size="lg" class="mt-5 w-full" :disabled="!password || busy">
        {{ busy ? t('gate.submitting') : t('gate.submit') }}
      </Button>
    </form>
  </main>
</template>
