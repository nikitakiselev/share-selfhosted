import { describe, expect, it } from 'vitest'
import {
  freeSpace,
  isEmail,
  isOverQuota,
  LOGIN_RE,
  normalizeEmail,
  normalizeLogin,
  parseQuotaGb,
  quotaRatio,
  quotaToGb,
  splitByQuota,
} from './quota'

const GB = 1 << 30

describe('limit', () => {
  it('over the limit only with a limit and used >= quota', () => {
    expect(isOverQuota({ quota: GB, used: GB })).toBe(true)
    expect(isOverQuota({ quota: GB, used: 3 * GB })).toBe(true)
    expect(isOverQuota({ quota: GB, used: GB - 1 })).toBe(false)
    expect(isOverQuota({ quota: null, used: 100 * GB })).toBe(false)
  })

  it('used share is clamped to 0…1, unlimited — null', () => {
    expect(quotaRatio({ quota: 4 * GB, used: GB })).toBe(0.25)
    expect(quotaRatio({ quota: GB, used: 12 * GB })).toBe(1)
    expect(quotaRatio({ quota: null, used: GB })).toBeNull()
  })

  it('free space excludes what is queued, never below zero', () => {
    expect(freeSpace({ quota: 10 * GB, used: 3 * GB }, 2 * GB)).toBe(5 * GB)
    expect(freeSpace({ quota: GB, used: 3 * GB })).toBe(0)
    expect(freeSpace({ quota: null, used: 3 * GB })).toBeNull()
  })
})

describe('splitting dropped files by space', () => {
  const f = (size: number) => ({ size })

  it('takes files in order while they fit, the rest is skipped', () => {
    const files = [f(3), f(4), f(2), f(1)]
    const { fit, skipped, skippedBytes } = splitByQuota(files, 8)
    expect(fit).toEqual([f(3), f(4)])
    expect(skipped).toEqual([f(2), f(1)])
    expect(skippedBytes).toBe(3)
  })

  it('everything fits without a limit', () => {
    expect(splitByQuota([f(10 * GB)], null).fit).toHaveLength(1)
  })

  it('exactly the remaining space fits', () => {
    expect(splitByQuota([f(5)], 5).fit).toHaveLength(1)
    expect(splitByQuota([f(6)], 5).fit).toHaveLength(0)
  })
})

describe('login', () => {
  it('is normalized and checked like on the server', () => {
    expect(normalizeLogin('  Masha.K ')).toBe('masha.k')
    expect(LOGIN_RE.test('masha.k')).toBe(true)
    expect(LOGIN_RE.test('ma')).toBe(false)
    expect(LOGIN_RE.test('маша')).toBe(false)
    expect(LOGIN_RE.test('a'.repeat(33))).toBe(false)
  })
})

describe('limit in GB', () => {
  it('whole GB → bytes, unlimited → null, anything else is invalid', () => {
    expect(parseQuotaGb('10', false)).toBe(10 * GB)
    expect(parseQuotaGb(' 1 ', false)).toBe(GB)
    expect(parseQuotaGb('', true)).toBeNull()
    expect(parseQuotaGb('abc', true)).toBeNull()
    expect(parseQuotaGb('', false)).toBeUndefined()
    expect(parseQuotaGb('0', false)).toBeUndefined()
    expect(parseQuotaGb('1.5', false)).toBeUndefined()
    expect(parseQuotaGb('-2', false)).toBeUndefined()
  })

  it('bytes → whole GB for the field, at least 1', () => {
    expect(quotaToGb(50 * GB)).toBe(50)
    expect(quotaToGb(GB / 2)).toBe(1)
  })
})

describe('email', () => {
  it('is normalized and roughly checked', () => {
    expect(normalizeEmail('  Masha@Example.COM ')).toBe('masha@example.com')
    expect(isEmail('masha@example.com')).toBe(true)
    expect(isEmail('masha.k+share@mail.example.ru')).toBe(true)
    expect(isEmail('masha')).toBe(false)
    expect(isEmail('masha@example')).toBe(false)
    expect(isEmail('ma sha@example.com')).toBe(false)
    expect(isEmail('a@b@example.com')).toBe(false)
    expect(isEmail(`${'a'.repeat(250)}@b.ru`)).toBe(false)
  })
})
