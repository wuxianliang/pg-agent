import Darwin
import Foundation
import PiSwiftAI
import PiSwiftAgent
import PiSwiftCodingAgent

let imageMessage = "image files are not supported"
let imageExts: Set<String> = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]

struct ToolError: Error {
    let code: String
    let message: String
}

func emit(_ obj: [String: Any], code: Int32) -> Never {
    guard JSONSerialization.isValidJSONObject(obj),
          let raw = try? JSONSerialization.data(withJSONObject: obj, options: []) else {
        Darwin.exit(1)
    }
    var frame = raw
    frame.append(0x0A)
    do {
        try FileHandle.standardOutput.write(contentsOf: frame)
    } catch {
        Darwin.exit(1)
    }
    Darwin.exit(code)
}

func failTool(_ err: ToolError) -> Never {
    emit(["ok": false, "error": err.code, "message": err.message], code: 3)
}

func errnoMessage(_ err: Int32) -> String {
    if let cstr = strerror(err) {
        return String(cString: cstr)
    }
    return "errno \(err)"
}

func optionalInt(_ req: [String: Any], key: String) throws -> Int? {
    guard req.keys.contains(key), let value = req[key], !(value is NSNull) else {
        return nil
    }
    guard let number = value as? NSNumber else {
        throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
    }
    if CFGetTypeID(number) == CFBooleanGetTypeID() {
        throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
    }
    let parsed = number.doubleValue
    guard parsed.isFinite, let exact = Int(exactly: parsed) else {
        throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
    }
    return exact
}

func lexicalClean(_ path: String) -> String {
    let absolute = path.hasPrefix("/")
    var parts: [String] = []
    for part in path.split(separator: "/", omittingEmptySubsequences: true) {
        if part == "." {
            continue
        }
        if part == ".." {
            if !parts.isEmpty {
                parts.removeLast()
            }
            continue
        }
        parts.append(String(part))
    }
    if absolute {
        return "/" + parts.joined(separator: "/")
    }
    if parts.isEmpty {
        return "."
    }
    return parts.joined(separator: "/")
}

func absoluteLexical(_ path: String) -> String {
    if path.hasPrefix("/") {
        return lexicalClean(path)
    }
    let cwd = FileManager.default.currentDirectoryPath
    let joined = cwd == "/" ? "/" + path : cwd + "/" + path
    return lexicalClean(joined)
}

func realpathStrict(_ path: String) -> (String?, Int32) {
    path.withCString { cstr in
        if let buf = realpath(cstr, nil) {
            defer { free(buf) }
            return (String(cString: buf), 0)
        }
        return (nil, errno)
    }
}

func realpathLoose(_ target: String) throws -> String {
    var missing: [String] = []
    var cur = absoluteLexical(target)
    while true {
        let (resolved, err) = realpathStrict(cur)
        if let resolved {
            if missing.isEmpty {
                return resolved
            }
            let tail = missing.reversed().joined(separator: "/")
            let joined = resolved == "/" ? "/" + tail : resolved + "/" + tail
            return lexicalClean(joined)
        }
        if err == ENOENT || err == ENOTDIR {
            let ns = cur as NSString
            let parent = ns.deletingLastPathComponent
            if parent == cur {
                throw ToolError(code: "read_failed", message: errnoMessage(err))
            }
            missing.append(ns.lastPathComponent)
            cur = parent
            continue
        }
        throw ToolError(code: "read_failed", message: errnoMessage(err))
    }
}

func relativePath(from base: String, to target: String) -> String {
    let baseParts = base.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
    let targetParts = target.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
    var index = 0
    while index < baseParts.count && index < targetParts.count && baseParts[index] == targetParts[index] {
        index += 1
    }
    var rel = Array(repeating: "..", count: baseParts.count - index)
    rel.append(contentsOf: targetParts[index...])
    if rel.isEmpty {
        return "."
    }
    return rel.joined(separator: "/")
}

func outsideFence(_ rel: String) -> Bool {
    rel == ".." || rel.hasPrefix("../")
}

