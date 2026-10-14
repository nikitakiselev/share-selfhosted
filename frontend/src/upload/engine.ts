// Upload engine: a queue of tus uploads, retries, pausing without network, resuming after
// a page reload. One for the whole app — uploads continue while navigating between admin
// pages.
import * as tus from 'tus-js-client'
import { computed, markRaw, reactive, toRaw, watch } from 'vue'
import { appApi } from '@/api/app'
import type { AdminFile } from '@/api/types'
import { apiErrorText } from '@/lib/http'
import { t } from '@/lib/i18n'
import type { PickedFile } from './handles'
import { matchFiles } from './match'
import { deleteUpload, loadUploads, saveUpload } from './persist'

export type UploadStatus =
  | 'queued' // waiting for its turn
  | 'uploading'
  | 'paused' // no network
  | 'retrying' // failed, retry on a timer
  | 'processing' // uploaded, the server is preparing the video
  | 'done'
  | 'error'
  | 'needs-file' // restored after a reload, needs access to the file

export interface UploadItem {
  key: string
  shareSlug: string
  /** Source file name: with size and time, it identifies the file when resuming. */
  name: string
  /** Name in the link, if set by hand. */
  displayName: string | null
  size: number
  type: string
  lastModified: number
  file: File | null
  handle: FileSystemFileHandle | null
  uploadUrl: string | null
  fileId: string | null
  bytesUploaded: number
  status: UploadStatus
  error: string | null
  retryAt: number | null
  speed: number
  /** Media processing result: whether it can be watched in the browser. */
  media: 'playable' | 'download-only' | 'failed' | null
}

export interface UploadTotals {
  count: number
  finished: number
  size: number
  uploaded: number
  speed: number
  eta: number | null
  active: boolean
}

const CHUNK_SIZE = 64 * 1024 * 1024
const PARALLEL = 2
const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000, 30000, ...Array<number>(60).fill(60000)]
const ENDPOINT = '/api/app/tus/'
const MEDIA_POLL_MS = 5000

const ACTIVE: ReadonlySet<UploadStatus> = new Set(['queued', 'uploading', 'paused', 'retrying'])

const state = reactive({
  items: [] as UploadItem[],
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  now: Date.now(),
  restored: false,
})

// Non-reactive: tus.Upload instances and speed samples.
const running = new Map<string, tus.Upload>()
const samples = new Map<string, { bytes: number; time: number }>()
/** Uploads stopped by us (no network, cancel) — their onError isn't an error. */
const stoppedByUs = new Set<string>()

let initialized = false
let ticker: number | null = null
let mediaPoller: number | null = null
let wakeLock: WakeLockSentinel | null = null

