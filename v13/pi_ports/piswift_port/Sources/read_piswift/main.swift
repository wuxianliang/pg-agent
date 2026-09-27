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
    if CFNumberIsFloatType(number) {
        let parsed = number.doubleValue
        guard parsed.isFinite, let exact = Int(exactly: parsed) else {
            throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
        }
        return exact
    }
    var wide: Int64 = 0
    guard CFNumberGetValue(number, .sInt64Type, &wide) else {
        throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
    }
    guard number.compare(NSNumber(value: wide)) == .orderedSame else {
        throw ToolError(code: "invalid_params", message: "\(key) must be an integer")
    }
    return Int(wide)
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

func validateTextBytes(_ path: String) throws -> Data {
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
    return data
}

func isOffsetBeyond(_ message: String) -> Bool {
    let pattern = #"^Offset .+ is beyond end of file \([0-9]+ lines total\)$"#
    return message.range(of: pattern, options: .regularExpression) != nil
}

func restoreCallerPath(_ text: String, executed: String, caller: String) -> String {
    if executed == caller || executed.isEmpty {
        return text
    }
    let pattern = #"^\[Line [0-9]+ is [^,\]]+, exceeds [^,\]]+ limit\. Use bash: sed -n '[0-9]+p' (.*) \| head -c 51200\]$"#
    guard let regex = try? NSRegularExpression(pattern: pattern) else {
        return text
    }
    let full = NSRange(text.startIndex..., in: text)
    guard let match = regex.firstMatch(in: text, range: full),
          match.range.location == 0,
          match.range.length == full.length,
          let pathRange = Range(match.range(at: 1), in: text) else {
        return text
    }
    guard String(text[pathRange]) == executed else {
        return text
    }
    return text.replacingCharacters(in: pathRange, with: caller)
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
    let tail = String(String.UnicodeScalarView(scalars[at...]))
    let patterns = [
        #"^\n\n\[Showing lines [0-9]+-[0-9]+ of [0-9]+\. Use offset=[0-9]+ to continue\]$"#,
        #"^\n\n\[Showing lines [0-9]+-[0-9]+ of [0-9]+ \([^)\n]+ limit\)\. Use offset=[0-9]+ to continue\]$"#,
        #"^\n\n\[[0-9]+ more lines in file\. Use offset=[0-9]+ to continue\]$"#,
    ]
    guard patterns.contains(where: { tail.range(of: $0, options: .regularExpression) != nil }) else {
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

func evidenceLine(derivedCopy: Bool) -> String {
    let pathTag = derivedCopy ? "path=fenced-derived-copy" : "path=fenced-absolute"
    return "pi_ports evidence: module=PiSwift version=\(VERSION) function=createReadTool tool=read execute=AgentTool.execute \(pathTag)\n"
}

struct PreparedRead {
    let path: String
    let transformed: Bool
    let cleanup: () -> Void
}

func prepareFrameworkPath(snapshot: Data) throws -> PreparedRead {
    let crlf = Data([0x0D, 0x0A])
    guard snapshot.range(of: crlf) != nil else {
        return PreparedRead(path: "", transformed: false, cleanup: {})
    }
    var copy = Data()
    copy.reserveCapacity(snapshot.count)
    var index = snapshot.startIndex
    while index < snapshot.endIndex {
        if index + 1 < snapshot.endIndex, snapshot[index] == 0x0D, snapshot[index + 1] == 0x0A {
            copy.append(0x00)
            copy.append(0x0A)
            index += 2
        } else {
            copy.append(snapshot[index])
            index += 1
        }
    }
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("v13-read-piswift-\(UUID().uuidString).txt")
    do {
        try copy.write(to: url, options: .atomic)
    } catch {
        throw ToolError(code: "read_failed", message: error.localizedDescription)
    }
    return PreparedRead(path: url.path, transformed: true, cleanup: { try? FileManager.default.removeItem(at: url) })
}

func restoreCRLFStandIn(_ text: String) -> String {
    text.replacingOccurrences(of: "\u{0000}", with: "\r")
}

func readViaFramework(callerPath: String, absolutePath: String, snapshot: Data, offset: Int?, limit: Int?) async throws -> String {
    let prepared = try prepareFrameworkPath(snapshot: snapshot)
    defer { prepared.cleanup() }
    let toolPath = prepared.transformed ? prepared.path : absolutePath
    let cwd = (absolutePath as NSString).deletingLastPathComponent
    let tool = createReadTool(cwd: cwd.isEmpty ? "/" : cwd)
    do {
        try FileHandle.standardError.write(contentsOf: Data(evidenceLine(derivedCopy: prepared.transformed).utf8))
    } catch {
        throw ToolError(code: "read_failed", message: error.localizedDescription)
    }
    var params: [String: AnyCodable] = ["path": AnyCodable(toolPath)]
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
    var text = resultText(result)
    if prepared.transformed {
        text = restoreCRLFStandIn(text)
    }
    let restored = restoreCallerPath(text, executed: toolPath, caller: callerPath)
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
            let snapshot = try validateTextBytes(absolutePath)
            let result = try await readViaFramework(
                callerPath: path,
                absolutePath: absolutePath,
                snapshot: snapshot,
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
