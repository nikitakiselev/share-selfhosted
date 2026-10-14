<script setup lang="ts">
import type { EventKind, ShareEvent } from '@/api/types'
import { formatDateFull, shortUserAgent } from '@/lib/format'
import { type MessageKey, t } from '@/lib/i18n'

defineProps<{ events: ShareEvent[] }>()

const KIND: Record<EventKind, MessageKey> = {
  view: 'events.view',
  download: 'events.download',
  zip: 'events.zip',
  play: 'events.play',
}
</script>

<template>
  <p v-if="!events.length" class="text-sm text-muted-foreground">{{ t('events.empty') }}</p>
  <div v-else class="-mx-5 overflow-x-auto px-5">
    <table class="w-full min-w-[640px] text-sm">
      <thead class="text-left text-muted-foreground">
        <tr class="border-b">
          <th class="py-2 pr-4 font-normal">{{ t('events.when') }}</th>
          <th class="py-2 pr-4 font-normal">{{ t('events.what') }}</th>
          <th class="py-2 pr-4 font-normal">{{ t('events.file') }}</th>
          <th class="py-2 pr-4 font-normal">IP</th>
          <th class="py-2 font-normal">{{ t('events.browser') }}</th>
        </tr>
      </thead>
      <tbody class="divide-y">
        <tr v-for="(event, i) in events" :key="i">
          <td class="tabular py-2 pr-4 whitespace-nowrap">{{ formatDateFull(event.ts) }}</td>
          <td class="py-2 pr-4 whitespace-nowrap">{{ KIND[event.kind] ? t(KIND[event.kind]) : event.kind }}</td>
          <td class="max-w-[16rem] truncate py-2 pr-4" :title="event.file_name ?? ''">{{ event.file_name ?? '—' }}</td>
          <td class="tabular py-2 pr-4 whitespace-nowrap">{{ event.ip ?? '—' }}</td>
          <td class="py-2 whitespace-nowrap text-muted-foreground" :title="event.user_agent ?? ''">
            {{ shortUserAgent(event.user_agent) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
