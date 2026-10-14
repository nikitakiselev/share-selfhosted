// Getting files together with a FileSystemFileHandle where the browser supports it (Chromium):
// the handle can be stored in IndexedDB to regain access to the file with one click after a
// reload. In other browsers handle = null.

export interface PickedFile {
  file: File
  handle: FileSystemFileHandle | null
}

export interface DroppedFiles {
  files: Promise<PickedFile[]>
  /** How many folders were skipped: only files are uploaded. */
  skippedDirectories: number
}

/**
 * Call SYNCHRONOUSLY in the drop handler: after the handler returns, DataTransfer is emptied
 * and getAsFileSystemHandle/getAsFile return nothing.
 */
export function collectDropped(dt: DataTransfer): DroppedFiles {
  const entries: { file: File; handle: Promise<FileSystemHandle | null> }[] = []
  let skippedDirectories = 0
  const items = dt.items ? Array.from(dt.items) : []

  if (items.length) {
    for (const item of items) {
      if (item.kind !== 'file') continue
      const entry = item.webkitGetAsEntry?.()
      if (entry?.isDirectory) {
        skippedDirectories++
        continue
      }
      const file = item.getAsFile()
      if (!file) continue
      const handle =
        typeof item.getAsFileSystemHandle === 'function'
          ? item.getAsFileSystemHandle().catch(() => null)
          : Promise.resolve(null)
      entries.push({ file, handle })
    }
  } else {
    for (const file of Array.from(dt.files)) entries.push({ file, handle: Promise.resolve(null) })
  }

  return {
    skippedDirectories,
    files: Promise.all(
      entries.map(async ({ file, handle }) => {
        const h = await handle
        return { file, handle: h && h.kind === 'file' ? (h as FileSystemFileHandle) : null }
      }),
    ),
  }
}

export function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/** File picker dialog. null — the user changed their mind. */
export async function pickFiles(): Promise<PickedFile[] | null> {
  if (typeof window.showOpenFilePicker === 'function') {
    try {
      const handles = await window.showOpenFilePicker({ multiple: true })
      return await Promise.all(handles.map(async (handle) => ({ file: await handle.getFile(), handle })))
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return null
      // SecurityError and the like — a regular <input type=file> below
    }
  }
  return pickViaInput()
}

function pickViaInput(): Promise<PickedFile[] | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.addEventListener('change', () => {
      const files = Array.from(input.files ?? [])
      resolve(files.length ? files.map((file) => ({ file, handle: null })) : null)
    })
    input.addEventListener('cancel', () => resolve(null))
    input.click()
  })
}
