import { afterEach, describe, expect, it } from 'vitest'
import { filesCount, formatDate, formatEta, formatRelative, formatSize, formatSpeed } from './format'
import { setLocale } from './i18n'

afterEach(() => setLocale('en'))

describe('formatSize', () => {
  it('picks the unit after rounding — en', () => {
    setLocale('en')
    expect(formatSize(1023 * 1024)).toBe('1,023 KB')
    expect(formatSize(1024 ** 3 - 12)).toBe('1 GB')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(500)).toBe('500 B')
  })

  it('picks the unit after rounding — ru', () => {
    setLocale('ru')
    expect(formatSize(1023 * 1024)).toBe(`${(1023).toLocaleString('ru')} КБ`)
    expect(formatSize(1024 ** 3 - 12)).toBe('1 ГБ')
    expect(formatSize(1536)).toBe('1,5 КБ')
    expect(formatSize(500)).toBe('500 Б')
  })
})

describe('speed, time left, file count', () => {
  it('en', () => {
    setLocale('en')
    expect(formatSpeed(1536)).toBe('1.5 KB/s')
    expect(formatEta(40)).toBe('40 s left')
    expect(formatEta(3 * 60)).toBe('3 min left')
    expect(formatEta(65 * 60)).toBe('1 h 5 min left')
    expect(filesCount(1)).toBe('1 file')
    expect(filesCount(5)).toBe('5 files')
  })

  it('ru', () => {
    setLocale('ru')
    expect(formatSpeed(1536)).toBe('1,5 КБ/с')
    expect(formatEta(40)).toBe('ещё 40 с')
    expect(formatEta(60 * 60)).toBe('ещё 1 ч')
    expect(filesCount(1)).toBe('1 файл')
    expect(filesCount(3)).toBe('3 файла')
    expect(filesCount(5)).toBe('5 файлов')
    expect(filesCount(21)).toBe('21 файл')
  })
})

describe('formatDate', () => {
  // a past year, so the year is always printed
  const ts = new Date(2020, 9, 21, 9, 5).getTime() / 1000

  it('en', () => {
    setLocale('en')
    expect(formatDate(ts)).toBe('October 21, 2020, 9:05 AM')
    expect(formatDate(ts, false)).toBe('October 21, 2020')
  })

  it('ru', () => {
    setLocale('ru')
    expect(formatDate(ts)).toBe('21 октября 2020 г., 09:05')
  })
})

describe('formatRelative', () => {
  const now = 1_792_000_000_000

  it('a couple of seconds of clock skew is "just now", not "in a minute"', () => {
    setLocale('ru')
    expect(formatRelative(now / 1000, now)).toBe('только что')
    expect(formatRelative(now / 1000 + 2, now)).toBe('только что')
    expect(formatRelative(now / 1000 - 30, now)).toBe('только что')
    expect(formatRelative(now / 1000 + 30, now)).toBe('через минуту')
    setLocale('en')
    expect(formatRelative(now / 1000 - 30, now)).toBe('just now')
    expect(formatRelative(now / 1000 + 30, now)).toBe('in a minute')
  })

  it('minutes and days in both languages', () => {
    setLocale('en')
    expect(formatRelative(now / 1000 - 5 * 60, now)).toBe('5 minutes ago')
    expect(formatRelative(now / 1000 + 3 * 86400, now)).toBe('in 3 days')
    setLocale('ru')
    expect(formatRelative(now / 1000 - 5 * 60, now)).toBe('5 минут назад')
    expect(formatRelative(now / 1000 + 3 * 86400, now)).toBe('через 3 дня')
  })
})