function newKey(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function fileIdFromUrl(url: string | null): string | null {
  if (!url) return null
  const path = url.replace(/[?#].*$/, '').replace(/\/+$/, '')
  return path.slice(path.lastIndexOf('/') + 1) || null
}

function isMedia(item: UploadItem): boolean {
  return /^(video|audio|image)\//.test(item.type) || /\.(mkv|avi|ts|m2ts|mts|mov|mp4|m4v|webm|flv|wmv|heic)$/i.test(item.name)
}

function persist(item: UploadItem): void {
  void saveUpload({
    key: item.key,
    shareSlug: item.shareSlug,
    name: item.name,
    displayName: item.displayName,
    size: item.size,
    type: item.type,
    lastModified: item.lastModified,
    uploadUrl: item.uploadUrl,
    handle: item.handle ? toRaw(item.handle) : null,
    createdAt: Date.now(),
  })
}

function find(key: string): UploadItem | undefined {
  return state.items.find((i) => i.key === key)
}

function errorMessage(error: unknown): string {
  const err = error as tus.DetailedError
  const response = err?.originalResponse
  const status = response?.getStatus?.() ?? 0
  try {
    const body = JSON.parse(response?.getBody?.() ?? '')
    if (body && typeof body.error === 'string') return apiErrorText(status, body)
  } catch {
    // not JSON
  }
  if (status === 401) return t('upload.sessionExpired')
  if (status === 403) return t('common.noAccess')
  if (status === 404) return t('common.linkDeleted')
  if (status === 413) return t('upload.noSpace')
  if (!state.online) return t('upload.offline')
  return status ? t('errors.server', { status }) : t('errors.network')
}

function isFatal(status: number): boolean {
  return status >= 400 && status < 500 && status !== 409 && status !== 423 && status !== 429
}

function sample(item: UploadItem, bytes: number): void {
  const now = performance.now()
  const prev = samples.get(item.key)
  if (!prev || bytes < prev.bytes) {
    samples.set(item.key, { bytes, time: now })
    return
  }
  const dt = now - prev.time
  if (dt < 500) return
  const instant = ((bytes - prev.bytes) * 1000) / dt
  item.speed = item.speed ? item.speed * 0.5 + instant * 0.5 : instant
  samples.set(item.key, { bytes, time: now })
}

function start(item: UploadItem): void {
  if (!item.file) return
  item.status = 'uploading'
  item.error = null
  item.retryAt = null
  item.speed = 0
  samples.delete(item.key)
  stoppedByUs.delete(item.key)

  const sentName = item.displayName ?? item.name
  const upload: tus.Upload = new tus.Upload(item.file, {
    endpoint: ENDPOINT,
    uploadUrl: item.uploadUrl ?? undefined,
    chunkSize: CHUNK_SIZE,
    retryDelays: RETRY_DELAYS,
    metadata: {
      share: item.shareSlug,
      filename: sentName,
      filetype: item.type || 'application/octet-stream',
      lastmodified: String(item.lastModified),
    },
    storeFingerprintForResuming: false,
    removeFingerprintOnSuccess: true,
    onUploadUrlAvailable() {
      item.uploadUrl = upload.url
      item.fileId = fileIdFromUrl(upload.url)
      persist(item)
      // renamed while the file was being created on the server — the metadata went with the old name
      if (item.displayName && item.displayName !== sentName) void renameUpload(item.key, item.displayName).catch(() => {})
    },
    onProgress(bytesSent) {
      item.bytesUploaded = bytesSent
      if (item.status === 'retrying') {
        item.status = 'uploading'
        item.retryAt = null
      }
      sample(item, bytesSent)
    },
    onShouldRetry(error, retryAttempt, options) {
      if (stoppedByUs.has(item.key) || !state.online) return false
      const status = error.originalResponse?.getStatus() ?? 0
      if (isFatal(status)) return false
      const delay = options.retryDelays?.[retryAttempt] ?? 0
      item.status = 'retrying'
      item.retryAt = Date.now() + delay
      item.error = errorMessage(error)
      item.speed = 0
      return true
    },
    onSuccess() {
      running.delete(item.key)
      samples.delete(item.key)
      item.bytesUploaded = item.size
      item.speed = 0
      item.error = null
      item.retryAt = null
      item.status = isMedia(item) ? 'processing' : 'done'
      void deleteUpload(item.key)
      ensureMediaPolling()
      pump()
    },
    onError(error) {
      running.delete(item.key)
      item.speed = 0
      item.retryAt = null
      if (stoppedByUs.has(item.key)) return
      if (!state.online) {
        item.status = 'paused'
        item.error = null
      } else {
        item.status = 'error'
        item.error = errorMessage(error)
      }
      pump()
    },
  })
  running.set(item.key, markRaw(upload))
  upload.start()
}

function pump(): void {
  if (!state.online) return
  let active = state.items.filter((i) => i.status === 'uploading' || i.status === 'retrying').length
  for (const item of state.items) {
    if (active >= PARALLEL) break
    if (item.status === 'queued' && item.file) {
      start(item)
      active++
    }
  }
}

// ——— media processing on the server ———

function applyMedia(item: UploadItem, file: AdminFile | undefined): void {
  if (!file) {
    item.status = 'done'
    return
  }
  if (file.media_status === 'pending') return
  item.status = 'done'
  if (file.media_status === 'failed') item.media = 'failed'
  else if (file.kind === 'video' || file.kind === 'audio') item.media = file.play_url ? 'playable' : 'download-only'
}

async function pollMedia(): Promise<void> {
  const slugs = new Set(state.items.filter((i) => i.status === 'processing').map((i) => i.shareSlug))
  if (!slugs.size) {
    if (mediaPoller !== null) window.clearInterval(mediaPoller)
    mediaPoller = null
    return
  }
  for (const slug of slugs) {
    try {
      const share = await appApi.share(slug)
      for (const item of state.items) {
        if (item.shareSlug !== slug || item.status !== 'processing') continue
        applyMedia(
          item,
          share.files.find((f) => f.id === item.fileId),
        )
      }
    } catch {
      // try again next time
    }
  }
}

function ensureMediaPolling(): void {
  if (mediaPoller !== null) return
  mediaPoller = window.setInterval(() => void pollMedia(), MEDIA_POLL_MS)
  window.setTimeout(() => void pollMedia(), 1500)
}

// ——— network, leaving the page, screen sleep ———

function onOffline(): void {
  state.online = false
  for (const item of state.items) {
    if (item.status !== 'uploading' && item.status !== 'retrying') continue
    const upload = running.get(item.key)
    stoppedByUs.add(item.key)
    running.delete(item.key)
    void upload?.abort(false)
    item.status = 'paused'
    item.speed = 0
    item.retryAt = null
  }
}

function onOnline(): void {
  state.online = true
  for (const item of state.items) {
    if (item.status === 'paused') item.status = 'queued'
  }
  pump()
}

function hasActive(): boolean {
  return state.items.some((i) => ACTIVE.has(i.status) && i.file)
}

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (!hasActive()) return
  event.preventDefault()
  event.returnValue = ''
}

async function acquireWakeLock(): Promise<void> {
  if (wakeLock || !('wakeLock' in navigator) || document.visibilityState !== 'visible') return
  try {
    wakeLock = await navigator.wakeLock.request('screen')
    wakeLock.addEventListener('release', () => {
      wakeLock = null
    })
  } catch {
    wakeLock = null
  }
}

function releaseWakeLock(): void {
  void wakeLock?.release().catch(() => {})
  wakeLock = null
}

function tick(): void {
  state.now = Date.now()
  // speed fades out when bytes stop flowing
  const now = performance.now()
  for (const item of state.items) {
    if (item.status !== 'uploading') continue
    const s = samples.get(item.key)
    if (s && now - s.time > 3000) item.speed *= 0.5
  }
}

// ——— restoring after a reload ———

async function headOffset(url: string): Promise<number | null> {
  try {
    const response = await fetch(url, {
      method: 'HEAD',
      headers: { 'Tus-Resumable': '1.0.0' },
      credentials: 'same-origin',
      cache: 'no-store',
    })
    if (!response.ok) return null
    const offset = Number(response.headers.get('Upload-Offset'))
    return Number.isFinite(offset) ? offset : null
  } catch {
    return null
  }
}

async function restore(): Promise<void> {
  const stored = await loadUploads()
  for (const s of stored) {
    if (find(s.key)) continue
    const item: UploadItem = {
      key: s.key,
      shareSlug: s.shareSlug,
      name: s.name,
      displayName: s.displayName,
      size: s.size,
      type: s.type,
      lastModified: s.lastModified,
      file: null,
      handle: s.handle ? markRaw(s.handle) : null,
      uploadUrl: s.uploadUrl,
      fileId: fileIdFromUrl(s.uploadUrl),
      bytesUploaded: 0,
      status: 'needs-file',
      error: null,
      retryAt: null,
      speed: 0,
      media: null,
    }
    state.items.push(item)
    if (s.uploadUrl) {
      void headOffset(s.uploadUrl).then((offset) => {
        const live = find(item.key)
        if (live && offset !== null) live.bytesUploaded = offset
      })
    }
  }
  state.restored = true
}

// ——— public interface ———

export function initUploads(): void {
  if (initialized || typeof window === 'undefined') return
  initialized = true
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  window.addEventListener('beforeunload', onBeforeUnload)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && hasActive()) void acquireWakeLock()
  })
  watch(
    () => hasActive(),
    (active) => {
      if (active) {
        void acquireWakeLock()
        ticker ??= window.setInterval(tick, 1000)
      } else {
        releaseWakeLock()
        if (ticker !== null) window.clearInterval(ticker)
        ticker = null
      }
    },
    { immediate: true },
  )
  void restore()
}

