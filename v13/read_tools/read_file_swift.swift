// Ported & modified from RepoPrompt CE (Apache-2.0).
// Sources: MCPDomainCanonicalWorkspaceService.swift:171-193
//          DirectHeadlessDomainContext.swift:302-333
// Single-root headless subset. Not the app-window read_file.
// See THIRD_PARTY_NOTICES.md.

import Foundation
import Darwin

let safeIntMax: Int64 = 9007199254740991

struct ReadFailure: Error {
    let code: String
    let message: String
}

func emitAndExit(_ object: [String: Any], _ code: Int32) -> Never {
    guard let encoded = try? JSONSerialization.data(withJSONObject: object) else {
        exit(1)
    }
    var frame = encoded
    frame.append(0x0A)
    try? FileHandle.standardOutput.write(contentsOf: frame)
    exit(code)
}

func optionalInt(_ value: Any?) -> Int? {
    guard let value, !(value is NSNull), !(value is String) else {
        return nil
    }
    if let number = value as? NSNumber {
        if CFGetTypeID(number) == CFBooleanGetTypeID() || CFNumberIsFloatType(number) {
            return nil
        }
        let int64 = number.int64Value
        if int64 < -safeIntMax || int64 > safeIntMax {
            return nil
        }
        return Int(int64)
    }
    if let intValue = value as? Int {
        if intValue < -Int(safeIntMax) || intValue > Int(safeIntMax) {
            return nil
        }
        return intValue
    }
    return nil
}

func joinPath(_ root: String, _ rel: String) -> String {
    if root == "/" {
        return "/" + rel
    }
    if root.hasSuffix("/") {
        return root + rel
    }
    return root + "/" + rel
}

func canonicalPath(_ path: String) throws -> String {
    errno = 0
    let resolved = path.withCString { Darwin.realpath($0, nil) }
    if let resolved {
        defer { free(resolved) }
        return String(cString: resolved)
    }
    if errno == ENOENT {
        let ns = path as NSString
        let parent = ns.deletingLastPathComponent
        if parent.isEmpty || parent == path {
            throw ReadFailure(code: "read_failed", message: "read failed")
        }
        let parentReal = try canonicalPath(parent)
        let base = ns.lastPathComponent
        if parentReal == "/" {
            return "/" + base
        }
        return parentReal + "/" + base
    }
    throw ReadFailure(code: "read_failed", message: "read failed")
}

func resolvePath(root: String, raw: String) throws -> String {
    if root.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        throw ReadFailure(code: "invalid_params", message: "root must be a string")
    }
    if raw.contains("\0") {
        throw ReadFailure(code: "path_outside_workspace", message: "path contains NUL")
    }
    if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        throw ReadFailure(code: "invalid_params", message: "path must not be empty")
    }
    let rootReal = try canonicalPath(root)
    let cand = raw.hasPrefix("/") ? raw : joinPath(rootReal, raw)
    let normalized = URL(fileURLWithPath: cand).standardizedFileURL.path
    let checked = try canonicalPath(normalized)
    if checked == rootReal || checked.hasPrefix(rootReal + "/") {
        return checked
    }
    throw ReadFailure(code: "path_outside_workspace", message: "path outside workspace")
}

func readUTF8(_ path: String) throws -> String {
    var isDir: ObjCBool = false
    if FileManager.default.fileExists(atPath: path, isDirectory: &isDir), isDir.boolValue {
        throw ReadFailure(code: "read_failed", message: "is a directory")
    }
    let data: Data
    do {
        data = try Data(contentsOf: URL(fileURLWithPath: path))
    } catch {
        throw ReadFailure(code: "read_failed", message: "read failed")
    }
    guard let text = String(data: data, encoding: .utf8) else {
        throw ReadFailure(code: "read_failed", message: "not utf-8")
    }
    if text.contains("\0") {
        throw ReadFailure(code: "read_failed", message: "contains NUL")
    }
    return text
}

func selectLines(_ lines: [String], start: Int?, limit: Int?) -> [String] {
    if let start, start < 0 {
        let count = min(lines.count, abs(start))
        if count == 0 {
            return []
        }
        return Array(lines.suffix(count))
    }
    if let start {
        let index = max(0, start - 1)
        if index >= lines.count {
            return []
        }
        let take = limit.map { max(0, $0) } ?? lines.count
        let end = index + take > lines.count ? lines.count : index + take
        return Array(lines[index..<end])
    }
    return lines
}

func run() throws {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let text = String(data: input, encoding: .utf8) else {
        exit(1)
    }
    if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        emitAndExit(
            ["ok": false, "error": "invalid_params", "message": "empty stdin"],
            3
        )
    }
    guard let obj = try? JSONSerialization.jsonObject(with: input) as? [String: Any] else {
        exit(1)
    }
    guard let root = obj["root"] as? String, let path = obj["path"] as? String else {
        throw ReadFailure(code: "invalid_params", message: "root and path must be strings")
    }
    let checked = try resolvePath(root: root, raw: path)
    let full = try readUTF8(checked)
    let lines = full.components(separatedBy: .newlines)
    let selected = selectLines(lines, start: optionalInt(obj["start_line"]), limit: optionalInt(obj["limit"]))
    emitAndExit(["ok": true, "result": selected.joined(separator: "\n")], 0)
}

do {
    try run()
} catch let failure as ReadFailure {
    emitAndExit(["ok": false, "error": failure.code, "message": failure.message], 3)
} catch {
    exit(1)
}
