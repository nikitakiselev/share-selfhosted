<script setup lang="ts">
// An "i" icon with an explanation. Opens on hover with a mouse, on tap or key press otherwise:
// a regular tooltip never opens on a phone, hence a popover.
import { Info } from '@lucide/vue'
import { PopoverAnchor, PopoverContent, PopoverPortal, PopoverRoot } from 'reka-ui'
import { ref } from 'vue'
import { t } from '@/lib/i18n'

defineProps<{ label?: string }>()

const open = ref(false)
const button = ref<HTMLButtonElement | null>(null)
let pointer = ''

function onHover(enter: boolean, event: PointerEvent) {
  if (event.pointerType === 'mouse') open.value = enter
}

function onClick(event: MouseEvent) {
  // a mouse already opened it on hover — the click must not close it; detail 0 is Enter/Space
  open.value = event.detail !== 0 && pointer === 'mouse' ? true : !open.value
}

function onInteractOutside(event: Event) {
  // a tap on the icon itself toggles via onClick instead of closing as "outside"
  if (button.value?.contains(event.target as Node)) event.preventDefault()
}
</script>

<template>
  <PopoverRoot v-model:open="open">
    <PopoverAnchor as-child>
      <button
        ref="button"
        type="button"
        :aria-label="label ?? t('common.hint')"
        :aria-expanded="open"
        class="inline-flex size-5 shrink-0 items-center justify-center rounded-full align-middle text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
        @pointerdown="pointer = $event.pointerType"
        @pointerenter="onHover(true, $event)"
        @pointerleave="onHover(false, $event)"
        @click="onClick"
        @keydown.esc="open = false"
      >
        <Info class="size-4" />
      </button>
    </PopoverAnchor>
    <PopoverPortal>
      <PopoverContent
        side="top"
        :side-offset="6"
        :collision-padding="16"
        class="z-50 max-w-[min(18rem,calc(100vw-2rem))] rounded-lg border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md"
        @open-auto-focus.prevent
        @close-auto-focus.prevent
        @interact-outside="onInteractOutside"
      >
        <slot />
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