func resolveFenced(root: String, raw: String) throws -> String {
    if root.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        throw ToolError(code: "invalid_params", message: "root must be a string")
    }
    if raw.contains("\u{0000}") {
        throw ToolError(code: "path_outside_workspace", message: "path contains NUL")
    }
    if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        throw ToolError(code: "invalid_params", message: "path must not be empty")
    }
    let rootAbs = absoluteLexical(root)
    let (rootResolved, rootErr) = realpathStrict(rootAbs)
    guard let rootReal = rootResolved else {
        throw ToolError(code: "read_failed", message: errnoMessage(rootErr))
    }
    let cand: String
    if raw.hasPrefix("/") {
        cand = lexicalClean(raw)
    } else {
        cand = lexicalClean(rootReal == "/" ? "/" + raw : rootReal + "/" + raw)
    }
    let checked = try realpathLoose(cand)
    if outsideFence(relativePath(from: rootReal, to: checked)) {
        throw ToolError(code: "path_outside_workspace", message: "path outside workspace")
    }
    return checked
}

func isImagePath(_ path: String) -> Bool {
    imageExts.contains((path as NSString).pathExtension.lowercased())
}

func isRegularFile(_ path: String) throws -> Bool {
    try path.withCString { cstr in
        var info = Darwin.stat()
        if lstat(cstr, &info) != 0 {
            throw ToolError(code: "read_failed", message: errnoMessage(errno))
        }
        return (info.st_mode & S_IFMT) == S_IFREG
    }
}

func validateTextBytes(_ path: String) throws {
    if try !isRegularFile(path) {
        throw ToolError(code: "read_failed", message: "not a regular file")
    }
    let data: Data
    do {
        data = try Data(contentsOf: URL(fileURLWithPath: path))
    } catch {
        throw ToolError(code: "read_failed", message: error.localizedDescription)
    }
    guard String(data: data, encoding: .utf8) != nil else {
        throw ToolError(code: "read_failed", message: "not utf-8")
    }
    if data.contains(0) {
        throw ToolError(code: "read_failed", message: "contains NUL")
    }
}

