import Foundation

/// Interface language follows the system, like the website: ru* → Russian, otherwise English.
enum L10n {
    static let isRussian: Bool = (Locale.preferredLanguages.first ?? "").lowercased().hasPrefix("ru")

    static func t(_ ru: String, _ en: String) -> String { isRussian ? ru : en }

    static var welcome: String { t("Добро пожаловать в Share.", "Welcome to Share.") }
    static var pleaseSignIn: String {
        t("Загружайте файлы и получайте ссылки. Вход откроется в браузере.",
          "Upload files and get links. The sign-in opens in your browser.")
    }
    static var signIn: String { t("Войти", "Sign in") }
    static var waitingForBrowser: String { t("Подтвердите вход в браузере…", "Confirm the sign-in in the browser…") }
    static var cancel: String { t("Отмена", "Cancel") }
    static var signOut: String { t("Выход", "Sign out") }
    static var quit: String { t("Закрыть приложение", "Quit") }
    static var dropHere: String { t("Перетащите файлы сюда", "Drop files here") }
    static var orClick: String { t("или нажмите, чтобы выбрать", "or click to choose") }
    static var uploading: String { t("Загрузка", "Uploading") }
    static var creatingLink: String { t("Создаём ссылку…", "Creating the link…") }
    static var copy: String { t("Скопировать ссылку", "Copy link") }
    static var copied: String { t("Скопировано", "Copied") }
    static var linkReady: String { t("Ссылка готова", "Link is ready") }
    static var newUpload: String { t("Ещё файлы", "More files") }
    static var retry: String { t("Повторить", "Retry") }
    static var offline: String { t("Сервер не отвечает", "The server is not responding") }
    static var unlimited: String { t("без лимита", "unlimited") }
    static var filesSuffix: String { t("файлов", "files") }

    static func free(_ free: String, of quota: String) -> String {
        t("Свободно \(free) из \(quota)", "\(free) free of \(quota)")
    }
    static func used(_ used: String) -> String { t("Занято \(used), без лимита", "\(used) used, unlimited") }
    static func fileOf(_ i: Int, _ n: Int) -> String { t("Файл \(i) из \(n)", "File \(i) of \(n)") }
    static func andMore(_ n: Int) -> String { t("и ещё \(n)", "and \(n) more") }
    static var expiresInHour: String { t("Ссылка живёт 1 час", "The link expires in 1 hour") }

    static func size(_ bytes: Int64) -> String {
        let f = ByteCountFormatter()
        f.countStyle = .file
        return f.string(fromByteCount: bytes)
    }
}
