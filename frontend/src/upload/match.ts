// Matching re-picked files to unfinished uploads after a page reload. Browsers without
// FileSystemFileHandle (Safari, Firefox) don't allow regaining access to a file — the user
// drags it again, and we recognize it by name, size and modification time.

export interface FileIdentity {
  name: string
  size: number
  lastModified: number
}

export interface PendingIdentity extends FileIdentity {
  key: string
}

export interface MatchResult {
  /** Pairs "unfinished upload → file index in the input list". */
  matched: { key: string; index: number }[]
  /** Indexes of files without a pair — these are new uploads. */
  unmatched: number[]
}

// Names from different sources (Finder, the file picker) may come in different Unicode
// normalization forms: "й" as one character or as "и" + breve.
const norm = (name: string) => name.normalize('NFC')

export function sameFile(a: FileIdentity, b: FileIdentity): boolean {
  return a.size === b.size && a.lastModified === b.lastModified && norm(a.name) === norm(b.name)
}

/** Each upload and each file takes part in at most one pair. */
export function matchFiles(pending: readonly PendingIdentity[], files: readonly FileIdentity[]): MatchResult {
  const used = new Set<string>()
  const matched: MatchResult['matched'] = []
  const unmatched: number[] = []
  files.forEach((file, index) => {
    const hit = pending.find((p) => !used.has(p.key) && sameFile(p, file))
    if (hit) {
      used.add(hit.key)
      matched.push({ key: hit.key, index })
    } else {
      unmatched.push(index)
    }
  })
  return { matched, unmatched }
}
