// Interface language: picked once from the browser (ru* → Russian, anything else → English),
// no switcher. Messages are flat keys; a plural message is an object of Intl.PluralRules forms
// and takes its number from the `count` param.
import en, { type Dictionary, type Message, type MessageKey } from '../locales/en'
import ru from '../locales/ru'

export type { MessageKey }
export type Locale = 'en' | 'ru'
export type Params = Record<string, string | number>

const dictionaries: Record<Locale, Dictionary> = { en, ru }

export function detectLocale(language = typeof navigator === 'undefined' ? '' : navigator.language): Locale {
  return language.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}

let locale: Locale = detectLocale()
let pluralRules = new Intl.PluralRules(locale)

export function getLocale(): Locale {
  return locale
}

/** The language is fixed for the page's lifetime; switching is for tests. */
export function setLocale(next: Locale): void {
  locale = next
  pluralRules = new Intl.PluralRules(next)
}

export function hasMessage(key: string): key is MessageKey {
  return Object.hasOwn(dictionaries.en, key)
}

export function t(key: MessageKey, params: Params = {}): string {
  const message: Message | undefined = dictionaries[locale][key]
  if (message === undefined) {
    if (import.meta.env.DEV) console.warn(`[i18n] missing message "${key}" for "${locale}"`)
    return key
  }
  let text: string
  if (typeof message === 'string') text = message
  else {
    const count = Number(params.count ?? 0)
    text = message[pluralRules.select(count)] ?? message.other
  }
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match))
}