/**
 * Add files to a link. Files recognized as unfinished after a reload instead continue their
 * uploads (in the link where they started).
 */
export function addFiles(shareSlug: string, picked: PickedFile[]): { resumed: number; added: number } {
  const waiting = state.items.filter((i) => i.status === 'needs-file')
  const { matched, unmatched } = matchFiles(
    waiting,
    picked.map((p) => p.file),
  )
  for (const { key, index } of matched) {
    const item = find(key)
    const { file, handle } = picked[index]!
    if (!item) continue
    item.file = markRaw(file)
    if (handle) item.handle = markRaw(handle)
    item.status = 'queued'
    item.error = null
    if (handle) persist(item)
  }
  for (const index of unmatched) {
    const { file, handle } = picked[index]!
    const item: UploadItem = {
      key: newKey(),
      shareSlug,
      name: file.name,
      displayName: null,
      size: file.size,
      type: file.type,
      lastModified: file.lastModified,
      file: markRaw(file),
      handle: handle ? markRaw(handle) : null,
      uploadUrl: null,
      fileId: null,
      bytesUploaded: 0,
      status: 'queued',
      error: null,
      retryAt: null,
      speed: 0,
      media: null,
    }
    state.items.push(item)
    persist(item)
  }
  pump()
  return { resumed: matched.length, added: unmatched.length }
}

