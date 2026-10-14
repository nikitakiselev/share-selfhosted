<script setup lang="ts">
import { Eye, EyeOff, Wand } from '@lucide/vue'
import { ref } from 'vue'
import { Input } from '@/components/ui/input'
import { t } from '@/lib/i18n'
import { generatePassword } from '@/lib/password'

defineProps<{ id: string; placeholder?: string }>()
const model = defineModel<string>({ default: '' })
const visible = ref(false)

function generate() {
  model.value = generatePassword()
  visible.value = true
}
</script>

<template>
  <div class="relative">
    <Input
      :id="id"
      v-model="model"
      :type="visible ? 'text' : 'password'"
      autocomplete="new-password"
      :placeholder="placeholder ?? t('common.noPassword')"
      class="pr-[4.5rem]"
    />
    <div class="absolute top-1/2 right-1 flex -translate-y-1/2">
      <button
        type="button"
        class="flex size-7 items-center justify-center rounded text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        :aria-label="t('password.generate')"
        :title="t('password.generate')"
        @click="generate"
      >
        <Wand class="size-4" />
      </button>
      <button
        type="button"
        class="flex size-7 items-center justify-center rounded text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        :aria-label="visible ? t('common.hidePassword') : t('common.showPassword')"
        @click="visible = !visible"
      >
        <EyeOff v-if="visible" class="size-4" />
        <Eye v-else class="size-4" />
      </button>
    </div>
  </div>
</template>
