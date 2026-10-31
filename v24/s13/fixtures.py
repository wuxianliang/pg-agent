"""Deterministic W4b fixtures: workspace trees, v2 specs and harness reuse.

The trees are materialized from the W1 ``tool_contracts`` vector nodes so the
byte recipes are the reviewed ones.  The v2 manifests deliberately carry the
SQL-compatible ``\\x`` adapter digest while the in-process ``ApprovedPlugin``
uses the bare 64-hex declaration digest (W4-0 probe (a)).

macOS APFS rejects raw non-UTF-8 filenames.  ``workspace`` therefore returns a
``Workspace`` describing either a real filesystem entry (Linux) or the
test-only readdir preload mode used on macOS.  Production plugins never read
the preload or its environment variables.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
V24 = HERE.parent
ROOT = V24.parent
if str(V24 / "s11") not in sys.path:
    sys.path.insert(0, str(V24 / "s11"))

from plugin_fixtures import PluginHarness  # noqa: E402

from v24.host.canonical import compact_json  # noqa: E402
from v24.host.registry import (  # noqa: E402
    ApprovedAdapterRegistry,
    ApprovedPlugin,
    ApprovedTool,
    adapter_declaration_digest,
)

VECTORS = HERE / "vectors"
PLUGINS = HERE / "plugins"
PRELOAD = HERE / "w4b_non_utf8_preload.cjs"
DESCRIPTOR_DOC = json.loads(
    (VECTORS / "descriptor_v2.json").read_text(encoding="utf-8"))
DESCRIPTORS = {
    case["id"].rsplit(".", 1)[-1]: case["input"]
    for case in DESCRIPTOR_DOC["cases"]
    if case["id"].startswith("descriptor.v2.")
}
TOOL_CONTRACTS = json.loads(
    (VECTORS / "tool_contracts.json").read_text(encoding="utf-8"))
_CONTRACT = {case["id"]: case for case in TOOL_CONTRACTS["cases"]}
PORTABLE_NODES = _CONTRACT["tool.fixture_tree.portable_nodes"]["input"]["nodes"]
LIST_NODES = _CONTRACT["tool.list.contract"]["input"]["fixture_tree"]
SEARCH_CASES = {
    case["id"]: case for case in _CONTRACT["tool.search.contract"]["input"]["inputs"]
}
_EILSEQ = getattr(errno, "EILSEQ", 92)
_UNSUPPORTED_NAME = {_EILSEQ, errno.ENOTSUP}


class ToolchainAbsent(RuntimeError):
    pass


@dataclass(frozen=True)
class Workspace:
    root: str
    non_utf8_mode: str          # "filesystem" | "preload_shim" | "none"
    preload: Path | None = None
    ledger: Path | None = None

    def env_overlay(self) -> dict[str, str]:
        if self.non_utf8_mode != "preload_shim":
            return {}
        return {
            "NODE_OPTIONS": f"--require {self.preload}",
            "W4B_NON_UTF8_ROOT": self.root,
            "W4B_SHIM_LEDGER": str(self.ledger),
        }


def _raw_path(root, path):
    if isinstance(path, dict):
        if "bytes_hex" not in path:
            raise ValueError(f"unsupported path node {path!r}")
        return os.path.join(os.fsencode(root), bytes.fromhex(path["bytes_hex"]))
    return os.path.join(os.fsencode(root), path.encode("utf-8"))


def _node_bytes(node):
    if "bytes_hex" in node:
        return bytes.fromhex(node["bytes_hex"])
    recipe = node.get("recipe") or {}
    if "repeat_hex" in recipe:
        return bytes.fromhex(recipe["repeat_hex"]) * int(recipe["count"])
    if "lines" in recipe:
        text = "\n".join(recipe["lines"])
        if recipe.get("final_newline", True):
            text += "\n"
        return text.encode("utf-8")
    return b""


def _mkdirs(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def materialize_nodes(root, nodes):
    root = os.fsencode(root)
    os.makedirs(root, exist_ok=True)
    for node in nodes:
        kind = node.get("kind")
        if kind != "directory":
            continue
        path = _raw_path(root, node["path"])
        os.makedirs(path, exist_ok=True)
        recipe = node.get("recipe") or {}
        if "regular_files" in recipe:
            count = int(recipe["regular_files"])
            template = recipe["name"]
            content = bytes.fromhex(recipe.get("content_hex", ""))
            for index in range(count):
                name = template % index
                with open(os.path.join(path, name.encode("utf-8")), "wb") as handle:
                    handle.write(content)
    for node in nodes:
        kind = node.get("kind")
        path = _raw_path(root, node.get("path"))
        if kind == "directory":
            continue
        _mkdirs(path)
        if kind == "file":
            with open(path, "wb") as handle:
                handle.write(_node_bytes(node))
        elif kind == "symlink":
            os.symlink(node["target"], path)
        elif kind == "special":
            os.mkfifo(path)
        else:
            raise ValueError(f"unsupported fixture node {kind!r}")


def _split_nodes(nodes):
    valid = []
    invalid = []
    for node in nodes:
        if isinstance(node.get("path"), dict):
            invalid.append(node)
        else:
            valid.append(node)
    return valid, invalid


def _create_invalid(root, nodes):
    """Try real raw names; return True only when exact bytes read back."""
    created = []
    ok = False
    try:
        for node in nodes:
            path = _raw_path(root, node["path"])
            _mkdirs(path)
            if node.get("kind") != "file":
                raise ValueError("non-UTF-8 fixture nodes must be files")
            with open(path, "wb") as handle:
                handle.write(_node_bytes(node))
            created.append(path)
        parent = os.fsencode(root)
        names = set(os.listdir(parent))
        for node in nodes:
            raw = bytes.fromhex(node["path"]["bytes_hex"])
            if raw not in names:
                return False
        ok = True
        return True
    except OSError as exc:
        if exc.errno not in _UNSUPPORTED_NAME:
            raise
        return False
    finally:
        if not ok:
            for path in created:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _probe_non_utf8(parent):
    """Probe raw-name support in a disposable sibling directory."""
    probe = Path(parent) / f".w4b-probe-{uuid.uuid4().hex}"
    probe.mkdir()
    raw = os.path.join(os.fsencode(probe), b"\xff")
    try:
        fd = os.open(raw, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        names = set(os.listdir(os.fsencode(probe)))
        return b"\xff" in names
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_NAME:
            return False
        raise
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _shim_workspace(root):
    ledger = Path(root).parent / f"w4b-nonutf8-{uuid.uuid4().hex}.jsonl"
    if ledger.exists():
        ledger.unlink()
    return Workspace(os.path.realpath(root), "preload_shim",
                     preload=PRELOAD, ledger=ledger)


def _workspace_result(root, nodes):
    valid, invalid = _split_nodes(nodes)
    materialize_nodes(root, valid)
    if not invalid:
        return Workspace(os.path.realpath(root), "none")
    forced = os.environ.get("W4B_FORCE_NON_UTF8_MODE")
    if forced not in (None, "preload_shim"):
        raise ValueError("W4B_FORCE_NON_UTF8_MODE only supports preload_shim")
    if forced == "preload_shim":
        return _shim_workspace(root)
    if _probe_non_utf8(Path(root).parent):
        if not _create_invalid(root, invalid):
            raise OSError("filesystem reported raw-name support but create failed")
        return Workspace(os.path.realpath(root), "filesystem")
    return _shim_workspace(root)

def _prepare_root(root):
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _list_nodes():
    return [
        {"kind": "directory", "path": "a"},
        {"kind": "file", "path": "a/child", "bytes_hex": "78"},
        {"kind": "symlink", "path": "b", "target": "a"},
        {"kind": "file", "path": "c", "bytes_hex": "7879"},
        {"kind": "file", "path": ".hidden", "bytes_hex": "78"},
        {"kind": "file", "path": ".git/config", "bytes_hex": "78"},
        {"kind": "special", "path": "socket", "tag": "unix_socket"},
        {"kind": "file", "path": {"bytes_hex": "ff"}, "bytes_hex": ""},
    ]


def workspace(root, kind="list"):
    """Materialize a reviewed tree; return Workspace (never None)."""
    root = _prepare_root(root)
    if kind == "portable":
        return _workspace_result(root, PORTABLE_NODES)
    if kind == "list":
        return _workspace_result(root, _list_nodes())
    if kind == "empty":
        return Workspace(os.path.realpath(root), "none")
    raise ValueError(f"unknown workspace kind {kind!r}")


def read_workspace(root):
    """Materialize the W5 read probe tree without touching frozen vectors."""
    root = _prepare_root(root)
    nodes = [
        {"kind": "file", "path": "empty", "bytes_hex": ""},
        {"kind": "file", "path": "binary", "bytes_hex": "610062"},
        {"kind": "file", "path": "nul_late", "bytes_hex": "61" * 8192 + "000a"},
        {"kind": "directory", "path": "dir"},
        {"kind": "file", "path": "dir/f", "bytes_hex": "780a"},
        {"kind": "special", "path": "fifo"},
        {"kind": "file", "path": "noperm", "bytes_hex": "78"},
        {"kind": "file", "path": "three", "bytes_hex": "610a620a630a"},
        {"kind": "file", "path": "long_after",
         "bytes_hex": ("610a" + "7a" * 16385 + "0a630a")},
        {"kind": "file", "path": "ctrl16384", "bytes_hex": "01" * 16384},
        {"kind": "file", "path": ".hidden", "bytes_hex": "68"},
        {"kind": "symlink", "path": "dirlink", "target": "dir"},
        {"kind": "file", "path": "nine5",
         "recipe": {"lines": ["a" * 9000] * 5, "final_newline": False}},
        {"kind": "file", "path": "wide",
         "recipe": {"lines": ["\x01" * 523] * 2000, "final_newline": False}},
        {"kind": "file", "path": "newlines_1m",
         "recipe": {"repeat_hex": "0a", "count": 1048576}},
    ]
    materialize_nodes(root, nodes)
    return Workspace(os.path.realpath(root), "none")


def search_workspace(root, case_id):
    case = SEARCH_CASES[case_id]
    root = _prepare_root(root)
    return _workspace_result(root, case["fixture_tree"])


def manifest_bytes(identity, realm, descriptors, language):
    document = {
        "identity": identity,
        "version": "1",
        "requires": [],
        "provides": [
            {"realm": realm, "key": item["tool"]["key"],
             "descriptor": item}
            for item in descriptors
        ],
        "adapter_digest": "\\x" + adapter_declaration_digest(language),
    }
    return compact_json(document)


@dataclass(frozen=True)
class V2Spec:
    language: str
    identity: str
    realm: str
    tool_keys: tuple[str, ...]
    manifest: bytes
    artifact_digest: str
    entry: ApprovedPlugin
    spawn_log: Path
    workspace: str
    env_overlay: tuple[tuple[str, str], ...] = ()

    def environment(self) -> dict[str, str]:
        return dict(self.env_overlay)


def _interpreter(language):
    if language == "python":
        return sys.executable
    node = shutil.which("node")
    if node is None:
        raise ToolchainAbsent("node")
    return node


def _root_path(value):
    return value.root if isinstance(value, Workspace) else os.path.realpath(value)


def build_spec(base, workspace_root, *, language, identity, descriptors,
               realm, timeout_ms=5000, extra_env=None):
    base = Path(base)
    install = base / "install"
    install.mkdir(parents=True, exist_ok=True)
    plugin_name = "fs_read.py" if language == "python" else "fs_tools.js"
    source = PLUGINS / plugin_name
    artifact = install / plugin_name
    shutil.copyfile(source, artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    spawn_dir = base / "spawn"
    spawn_dir.mkdir(parents=True, exist_ok=True)
    spawn_log = spawn_dir / f"{uuid.uuid4().hex}.log"
    manifest = manifest_bytes(identity, realm, descriptors, language)
    argv = (_interpreter(language), str(artifact), "serve",
            "--spawn-log", str(spawn_log))
    tools = tuple(
        ApprovedTool.from_descriptor(item, key=item["tool"]["key"])
        for item in descriptors
    )
    overlay = dict(extra_env or {})
    allowlist = ("PATH", "HOME", "V24_WORKSPACE_ROOT", *overlay.keys())
    workspace_path = _root_path(workspace_root)
    plugin = ApprovedPlugin(
        adapter_id=f"{identity}.{realm}",
        language=language,
        identity=identity,
        version="1",
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=digest,
        adapter_digest=adapter_declaration_digest(language),
        argv=argv,
        cwd=str(install),
        environment_allowlist=allowlist,
        tools=tools,
        workspace_root=workspace_path,
        timeout_ms=timeout_ms,
    )
    return V2Spec(
        language=language,
        identity=identity,
        realm=realm,
        tool_keys=tuple(item["tool"]["key"] for item in descriptors),
        manifest=manifest,
        artifact_digest=digest,
        entry=plugin,
        spawn_log=spawn_log,
        workspace=workspace_path,
        env_overlay=tuple(sorted(overlay.items())),
    )


def _extra_env(workspace_root):
    return workspace_root.env_overlay() if isinstance(workspace_root, Workspace) else {}


def read_spec(base, workspace_root, *, realm=None):
    return build_spec(
        base, workspace_root, language="python", identity="v24.fs.python",
        descriptors=[DESCRIPTORS["read"]],
        realm=realm or f"read-{uuid.uuid4().hex[:8]}",
        extra_env=_extra_env(workspace_root))


def node_spec(base, workspace_root, *, realm=None):
    return build_spec(
        base, workspace_root, language="node", identity="v24.fs.node",
        descriptors=[DESCRIPTORS["list"], DESCRIPTORS["search"]],
        realm=realm or f"node-{uuid.uuid4().hex[:8]}",
        extra_env=_extra_env(workspace_root))


def plugin_registry(specs):
    return ApprovedAdapterRegistry(tuple(spec.entry for spec in specs))


def open_harness(fixture, specs, workdir, *, realm):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    os.chmod(workdir, 0o700)
    return PluginHarness(fixture, plugin_registry(specs), workdir, realm=realm)


def install_spawn_log(harness, install_id):
    row = dict(harness.install_row(install_id))
    for name in ("manifest_digest", "artifact_digest", "adapter_digest"):
        value = row.get(name)
        if isinstance(value, str) and value.startswith("\\x"):
            row[name] = value[2:]
    entry = harness.registry.lookup_install(row)
    argv = list(entry.argv)
    if "--spawn-log" not in argv:
        return None
    index = argv.index("--spawn-log")
    return Path(argv[index + 1])


def spawn_count(harness, install_id):
    path = install_spawn_log(harness, install_id)
    if path is None or not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())
