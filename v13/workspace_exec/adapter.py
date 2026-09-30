"""In-process workspace tools. No SQL. No shell."""
from __future__ import annotations

import errno
import hashlib
import os
import stat


class Escape(Exception):
    pass


class AmbiguousOutcome(Exception):
    pass


class WorkerFail(Exception):
    def __init__(self, token: str):
        self.token = token


def _utf8_prefix(data: bytes, cap: int) -> str:
    cut = data[:cap]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


class Adapter:
    def __init__(self, root: str, bash_verbs, result_cap: int, find_depth_cap: int):
        self.root = root
        self.bash_verbs = list(bash_verbs)
        self.result_cap = int(result_cap)
        self.find_depth_cap = int(find_depth_cap)
        self._dev = None
        self._ino = None
        st = os.lstat(root)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise Escape()
        self._dev = st.st_dev
        self._ino = st.st_ino

    def run(self, tool, paths, payload, attempt_key, hooks=None):
        hooks = hooks or {}
        self._check_root()
        if hooks.get("before_recheck"):
            hooks["before_recheck"]()
        self._check_root()
        if hooks.get("force_io_error"):
            raise WorkerFail("io_error")
        if tool == "write":
            return self._write(payload, attempt_key, hooks)
        if tool == "edit":
            return self._edit(payload, attempt_key, hooks)
        if tool == "grep":
            return self._grep(payload)
        if tool == "find":
            return self._find(payload)
        if tool == "ls":
            return self._ls(payload)
        if tool == "bash":
            return self._bash(payload, attempt_key, hooks)
        raise WorkerFail("io_error")

    def _check_root(self):
        st = os.lstat(self.root)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise Escape()
        if (st.st_dev, st.st_ino) != (self._dev, self._ino):
            raise Escape()

    def _parent(self, rel):
        parts = rel.split("/")
        if not parts or any(p in ("", ".", "..") for p in parts):
            raise Escape()
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise Escape() from exc
            raise WorkerFail("io_error") from exc
        try:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != (self._dev, self._ino) or not stat.S_ISDIR(st.st_mode):
                raise Escape()
            for part in parts[:-1]:
                try:
                    nxt = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=fd,
                    )
                except OSError as exc:
                    self._map_open(exc, want="dir")
                os.close(fd)
                fd = nxt
            return fd, parts[-1]
        except Exception:
            os.close(fd)
            raise

    def _map_open(self, exc, want="file"):
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise Escape() from exc
        if exc.errno == errno.ENOENT:
            raise WorkerFail("missing") from exc
        if exc.errno == errno.EACCES:
            raise WorkerFail("io_error") from exc
        if exc.errno == errno.ENOTDIR or (want == "dir" and exc.errno == errno.EEXIST):
            raise WorkerFail("not_a_dir") from exc
        raise WorkerFail("io_error") from exc

    def _lstat(self, parent, name):
        try:
            return os.lstat(name, dir_fd=parent)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise Escape() from exc
            raise WorkerFail("io_error") from exc

    def _classify_file(self, st):
        if st is None:
            raise WorkerFail("missing")
        if stat.S_ISLNK(st.st_mode):
            raise Escape()
        if not stat.S_ISREG(st.st_mode):
            raise WorkerFail("not_a_file")

    def _hash(self, parent, name):
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            h = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
            return h.hexdigest()
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise Escape() from exc
            raise WorkerFail("io_error") from exc
        finally:
            if fd is not None:
                os.close(fd)

    def _read(self, parent, name):
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            parts = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                parts.append(chunk)
            return b"".join(parts)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise Escape() from exc
            raise WorkerFail("io_error") from exc
        finally:
            if fd is not None:
                os.close(fd)

    def _temp_name(self, attempt_key):
        if not isinstance(attempt_key, str) or attempt_key in ("", ".", ".."):
            raise Escape()
        if "/" in attempt_key or "\\" in attempt_key or "\0" in attempt_key:
            raise Escape()
        name = ".v13tmp-" + attempt_key
        if name in (".", "..", "") or "/" in name or "\\" in name or "\0" in name:
            raise Escape()
        if os.path.basename(name) != name or os.path.dirname(name) != "":
            raise Escape()
        return name

    def _write_temp(self, parent, temp, data):
        fd = os.open(
            temp,
            os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY | os.O_CLOEXEC,
            0o644,
            dir_fd=parent,
        )
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _cleanup_temp(self, parent, temp, hooks):
        if hooks.get("fail_temp_unlink"):
            raise AmbiguousOutcome()
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise AmbiguousOutcome() from exc

    def _install_new(self, parent, temp, name, hooks):
        if hooks.get("fail_install"):
            self._cleanup_temp(parent, temp, hooks)
            raise WorkerFail("exists")
        try:
            os.link(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        except FileExistsError:
            self._cleanup_temp(parent, temp, hooks)
            raise WorkerFail("exists")
        except OSError as exc:
            try:
                self._cleanup_temp(parent, temp, hooks)
            except AmbiguousOutcome:
                raise
            raise WorkerFail("io_error") from exc
        self._cleanup_temp(parent, temp, hooks)

    def _replace(self, parent, temp, name):
        try:
            os.rename(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        except OSError as exc:
            raise AmbiguousOutcome() from exc

    def _list_dir(self, fd):
        try:
            names = os.listdir(fd)
        except OSError as exc:
            raise WorkerFail("io_error") from exc
        out = []
        for name in names:
            try:
                st = os.lstat(name, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.EMLINK):
                    raise Escape() from exc
                raise WorkerFail("io_error") from exc
            out.append((name, st))
        return out

    def _summary(self, path, data: bytes):
        text = f"{path} {len(data)} {hashlib.sha256(data).hexdigest()}"
        return self._ok(text, len(text.encode("utf-8")), False, False)

    def _ok(self, text, byte_length, truncated, depth_limited, tool=None):
        return {
            "ambiguous": False,
            "status": "succeeded",
            "text": text,
            "byte_length": byte_length,
            "truncated": truncated,
            "depth_limited": depth_limited,
        }

    def _fail(self, token):
        raise WorkerFail(token)

    def _shaped(self, tool, text, byte_length, truncated, depth_limited, ok, token):
        return {
            "schema_version": 1,
            "ok": ok,
            "tool": tool,
            "truncated": truncated,
            "depth_limited": depth_limited,
            "byte_length": byte_length,
            "text": text,
            "error_token": token,
        }

    def finish(self, tool, outcome):
        if outcome.get("ambiguous"):
            return outcome
        body = self._shaped(
            tool,
            outcome["text"],
            outcome["byte_length"],
            outcome["truncated"],
            outcome["depth_limited"],
            outcome["status"] == "succeeded",
            None if outcome["status"] == "succeeded" else outcome.get("error_token"),
        )
        return {"ambiguous": False, "status": outcome["status"], "result": body}

    def _write(self, payload, attempt_key, hooks):
        path = payload["path"]
        content = payload["content"].encode("utf-8")
        expected = payload["expected_sha256"]
        parent, name = self._parent(path)
        try:
            st = self._lstat(parent, name)
            if st is not None:
                if stat.S_ISLNK(st.st_mode):
                    raise Escape()
                if not stat.S_ISREG(st.st_mode):
                    raise WorkerFail("not_a_file")
            if expected is None:
                if st is not None:
                    raise WorkerFail("exists")
            else:
                if st is None:
                    raise WorkerFail("missing")
                if self._hash(parent, name) != expected:
                    raise WorkerFail("hash_mismatch")
            temp = self._temp_name(attempt_key)
            self._write_temp(parent, temp, content)
            if hooks.get("before_replace"):
                hooks["before_replace"](temp, attempt_key, parent)
            if expected is None:
                self._install_new(parent, temp, name, hooks)
            else:
                self._replace(parent, temp, name)
            return self.finish("write", self._summary(path, content))
        finally:
            os.close(parent)

    def _edit(self, payload, attempt_key, hooks):
        path = payload["path"]
        expected = payload["expected_sha256"]
        parent, name = self._parent(path)
        try:
            st = self._lstat(parent, name)
            self._classify_file(st)
            if self._hash(parent, name) != expected:
                raise WorkerFail("hash_mismatch")
            raw = self._read(parent, name)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise WorkerFail("bad_utf8")
            count = text.count(payload["old"])
            if count != 1:
                raise WorkerFail("edit_not_unique")
            new_text = text.replace(payload["old"], payload["new"], 1)
            data = new_text.encode("utf-8")
            temp = self._temp_name(attempt_key)
            self._write_temp(parent, temp, data)
            if hooks.get("before_replace"):
                hooks["before_replace"](temp, attempt_key, parent)
            self._replace(parent, temp, name)
            return self.finish("edit", self._summary(path, data))
        finally:
            os.close(parent)

    def _grep(self, payload):
        path = payload["path"]
        pattern = payload["pattern"]
        parent, name = self._parent(path)
        try:
            st = self._lstat(parent, name)
            self._classify_file(st)
            try:
                raw = self._read(parent, name)
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise WorkerFail("bad_utf8")
            except OSError as exc:
                raise WorkerFail("io_error") from exc
            lines = [line for line in text.splitlines(keepends=True) if pattern in line]
            full = "".join(lines).encode("utf-8")
            return self.finish("grep", self._capped(full, False))
        finally:
            os.close(parent)

    def _find(self, payload):
        start = payload["path"]
        name_fixed = payload.get("name_fixed")
        parent, name = self._parent(start)
        try:
            st = self._lstat(parent, name)
            if st is None:
                raise WorkerFail("missing")
            if stat.S_ISLNK(st.st_mode):
                raise Escape()
            if not stat.S_ISDIR(st.st_mode):
                raise WorkerFail("not_a_dir")
        finally:
            os.close(parent)
        found = []
        limited = self._walk_find(start, 0, name_fixed, found)
        full = ("\n".join(found) + ("\n" if found else "")).encode("utf-8")
        return self.finish("find", self._capped(full, limited))

    def _walk_find(self, rel, depth, name_fixed, found):
        limited = False
        parent, name = self._parent(rel)
        fd = None
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            for name, st in self._list_dir(fd):
                child = rel + "/" + name
                is_link = stat.S_ISLNK(st.st_mode)
                is_dir = (not is_link) and stat.S_ISDIR(st.st_mode)
                if name_fixed is None or name == name_fixed:
                    found.append(child)
                if is_link:
                    continue
                if is_dir:
                    if depth + 1 > self.find_depth_cap:
                        limited = True
                        continue
                    if self._walk_find(child, depth + 1, name_fixed, found):
                        limited = True
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)
        return limited

    def _ls(self, payload):
        rel = payload["path"]
        parent, name = self._parent(rel)
        try:
            st = self._lstat(parent, name)
            if st is None:
                raise WorkerFail("missing")
            if stat.S_ISLNK(st.st_mode):
                raise Escape()
            if not stat.S_ISDIR(st.st_mode):
                raise WorkerFail("not_a_dir")
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            names = sorted(name for name, _st in self._list_dir(fd))
        finally:
            os.close(fd)
        full = ("\n".join(names) + ("\n" if names else "")).encode("utf-8")
        return self.finish("ls", self._capped(full, False))

    def _capped(self, full: bytes, depth_limited: bool):
        truncated = len(full) > self.result_cap
        text = _utf8_prefix(full, self.result_cap) if truncated else full.decode("utf-8")
        return self._ok(text, len(full), truncated, depth_limited)

    def _bash(self, payload, attempt_key, hooks):
        argv = payload["argv"]
        verb = argv[0]
        if verb not in self.bash_verbs:
            raise WorkerFail("io_error")
        if hooks.get("ambiguous_rm") and verb == "rm":
            raise AmbiguousOutcome()
        if verb == "mkdir":
            return self._mkdir(argv[1])
        if verb == "rm":
            return self._rm(argv[1], payload["expected_sha256"], hooks)
        if verb == "cp":
            return self._cp(argv[1], argv[2], payload["expected_sha256"], attempt_key, hooks)
        if verb == "mv":
            return self._mv(argv[1], argv[2], payload["expected_sha256"], hooks)
        raise WorkerFail("io_error")

    def _mkdir(self, rel):
        parent, name = self._parent(rel)
        try:
            st = self._lstat(parent, name)
            if st is not None:
                if stat.S_ISLNK(st.st_mode):
                    raise Escape()
                raise WorkerFail("exists")
            pst = os.fstat(parent)
            if not stat.S_ISDIR(pst.st_mode):
                raise WorkerFail("not_a_dir")
            try:
                os.mkdir(name, 0o755, dir_fd=parent)
            except FileExistsError:
                raise WorkerFail("exists")
            except FileNotFoundError:
                raise WorkerFail("missing")
            except OSError as exc:
                if exc.errno == errno.ENOTDIR:
                    raise WorkerFail("not_a_dir") from exc
                raise WorkerFail("io_error") from exc
            return self.finish("bash", self._ok("", 0, False, False))
        except FileNotFoundError:
            raise WorkerFail("missing")
        finally:
            os.close(parent)

    def _rm(self, rel, expected, hooks):
        parent, name = self._parent(rel)
        try:
            st = self._lstat(parent, name)
            self._classify_file(st)
            if self._hash(parent, name) != expected:
                raise WorkerFail("hash_mismatch")
            if hooks.get("unlink_raises"):
                raise AmbiguousOutcome()
            try:
                os.unlink(name, dir_fd=parent)
            except OSError as exc:
                raise AmbiguousOutcome() from exc
            return self.finish("bash", self._ok("", 0, False, False))
        finally:
            os.close(parent)

    def _cp(self, src, dst, expected, attempt_key, hooks):
        sp, sn = self._parent(src)
        try:
            st = self._lstat(sp, sn)
            self._classify_file(st)
            if self._hash(sp, sn) != expected:
                raise WorkerFail("hash_mismatch")
            data = self._read(sp, sn)
        finally:
            os.close(sp)
        dp, dn = self._parent(dst)
        try:
            dst_st = self._lstat(dp, dn)
            if dst_st is not None:
                if stat.S_ISLNK(dst_st.st_mode):
                    raise Escape()
                raise WorkerFail("exists")
            temp = self._temp_name(attempt_key)
            self._write_temp(dp, temp, data)
            if hooks.get("before_replace"):
                hooks["before_replace"](temp, attempt_key, dp)
            self._install_new(dp, temp, dn, hooks)
            return self.finish("bash", self._ok("", 0, False, False))
        finally:
            os.close(dp)

    def _mv(self, src, dst, expected, hooks):
        sp, sn = self._parent(src)
        dp = None
        try:
            st = self._lstat(sp, sn)
            self._classify_file(st)
            if self._hash(sp, sn) != expected:
                raise WorkerFail("hash_mismatch")
            if hooks.get("unlink_raises"):
                raise AmbiguousOutcome()
            dp, dn = self._parent(dst)
            dst_st = self._lstat(dp, dn)
            if dst_st is not None:
                if stat.S_ISLNK(dst_st.st_mode):
                    raise Escape()
                raise WorkerFail("exists")
            try:
                os.rename(sn, dn, src_dir_fd=sp, dst_dir_fd=dp)
            except OSError as exc:
                raise AmbiguousOutcome() from exc
            return self.finish("bash", self._ok("", 0, False, False))
        finally:
            if dp is not None:
                os.close(dp)
            os.close(sp)
