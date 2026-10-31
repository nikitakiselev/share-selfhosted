import XCTest
import CryptoKit
@testable import ShareApp

final class PkceTests: XCTestCase {
    func testChallengeMatchesServer() {
        // sha256("test") in base64url without padding — what accounts.pkce_challenge computes
        struct Fixed { let verifier = "test" }
        let challenge = Data(SHA256.hash(data: Data("test".utf8))).base64URL()
        XCTAssertEqual(challenge, "n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg")
        XCTAssertEqual(Pkce().challenge.count, 43)
        XCTAssertNotEqual(Pkce().verifier, Pkce().verifier)
    }
}

/// End-to-end against a running backend: SHARE_TEST_SERVER=http://127.0.0.1:8000 SHARE_TEST_TOKEN=<session>.
final class UploadFlowTests: XCTestCase {
    func testCreateShareAndUpload() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let server = env["SHARE_TEST_SERVER"], let token = env["SHARE_TEST_TOKEN"] else {
            throw XCTSkip("set SHARE_TEST_SERVER and SHARE_TEST_TOKEN")
        }
        let api = ApiClient(baseURL: URL(string: server)!, token: token)
        let info = try await api.session()
        XCTAssertTrue(info.authenticated)

        // 10 MiB + 1 byte: three chunks, the last one partial
        let size = 10 * (1 << 20) + 1
        var bytes = [UInt8](repeating: 0, count: size)
        for i in stride(from: 0, to: size, by: 4099) { bytes[i] = UInt8(i % 251) }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("тест видео.bin")
        try Data(bytes).write(to: file)

        let share = try await api.createShare()
        XCTAssertTrue(share.url.hasSuffix("/s/\(share.slug)"))
        var reported: [Int64] = []
        try await TusUploader(api: api, slug: share.slug).upload(file: file) { reported.append($0) }
        XCTAssertEqual(reported.last, Int64(size))
        XCTAssertEqual(reported.count, 3)

        let (data, _) = try await api.send(api.request("GET", "api/app/shares/\(share.slug)"))
        let obj = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let files = obj["files"] as! [[String: Any]]
        XCTAssertEqual(files.count, 1)
        XCTAssertEqual(files[0]["name"] as? String, "тест видео.bin")
        XCTAssertEqual(files[0]["size"] as? Int, size)
        XCTAssertEqual(files[0]["status"] as? String, "ready")
        try await api.deleteShare(share.slug)
    }
}
