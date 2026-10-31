import CryptoKit
import Foundation

struct User: Decodable {
    let login: String
    let email: String?
    let quota: Int64?
    let used: Int64
}

struct SessionInfo: Decodable {
    let authenticated: Bool
    let user: User?
}

struct TokenResponse: Decodable {
    let token: String
    let user: User
}

struct ShareSummary: Decodable {
    let slug: String
    let url: String
}

struct ApiError: LocalizedError {
    let status: Int
    let code: String
    let message: String
    var errorDescription: String? { message }
}

/// PKCE: the verifier stays in the app, only its hash goes to the browser.
struct Pkce {
    let verifier: String
    var challenge: String {
        Data(SHA256.hash(data: Data(verifier.utf8))).base64URL()
    }

    init() {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        verifier = Data(bytes).base64URL()
    }
}

extension Data {
    func base64URL() -> String {
        base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

/// The share API with a Bearer session. Errors are `ApiError` for an API answer, `URLError` otherwise.
final class ApiClient {
    let baseURL: URL
    var token: String?
    private let session: URLSession

    init(baseURL: URL, token: String?) {
        self.baseURL = baseURL
        self.token = token
        let cfg = URLSessionConfiguration.ephemeral
        cfg.httpCookieAcceptPolicy = .never
        cfg.timeoutIntervalForRequest = 60
        cfg.timeoutIntervalForResource = 3600
        session = URLSession(configuration: cfg)
    }

    func request(_ method: String, _ path: String, body: Data? = nil, headers: [String: String] = [:],
                 json: Bool = false) -> URLRequest {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.setValue("Share for macOS", forHTTPHeaderField: "User-Agent")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if json { req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }
        req.httpBody = body
        return req
    }

    @discardableResult
    func send(_ req: URLRequest, from data: Data? = nil) async throws -> (Data, HTTPURLResponse) {
        let (out, resp): (Data, URLResponse)
        if let data {
            (out, resp) = try await session.upload(for: req, from: data)
        } else {
            (out, resp) = try await session.data(for: req)
        }
        let http = resp as! HTTPURLResponse
        guard (200..<300).contains(http.statusCode) else {
            let obj = (try? JSONSerialization.jsonObject(with: out)) as? [String: Any]
            throw ApiError(status: http.statusCode, code: obj?["error"] as? String ?? "http_\(http.statusCode)",
                           message: obj?["message"] as? String ?? "HTTP \(http.statusCode)")
        }
        return (out, http)
    }

    func json<T: Decodable>(_ type: T.Type, _ req: URLRequest) async throws -> T {
        let (data, _) = try await send(req)
        return try JSONDecoder().decode(type, from: data)
    }

    // --- auth ---

    func connectURL(challenge: String) -> URL {
        var c = URLComponents(url: baseURL.appendingPathComponent("connect"), resolvingAgainstBaseURL: false)!
        c.queryItems = [URLQueryItem(name: "challenge", value: challenge)]
        return c.url!
    }

    func exchange(code: String, verifier: String) async throws -> TokenResponse {
        let body = try JSONSerialization.data(withJSONObject: ["code": code, "verifier": verifier])
        return try await json(TokenResponse.self, request("POST", "api/auth/app/token", body: body, json: true))
    }

    func session() async throws -> SessionInfo {
        try await json(SessionInfo.self, request("GET", "api/auth/session"))
    }

    func logout() async throws {
        try await send(request("POST", "api/auth/logout", body: Data("{}".utf8), json: true))
    }

    // --- links ---

    func createShare(expiresAt: Int? = nil) async throws -> ShareSummary {
        var obj: [String: Any] = [:]
        if let expiresAt { obj["expires_at"] = expiresAt }
        let body = try JSONSerialization.data(withJSONObject: obj)
        return try await json(ShareSummary.self, request("POST", "api/app/shares", body: body, json: true))
    }

    func deleteShare(_ slug: String) async throws {
        try await send(request("DELETE", "api/app/shares/\(slug)"))
    }
}