/** Wait until unfinished uploads are loaded from IndexedDB. */
export function whenRestored(): Promise<void> {
  initUploads()
  if (state.restored) return Promise.resolve()
  return new Promise((resolve) => {
    const stop = watch(
      () => state.restored,
      (restored) => {
        if (!restored) return
        stop()
        resolve()
      },
    )
  })
}

/** A link with unfinished uploads — running or waiting for a file. */
export function hasUnfinished(shareSlug: string): boolean {
  return state.items.some((i) => i.shareSlug === shareSlug && i.status !== 'done' && i.status !== 'processing')
}

/**
 * Split picked files: resumed interrupted uploads (the server has already reserved their
 * space) and new ones — only those need checking against the limit.
 */
export function partitionResumable(picked: PickedFile[]): { resumable: PickedFile[]; fresh: PickedFile[] } {
  const waiting = state.items.filter((i) => i.status === 'needs-file')
  const { matched } = matchFiles(
    waiting,
    picked.map((p) => p.file),
  )
  const resumed = new Set(matched.map((m) => m.index))
  return {
    resumable: picked.filter((_, i) => resumed.has(i)),
    fresh: picked.filter((_, i) => !resumed.has(i)),
  }
}

/** Queued bytes the server doesn't count as used yet: the upload isn't created there yet. */
export function pendingBytes(): number {
  return state.items.filter((i) => !i.fileId && ACTIVE.has(i.status)).reduce((sum, i) => sum + i.size, 0)
}

/** Only for uploads unfinished after a reload: check for a match without starting. */
export function matchesWaiting(picked: PickedFile[]): number {
  const waiting = state.items.filter((i) => i.status === 'needs-file')
  return matchFiles(
    waiting,
    picked.map((p) => p.file),
  ).matched.length
}

/** Regain access to files via saved handles. Call from a click handler. */
export async function resumeWithHandles(): Promise<{ resumed: number; failed: number }> {
  let resumed = 0
  let failed = 0
  for (const item of state.items.filter((i) => i.status === 'needs-file' && i.handle)) {
    const handle = item.handle!
    try {
      let permission = await handle.queryPermission({ mode: 'read' })
      if (permission !== 'granted') permission = await handle.requestPermission({ mode: 'read' })
      if (permission !== 'granted') {
        failed++
        continue
      }
      const file = await handle.getFile()
      if (file.size !== item.size || file.lastModified !== item.lastModified) {
        item.error = t('upload.fileChanged')
        failed++
        continue
      }
      item.file = markRaw(file)
      item.status = 'queued'
      item.error = null
      resumed++
    } catch {
      item.handle = null
      item.error = t('upload.noFileAccess')
      failed++
    }
  }
  pump()
  return { resumed, failed }
}

