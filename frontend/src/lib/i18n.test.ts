import { afterEach, describe, expect, it, vi } from 'vitest'
import en from '../locales/en'
import ru from '../locales/ru'
import { detectLocale, hasMessage, setLocale, t } from './i18n'

afterEach(() => setLocale('en'))

describe('detectLocale', () => {
  it('ru* is Russian, anything else is English', () => {
    expect(detectLocale('ru')).toBe('ru')
    expect(detectLocale('ru-RU')).toBe('ru')
    expect(detectLocale('RU-ua')).toBe('ru')
    expect(detectLocale('en-US')).toBe('en')
    expect(detectLocale('de-DE')).toBe('en')
    expect(detectLocale('')).toBe('en')
  })
})

describe('t', () => {
  it('substitutes params and keeps unknown placeholders', () => {
    setLocale('en')
    expect(t('users.since', { date: 'May 1' })).toBe('Since May 1')
    expect(t('common.xOfY', { x: 2, y: 5 })).toBe('2 of 5')
    expect(t('users.since')).toBe('Since {date}')
    setLocale('ru')
    expect(t('common.xOfY', { x: 2, y: 5 })).toBe('2 из 5')
  })

  it('English plurals: one / other', () => {
    setLocale('en')
    expect(t('count.shares', { count: 1 })).toBe('1 link')
    expect(t('count.shares', { count: 0 })).toBe('0 links')
    expect(t('count.shares', { count: 2 })).toBe('2 links')
  })

  it('Russian plurals: one / few / many', () => {
    setLocale('ru')
    expect(t('count.shares', { count: 1 })).toBe('1 ссылка')
    expect(t('count.shares', { count: 3 })).toBe('3 ссылки')
    expect(t('count.shares', { count: 5 })).toBe('5 ссылок')
    expect(t('count.shares', { count: 11 })).toBe('11 ссылок')
    expect(t('count.shares', { count: 21 })).toBe('21 ссылка')
    expect(t('count.shares', { count: 22 })).toBe('22 ссылки')
  })

  it('an unknown key is shown as is with a warning', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(t('no.such.key' as never)).toBe('no.such.key')
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })
})

describe('dictionaries', () => {
  it('ru has exactly the keys of en, plurals stay plurals', () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort())
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(typeof ru[key], key).toBe(typeof en[key])
    }
  })

  it('hasMessage knows only dictionary keys', () => {
    expect(hasMessage('errors.quota_exceeded')).toBe(true)
    expect(hasMessage('errors.something_new')).toBe(false)
  })
})
