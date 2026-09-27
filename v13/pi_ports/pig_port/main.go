package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"runtime/debug"
	"strings"
	"syscall"
	"unicode/utf8"

	"github.com/MichaelKinsy/PiG/agent"
	"github.com/MichaelKinsy/PiG/coding"
	"github.com/MichaelKinsy/PiG/coding/pigversion"
)

const imageMessage = "image files are not supported"

var (
	imageExts    = map[string]struct{}{"jpg": {}, "jpeg": {}, "png": {}, "gif": {}, "webp": {}, "bmp": {}}
	offsetBeyond = regexp.MustCompile(`Offset .+ is beyond end of file`)
)

type toolError struct {
	code    string
	message string
}

func (e *toolError) Error() string { return e.message }

func emit(obj map[string]any, code int) {
	raw, err := json.Marshal(obj)
	if err != nil {
		os.Exit(1)
	}
	frame := append(raw, '\n')
	off := 0
	for off < len(frame) {
		n, err := os.Stdout.Write(frame[off:])
		if n > 0 {
			off += n
		}
		if err != nil || n == 0 {
			os.Exit(1)
		}
	}
	os.Exit(code)
}

func failTool(err *toolError) {
	emit(map[string]any{"ok": false, "error": err.code, "message": err.message}, 3)
}

func optionalInt(req map[string]any, key string) (*int, error) {
	value, ok := req[key]
	if !ok || value == nil {
		return nil, nil
	}
	number, ok := value.(float64)
	if !ok || math.IsNaN(number) || math.IsInf(number, 0) || number != math.Trunc(number) || number > float64(math.MaxInt) || number < float64(math.MinInt) {
		return nil, &toolError{code: "invalid_params", message: key + " must be an integer"}
	}
	parsed := int(number)
	return &parsed, nil
}

func pigEvidence() string {
	modulePath := "github.com/MichaelKinsy/PiG"
	listed := ""
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, dep := range info.Deps {
			if dep.Path == modulePath && dep.Version != "" {
				listed = dep.Version
				break
			}
		}
	}
	line := "pi_ports evidence: module=" + modulePath + " version=" + pigversion.Version
	if listed != "" {
		line += " go_list=" + listed
	}
	return line + " function=coding.NewSession tool=read execute=agent.AgentTool.Execute path=fenced-absolute\n"
}

func missingOrNotDir(err error) bool {
	if errors.Is(err, os.ErrNotExist) {
		return true
	}
	var pathErr *os.PathError
	if errors.As(err, &pathErr) {
		errno, ok := pathErr.Err.(syscall.Errno)
		return ok && (errno == syscall.ENOENT || errno == syscall.ENOTDIR)
	}
	return false
}

func realpathLoose(target string) (string, error) {
	abs, err := filepath.Abs(target)
	if err != nil {
		return "", &toolError{code: "read_failed", message: err.Error()}
	}
	var missing []string
	cur := abs
	for {
		resolved, err := filepath.EvalSymlinks(cur)
		if err == nil {
			if len(missing) == 0 {
				return resolved, nil
			}
			parts := []string{resolved}
			for i := len(missing) - 1; i >= 0; i-- {
				parts = append(parts, missing[i])
			}
			return filepath.Join(parts...), nil
		}
		if missingOrNotDir(err) {
			parent := filepath.Dir(cur)
			if parent == cur {
				return "", &toolError{code: "read_failed", message: err.Error()}
			}
			missing = append(missing, filepath.Base(cur))
			cur = parent
			continue
		}
		return "", &toolError{code: "read_failed", message: err.Error()}
	}
}

func resolveFenced(root, raw string) (string, string, error) {
	if strings.TrimSpace(root) == "" {
		return "", "", &toolError{code: "invalid_params", message: "root must be a string"}
	}
	if strings.Contains(raw, "\x00") {
		return "", "", &toolError{code: "path_outside_workspace", message: "path contains NUL"}
	}
	if strings.TrimSpace(raw) == "" {
		return "", "", &toolError{code: "invalid_params", message: "path must not be empty"}
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", "", &toolError{code: "read_failed", message: err.Error()}
	}
	rootReal, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return "", "", &toolError{code: "read_failed", message: err.Error()}
	}
	var cand string
	if strings.HasPrefix(raw, "/") {
		cand = filepath.Clean(raw)
	} else {
		cand = filepath.Clean(filepath.Join(rootReal, raw))
	}
	checked, err := realpathLoose(cand)
	if err != nil {
		return "", "", err
	}
	rel, err := filepath.Rel(rootReal, checked)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return "", "", &toolError{code: "path_outside_workspace", message: "path outside workspace"}
	}
	return rootReal, checked, nil
}

func isImagePath(absPath string) bool {
	ext := strings.TrimPrefix(strings.ToLower(filepath.Ext(absPath)), ".")
	_, ok := imageExts[ext]
	return ok
}

