// Unfinished uploads in IndexedDB — to survive a page reload. A FileSystemFileHandle
// (Chromium) is saved by structured cloning; where it's missing or IndexedDB is unavailable
// (private mode), everything degrades to "drag it again".
import { type IDBPDatabase, openDB } from 'idb'

export interface StoredUpload {
  key: string
  shareSlug: string
  name: string
  /** Name in the link, if set by hand. */
  displayName: string | null
  size: number
  type: string
  lastModified: number
  uploadUrl: string | null
  handle: FileSystemFileHandle | null
  createdAt: number
}

const STORE = 'uploads'
let dbPromise: Promise<IDBPDatabase> | null = null

function db(): Promise<IDBPDatabase> {
  dbPromise ??= openDB('share-uploads', 1, {
    upgrade(database) {
      database.createObjectStore(STORE, { keyPath: 'key' })
    },
  })
  return dbPromise
}

export async function saveUpload(upload: StoredUpload): Promise<void> {
  try {
    await (await db()).put(STORE, upload)
  } catch {
    if (!upload.handle) return
    try {
      await (await db()).put(STORE, { ...upload, handle: null })
    } catch {
      // IndexedDB is unavailable — resuming after a reload just won't be offered
    }
  }
}

export async function deleteUpload(key: string): Promise<void> {
  try {
    await (await db()).delete(STORE, key)
  } catch {
    // nothing to do
  }
}

export async function loadUploads(): Promise<StoredUpload[]> {
  try {
    const all = (await (await db()).getAll(STORE)) as StoredUpload[]
    return all.sort((a, b) => a.createdAt - b.createdAt)
  } catch {
    return []
  }
}