async function terminate(url: string): Promise<void> {
  try {
    await fetch(url, { method: 'DELETE', headers: { 'Tus-Resumable': '1.0.0' }, credentials: 'same-origin' })
  } catch {
    // the server removes an abandoned upload by itself after 7 days
  }
}

/**
 * Set the file name in the link. Until the file exists on the server, the name goes in the
 * creation metadata; after that, via a rename API call. API errors are rethrown.
 */
export async function renameUpload(key: string, name: string): Promise<void> {
  const item = find(key)
  if (!item) return
  if (item.fileId) {
    const updated = await appApi.renameFile(item.shareSlug, item.fileId, name)
    item.displayName = updated.name
  } else {
    // like the server does on rename: it would cut a "/" in tus metadata names along with the beginning
    item.displayName = name.replace(/[/\\]/g, '_')
  }
  persist(item)
}

export async function cancelUpload(key: string): Promise<void> {
  const item = find(key)
  if (!item) return
  stoppedByUs.add(key)
  const upload = running.get(key)
  running.delete(key)
  state.items.splice(state.items.indexOf(item), 1)
  void deleteUpload(key)
  pump()
  if (upload) {
    try {
      await upload.abort(true)
    } catch {
      if (item.uploadUrl) await terminate(item.uploadUrl)
    }
  } else if (item.uploadUrl && item.status !== 'done' && item.status !== 'processing') {
    await terminate(item.uploadUrl)
  }
}

export async function cancelWaiting(): Promise<void> {
  const keys = state.items.filter((i) => i.status === 'needs-file').map((i) => i.key)
  await Promise.all(keys.map(cancelUpload))
}

export function retryUpload(key: string): void {
  const item = find(key)
  if (!item || item.status !== 'error' || !item.file) return
  item.status = 'queued'
  item.error = null
  pump()
}

/** Remove a link's finished uploads from the list (after "New link"). */
export function clearFinished(shareSlug?: string): void {
  state.items = state.items.filter(
    (i) => !((i.status === 'done' || i.status === 'processing') && (!shareSlug || i.shareSlug === shareSlug)),
  )
}

/** The link was deleted — its uploads have nowhere to continue. */
export async function dropShare(shareSlug: string): Promise<void> {
  const keys = state.items.filter((i) => i.shareSlug === shareSlug).map((i) => i.key)
  for (const key of keys) {
    stoppedByUs.add(key)
    void running.get(key)?.abort(false)
    running.delete(key)
    void deleteUpload(key)
  }
  state.items = state.items.filter((i) => i.shareSlug !== shareSlug)
}

export function totalsOf(items: readonly UploadItem[]): UploadTotals {
  let size = 0
  let uploaded = 0
  let speed = 0
  let finished = 0
  let active = false
  for (const item of items) {
    size += item.size
    uploaded += Math.min(item.bytesUploaded, item.size)
    if (item.status === 'uploading') speed += item.speed
    if (item.status === 'done' || item.status === 'processing') finished++
    if (ACTIVE.has(item.status)) active = true
  }
  const remaining = size - uploaded
  return {
    count: items.length,
    finished,
    size,
    uploaded,
    speed,
    eta: speed > 0 && remaining > 0 ? remaining / speed : null,
    active,
  }
}

export function useUploads() {
  initUploads()
  return {
    state,
    waiting: computed(() => state.items.filter((i) => i.status === 'needs-file')),
    waitingWithHandles: computed(() => state.items.filter((i) => i.status === 'needs-file' && i.handle)),
    itemsFor: (shareSlug: string) => computed(() => state.items.filter((i) => i.shareSlug === shareSlug)),
    active: computed(() => state.items.filter((i) => ACTIVE.has(i.status) && i.file)),
    overall: computed(() => totalsOf(state.items.filter((i) => i.status !== 'needs-file'))),
  }
}