func validateTextBytes(absPath string) error {
	info, err := os.Stat(absPath)
	if err != nil {
		return &toolError{code: "read_failed", message: err.Error()}
	}
	if !info.Mode().IsRegular() {
		return &toolError{code: "read_failed", message: "not a regular file"}
	}
	buffer, err := os.ReadFile(absPath)
	if err != nil {
		return &toolError{code: "read_failed", message: err.Error()}
	}
	if !utf8.Valid(buffer) {
		return &toolError{code: "read_failed", message: "not utf-8"}
	}
	if strings.Contains(string(buffer), "\x00") {
		return &toolError{code: "read_failed", message: "contains NUL"}
	}
	return nil
}

func restoreCallerPath(text, executedPath, callerPath string) string {
	if executedPath == callerPath {
		return text
	}
	marker := "sed -n '"
	at := strings.LastIndex(text, marker)
	if at < 0 || !strings.Contains(text[at:], executedPath) {
		return text
	}
	return text[:at] + strings.ReplaceAll(text[at:], executedPath, callerPath)
}

func readTool(ctx context.Context) (agent.AgentTool, func(), error) {
	tmp, err := os.MkdirTemp("", "v13-read-pig-")
	if err != nil {
		return nil, nil, err
	}
	cleanup := func() { _ = os.RemoveAll(tmp) }
	trusted := false
	svcs, err := coding.NewServices(coding.ServicesOptions{
		CWD:            tmp,
		AgentDir:       tmp,
		ProjectTrusted: &trusted,
	})
	if err != nil {
		cleanup()
		return nil, nil, err
	}
	sess, err := coding.NewSession(svcs, coding.SessionOptions{
		NoSession:          true,
		ActiveBuiltinTools: map[string]struct{}{"read": {}},
	})
	if err != nil {
		cleanup()
		return nil, nil, err
	}
	for _, tool := range sess.Tools() {
		if tool.Name() == "read" {
			return tool, cleanup, nil
		}
	}
	cleanup()
	return nil, nil, errors.New("read tool missing")
}

func readViaFramework(callerPath, absolutePath string, offset *int, limit *int) (string, error) {
	ctx := context.Background()
	tool, cleanup, err := readTool(ctx)
	if cleanup != nil {
		defer cleanup()
	}
	if err != nil {
		return "", &toolError{code: "read_failed", message: err.Error()}
	}
	if _, err := os.Stderr.WriteString(pigEvidence()); err != nil {
		return "", &toolError{code: "read_failed", message: err.Error()}
	}
	params := map[string]any{"path": absolutePath}
	if offset != nil {
		params["offset"] = *offset
	}
	if limit != nil {
		params["limit"] = *limit
	}
	raw, err := json.Marshal(params)
	if err != nil {
		return "", &toolError{code: "read_failed", message: err.Error()}
	}
	result, err := tool.Execute(ctx, "pi-ports-read", raw, nil)
	if err != nil {
		message := err.Error()
		if offsetBeyond.MatchString(message) {
			return "", &toolError{code: "offset_out_of_range", message: message}
		}
		return "", &toolError{code: "read_failed", message: message}
	}
	if len(result.Images) > 0 {
		return "", &toolError{code: "image_unsupported", message: imageMessage}
	}
	if result.IsError {
		if offsetBeyond.MatchString(result.Content) {
			return "", &toolError{code: "offset_out_of_range", message: result.Content}
		}
		return "", &toolError{code: "read_failed", message: result.Content}
	}
	return restoreCallerPath(result.Content, absolutePath, callerPath), nil
}

func asToolError(err error) *toolError {
	var tool *toolError
	if errors.As(err, &tool) {
		return tool
	}
	return &toolError{code: "read_failed", message: err.Error()}
}

func main() {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(1)
	}
	if !utf8.Valid(raw) {
		os.Exit(1)
	}
	text := strings.TrimSpace(string(raw))
	if text == "" {
		emit(map[string]any{"ok": false, "error": "invalid_params", "message": "empty stdin"}, 3)
	}
	if text[0] != '{' {
		os.Exit(1)
	}
	var req map[string]any
	if err := json.Unmarshal([]byte(text), &req); err != nil || req == nil {
		os.Exit(1)
	}
	root, rootOK := req["root"].(string)
	path, pathOK := req["path"].(string)
	if !rootOK || !pathOK {
		emit(map[string]any{"ok": false, "error": "invalid_params", "message": "root and path must be strings"}, 3)
	}
	if strings.TrimSpace(path) == "" {
		emit(map[string]any{"ok": false, "error": "invalid_params", "message": "path must not be empty"}, 3)
	}
	offset, err := optionalInt(req, "offset")
	if err != nil {
		failTool(asToolError(err))
	}
	limit, err := optionalInt(req, "limit")
	if err != nil {
		failTool(asToolError(err))
	}
	if limit != nil && *limit < 0 {
		zero := 0
		limit = &zero
	}
	_, absolutePath, err := resolveFenced(root, path)
	if err != nil {
		failTool(asToolError(err))
	}
	if isImagePath(absolutePath) {
		failTool(&toolError{code: "image_unsupported", message: imageMessage})
	}
	if err := validateTextBytes(absolutePath); err != nil {
		failTool(asToolError(err))
	}
	result, err := readViaFramework(path, absolutePath, offset, limit)
	if err != nil {
		failTool(asToolError(err))
	}
	emit(map[string]any{"ok": true, "result": result}, 0)
}