func isOffsetBeyond(_ message: String) -> Bool {
    message.range(of: #"Offset .+ is beyond end of file"#, options: .regularExpression) != nil
}

func restoreCallerPath(_ text: String, executed: String, caller: String) -> String {
    if executed == caller {
        return text
    }
    let marker = "sed -n '"
    guard let at = text.range(of: marker, options: .backwards), text[at.lowerBound...].contains(executed) else {
        return text
    }
    let head = text[..<at.lowerBound]
    let tail = text[at.lowerBound...].replacingOccurrences(of: executed, with: caller)
    return head + tail
}

func alignContractTrailer(_ text: String) -> String {
    let scalars = Array(text.unicodeScalars)
    let marker: [Unicode.Scalar] = ["\n", "\n", "["]
    guard scalars.count >= marker.count else {
        return text
    }
    var found: Int?
    for index in stride(from: scalars.count - marker.count, through: 0, by: -1) {
        if Array(scalars[index..<(index + marker.count)]) == marker {
            found = index
            break
        }
    }
    guard let at = found else {
        return text
    }
    let tail = scalars[at...]
    guard !tail.dropFirst(marker.count).contains("\n") else {
        return text
    }
    let suffix: [Unicode.Scalar] = Array("to continue]".unicodeScalars)
    guard tail.count >= suffix.count, Array(tail.suffix(suffix.count)) == suffix else {
        return text
    }
    var fixed = scalars
    fixed.removeLast()
    fixed.append(contentsOf: Array(".]".unicodeScalars))
    return String(String.UnicodeScalarView(fixed))
}

func hasImageAttachment(_ result: AgentToolResult) -> Bool {
    result.content.contains { block in
        if case .image = block {
            return true
        }
        return false
    }
}

func resultText(_ result: AgentToolResult) -> String {
    result.content.compactMap { block in
        if case .text(let text) = block {
            return text.text
        }
        return nil
    }.joined()
}

func evidenceLine() -> String {
    "pi_ports evidence: module=PiSwift version=\(VERSION) function=createReadTool tool=read execute=AgentTool.execute path=fenced-absolute\n"
}

struct PreparedRead {
    let path: String
    let cleanup: () -> Void
}

func prepareFrameworkPath(_ absolutePath: String) throws -> PreparedRead {
    let text = try String(contentsOfFile: absolutePath, encoding: .utf8)
    let scalars = Array(text.unicodeScalars)
    var hasCRLF = false
    if scalars.count >= 2 {
        for index in 0..<(scalars.count - 1) where scalars[index] == "\r" && scalars[index + 1] == "\n" {
            hasCRLF = true
            break
        }
    }
    if !hasCRLF {
        return PreparedRead(path: absolutePath, cleanup: {})
    }
    let broken = text.replacingOccurrences(of: "\r\n", with: "\r\u{E000}\n")
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("v13-read-piswift-\(UUID().uuidString).txt")
    try Data(broken.utf8).write(to: url, options: .atomic)
    return PreparedRead(path: url.path, cleanup: { try? FileManager.default.removeItem(at: url) })
}

func stripGraphemeBreak(_ text: String) -> String {
    text.replacingOccurrences(of: "\r\u{E000}", with: "\r")
}

func readViaFramework(callerPath: String, absolutePath: String, offset: Int?, limit: Int?) async throws -> String {
    let prepared = try prepareFrameworkPath(absolutePath)
    defer { prepared.cleanup() }
    let cwd = (absolutePath as NSString).deletingLastPathComponent
    let tool = createReadTool(cwd: cwd.isEmpty ? "/" : cwd)
    try FileHandle.standardError.write(contentsOf: Data(evidenceLine().utf8))
    var params: [String: AnyCodable] = ["path": AnyCodable(absolutePath)]
    if prepared.path != absolutePath {
        params["path"] = AnyCodable(prepared.path)
    }
    if let offset {
        params["offset"] = AnyCodable(offset)
    }
    if let limit {
        params["limit"] = AnyCodable(limit)
    }
    let result: AgentToolResult
    do {
        result = try await tool.execute("pi-ports-read", params, nil, nil)
    } catch {
        let message = error.localizedDescription
        if isOffsetBeyond(message) {
            throw ToolError(code: "offset_out_of_range", message: message)
        }
        throw ToolError(code: "read_failed", message: message)
    }
    if hasImageAttachment(result) {
        throw ToolError(code: "image_unsupported", message: imageMessage)
    }
    let text = resultText(result)
    if isOffsetBeyond(text) {
        throw ToolError(code: "offset_out_of_range", message: text)
    }
    let restored = restoreCallerPath(stripGraphemeBreak(text), executed: prepared.path, caller: callerPath)
    return alignContractTrailer(restored)
}

@main
struct ReadPiSwift {
    static func main() async {
        let raw = FileHandle.standardInput.readDataToEndOfFile()
        guard let decoded = String(data: raw, encoding: .utf8) else {
            Darwin.exit(1)
        }
        let text = decoded.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            emit(["ok": false, "error": "invalid_params", "message": "empty stdin"], code: 3)
        }
        guard text.hasPrefix("{"),
              let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let req = obj as? [String: Any] else {
            Darwin.exit(1)
        }
        guard let root = req["root"] as? String, let path = req["path"] as? String else {
            emit(["ok": false, "error": "invalid_params", "message": "root and path must be strings"], code: 3)
        }
        if path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            emit(["ok": false, "error": "invalid_params", "message": "path must not be empty"], code: 3)
        }
        let offset: Int?
        var limit: Int?
        do {
            offset = try optionalInt(req, key: "offset")
            limit = try optionalInt(req, key: "limit")
        } catch let err as ToolError {
            failTool(err)
        } catch {
            Darwin.exit(1)
        }
        if let value = limit, value < 0 {
            limit = 0
        }
        do {
            let absolutePath = try resolveFenced(root: root, raw: path)
            if isImagePath(absolutePath) {
                failTool(ToolError(code: "image_unsupported", message: imageMessage))
            }
            try validateTextBytes(absolutePath)
            let result = try await readViaFramework(
                callerPath: path,
                absolutePath: absolutePath,
                offset: offset,
                limit: limit
            )
            emit(["ok": true, "result": result], code: 0)
        } catch let err as ToolError {
            failTool(err)
        } catch {
            let message = error.localizedDescription
            if isOffsetBeyond(message) {
                failTool(ToolError(code: "offset_out_of_range", message: message))
            }
            let line = Data((message + "\n").utf8)
            try? FileHandle.standardError.write(contentsOf: line)
            Darwin.exit(1)
        }
    }
}
