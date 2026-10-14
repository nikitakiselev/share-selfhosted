import { afterEach, describe, expect, it } from 'vitest'
import { apiErrorText } from './http'
import { setLocale } from './i18n'

afterEach(() => setLocale('en'))

describe('apiErrorText', () => {
  it('translates a known code with numbers from the response', () => {
    const body = { error: 'quota_exceeded', message: 'Not enough space', needed: 3 * 1024 ** 3, free: 512 * 1024 ** 2 }
    setLocale('en')
    expect(apiErrorText(413, body)).toBe('Not enough space: 3 GB needed, 512 MB free')
    setLocale('ru')
    expect(apiErrorText(413, body)).toBe('Не хватает места: нужно 3 ГБ, свободно 512 МБ')
    expect(apiErrorText(429, { error: 'too_many_attempts', retry_after: 900 })).toBe(
      'Слишком много попыток. Попробуйте через 15 минут.',
    )
    expect(apiErrorText(400, { error: 'weak_password', min_length: 10, max_length: 200 })).toBe(
      'Пароль — от 10 до 200 символов',
    )
  })

  it("an unknown code shows the server's message, no body — a text by status", () => {
    setLocale('ru')
    expect(apiErrorText(400, { error: 'something_new', message: 'Something new' })).toBe('Something new')
    expect(apiErrorText(404, {})).toBe('Не найдено')
    expect(apiErrorText(502, {})).toBe('Ошибка сервера (502)')
  })
})
