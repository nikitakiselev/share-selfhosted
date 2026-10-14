// Before uploading: new files go in order while they fit the limit; resumed uploads always
// go (their space is already taken). The server checks anyway and answers 413 — this is
// to avoid creating uploads and links that are bound to fail.
import { toast } from 'vue-sonner'
import { filesCount, formatSize } from '@/lib/format'
import { t } from '@/lib/i18n'
import { freeSpace, splitByQuota } from '@/lib/quota'
import { partitionResumable, pendingBytes } from '@/upload/engine'
import type { PickedFile } from '@/upload/handles'
import { currentUsage } from './usage'

export function admitFiles(picked: PickedFile[]): PickedFile[] {
  const usage = currentUsage.value
  if (!usage || usage.quota === null) return picked
  const { resumable, fresh } = partitionResumable(picked)
  const free = freeSpace(usage, pendingBytes()) ?? 0
  const { fit, skipped, skippedBytes } = splitByQuota(
    fresh.map((p) => ({ size: p.file.size, picked: p })),
    free,
  )
  if (skipped.length) {
    if (!fit.length && !resumable.length) {
      toast.error(t('errors.quota_exceeded', { needed: formatSize(skippedBytes), free: formatSize(free) }))
    } else {
      toast.warning(
        t('upload.someSkipped', { files: filesCount(skipped.length), size: formatSize(skippedBytes), free: formatSize(free) }),
      )
    }
  }
  return [...resumable, ...fit.map((f) => f.picked)]
}
