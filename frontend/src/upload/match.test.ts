import { describe, expect, it } from 'vitest'
import { matchFiles, sameFile } from './match'

const f = (name: string, size = 100, lastModified = 1_700_000_000_000) => ({ name, size, lastModified })
const p = (key: string, name: string, size = 100, lastModified = 1_700_000_000_000) => ({
  key,
  name,
  size,
  lastModified,
})

describe('sameFile', () => {
  it('matches by name, size and modification time', () => {
    expect(sameFile(f('a.mp4'), f('a.mp4'))).toBe(true)
  })

  it('a different size is a different file', () => {
    expect(sameFile(f('a.mp4', 100), f('a.mp4', 101))).toBe(false)
  })

  it('a different modification time is a different file (it was overwritten)', () => {
    expect(sameFile(f('a.mp4', 100, 1), f('a.mp4', 100, 2))).toBe(false)
  })

  it('names are compared regardless of Unicode normalization', () => {
    const nfc = 'Видео йога.mov'.normalize('NFC')
    const nfd = 'Видео йога.mov'.normalize('NFD')
    expect(nfc).not.toBe(nfd)
    expect(sameFile(f(nfc), f(nfd))).toBe(true)
  })
})

describe('matchFiles', () => {
  it('finds pairs and separates new files', () => {
    const result = matchFiles([p('k1', 'a.mp4'), p('k2', 'b.mp4', 200)], [f('new.txt'), f('b.mp4', 200), f('a.mp4')])
    expect(result.matched).toEqual([
      { key: 'k2', index: 1 },
      { key: 'k1', index: 2 },
    ])
    expect(result.unmatched).toEqual([0])
  })

  it('identical files take different uploads one by one', () => {
    const result = matchFiles([p('k1', 'a.mp4'), p('k2', 'a.mp4')], [f('a.mp4'), f('a.mp4'), f('a.mp4')])
    expect(result.matched).toEqual([
      { key: 'k1', index: 0 },
      { key: 'k2', index: 1 },
    ])
    expect(result.unmatched).toEqual([2])
  })

  it('without unfinished uploads everything is new', () => {
    expect(matchFiles([], [f('a'), f('b')])).toEqual({ matched: [], unmatched: [0, 1] })
  })

  it('empty input', () => {
    expect(matchFiles([p('k1', 'a')], [])).toEqual({ matched: [], unmatched: [] })
  })
})
