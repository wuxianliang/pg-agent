"""Opt-in DuckDB grammar-extension configuration and connection bootstrap."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_FEATURE = "pipe_query_syntax"
DEFAULT_EXTENSION_PATH = Path(
    "/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/extension/"
    "loadable_grammar_extension_demo.duckdb_extension"
)
DEFAULT_EXTENSION_SHA256 = "fce89a46632a3ff3b98f75bc7f9bafb7c663e5b31d3cc0453d012ce4c8986393"
EXPECTED_PACKAGE = "1.6.0.dev366+ga1f0ab1911"
EXPECTED_SOURCE_ID = "a1f0ab1911"
EXPECTED_LIBRARY_VERSION = "v1.6.0-dev13823"
_SHA256 = re.compile(r"[0-9a-f]{64}", re.I)
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class GrammarExtensionError(RuntimeError):
    """Raised when an opted-in grammar extension cannot be trusted or activated."""


def _parse_bool_env(name: str, raw: str | None, *, missing: bool) -> bool:
    if raw is None or raw.strip() == "":
        return missing
    token = raw.strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    raise GrammarExtensionError(f"invalid boolean for {name}: {raw!r}")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parse_feature_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(x) for x in value)
    if not isinstance(value, str):
        raise GrammarExtensionError(f"active grammar features have unexpected type {type(value).__name__}")
    text = value.strip()
    if text.startswith("{") and text.endswith("}"):
        text = "[" + text[1:-1] + "]"
    if not (text.startswith("[") and text.endswith("]")):
        raise GrammarExtensionError(f"malformed active grammar features: {value!r}")
    inner = text[1:-1].strip()
    if not inner:
        return ()
    features: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        if inner[i] in "'\"":
            quote = inner[i]
            j = i + 1
            buf: list[str] = []
            while j < n and inner[j] != quote:
                buf.append(inner[j])
                j += 1
            if j >= n:
                raise GrammarExtensionError("unterminated feature name in active grammar list")
            features.append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and inner[j] != ",":
                j += 1
            token = inner[i:j].strip()
            if not token:
                raise GrammarExtensionError("malformed active grammar features")
            features.append(token)
            i = j
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        if inner[i] != ",":
            raise GrammarExtensionError("malformed active grammar features")
        i += 1
    return tuple(features)


@dataclass(frozen=True)
class GrammarExtensionConfig:
    enabled: bool = False
    extension_path: Path | None = None
    extension_sha256: str | None = None
    active_features: tuple[str, ...] = ()
    enable_external_access: bool = False

    @classmethod
    def from_env(cls) -> "GrammarExtensionConfig":
        enabled = _parse_bool_env(
            "PG_AGENT_DUCKDB_GRAMMAR_ENABLED",
            os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_ENABLED"),
            missing=False,
        )
        external = _parse_bool_env(
            "PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS",
            os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS"),
            missing=False,
        )
        if not enabled:
            return cls(enabled=False, enable_external_access=external)
        raw_features = os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_FEATURES")
        if raw_features is None:
            features = (DEFAULT_FEATURE,)
        else:
            features = tuple(part.strip() for part in raw_features.split(",") if part.strip())
        path_value = os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_PATH")
        hash_value = os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_SHA256")
        return cls(
            enabled=True,
            extension_path=Path(path_value).expanduser() if path_value else DEFAULT_EXTENSION_PATH,
            extension_sha256=(hash_value or DEFAULT_EXTENSION_SHA256).lower(),
            active_features=features,
            enable_external_access=external,
        )

    def validate(self) -> None:
        if self.enable_external_access:
            raise GrammarExtensionError("enable_external_access=true is rejected; v6 connections must keep external access off")
        if not self.enabled:
            return
        if self.active_features != (DEFAULT_FEATURE,):
            raise GrammarExtensionError(
                f"unsupported active grammar features: {self.active_features!r}; "
                f"only {DEFAULT_FEATURE!r} is supported"
            )
        if self.extension_path is None:
            raise GrammarExtensionError("grammar extension path is required when enabled")
        if self.extension_path.suffix != ".duckdb_extension":
            raise GrammarExtensionError(f"grammar extension must end in .duckdb_extension: {self.extension_path}")
        if self.extension_sha256 is None or not _SHA256.fullmatch(self.extension_sha256):
            raise GrammarExtensionError("grammar extension SHA-256 must be exactly 64 hexadecimal characters")

    def verified_path_and_hash(self) -> tuple[Path, str]:
        self.validate()
        if not self.enabled:
            raise GrammarExtensionError("grammar extension is disabled")
        assert self.extension_path is not None and self.extension_sha256 is not None
        path = self.extension_path
        if path.is_symlink() or not path.exists() or not path.is_file():
            raise GrammarExtensionError(f"grammar extension is not a trusted regular file: {path}")
        canonical = path.resolve(strict=True)
        with canonical.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        if digest.lower() != self.extension_sha256.lower():
            raise GrammarExtensionError(
                f"grammar extension hash mismatch for {canonical}: expected {self.extension_sha256}, got {digest}"
            )
        return canonical, digest


@dataclass(frozen=True)
class DuckDBGrammarCapabilities:
    enabled: bool
    loaded: bool
    active_features: tuple[str, ...]
    package_version: str | None = None
    source_id: str | None = None
    library_version: str | None = None

    @property
    def pipe_query_syntax(self) -> bool:
        return self.enabled and self.loaded and DEFAULT_FEATURE in self.active_features

    def prompt_text(self) -> str:
        if not self.pipe_query_syntax:
            return ""
        return (
            "当前 DuckDB 工作台连接已启用 pipe_query_syntax。可使用从 FROM 开始的管道查询，"
            "例如：FROM sales_src |> WHERE revenue > 0 |> SELECT month, revenue。"
            "仍只能提交单条只读 SELECT；不要使用 LOAD、INSTALL 或修改安全设置。"
        )


def _setting_bool(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    value = con.execute(f"SELECT current_setting({_sql_literal(name)})").fetchone()[0]
    return str(value).lower() in {"true", "1"}


def _build_identity(con: duckdb.DuckDBPyConnection) -> tuple[str, str, str]:
    package_version = str(getattr(duckdb, "__version__", ""))
    if package_version != EXPECTED_PACKAGE:
        raise GrammarExtensionError(
            f"unexpected DuckDB Python package: expected {EXPECTED_PACKAGE}, got {package_version}"
        )
    row = con.execute("SELECT library_version, source_id FROM pragma_version()").fetchone()
    if row is None or len(row) < 2:
        raise GrammarExtensionError("DuckDB pragma_version() did not return build identity")
    library_version, source_id = str(row[0]), str(row[1])
    if source_id != EXPECTED_SOURCE_ID:
        raise GrammarExtensionError(f"unexpected DuckDB source_id: expected {EXPECTED_SOURCE_ID}, got {source_id}")
    if library_version != EXPECTED_LIBRARY_VERSION:
        raise GrammarExtensionError(
            f"unexpected DuckDB library version: expected {EXPECTED_LIBRARY_VERSION}, got {library_version}"
        )
    return package_version, source_id, library_version


def _grammar_extension_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    cursor = con.execute("SELECT * FROM duckdb_grammar_extensions()")
    rows = cursor.fetchall()
    description = getattr(cursor, "description", None) or getattr(con, "description", None)
    if not rows:
        return set()
    if description:
        names = [str(item[0]).lower() for item in description]
        if "name" in names:
            idx = names.index("name")
            return {str(row[idx]) for row in rows}
    return {str(row[0]) for row in rows}


def _hash_extension(config: GrammarExtensionConfig, prepared_extension_path: Path | None) -> Path:
    path, digest = config.verified_path_and_hash()
    if prepared_extension_path is not None and path != prepared_extension_path:
        raise GrammarExtensionError(
            f"grammar extension path changed after startup: expected {prepared_extension_path}, got {path}"
        )
    if digest.lower() != config.extension_sha256.lower():
        raise GrammarExtensionError("grammar extension hash mismatch before LOAD")
    return path


def bootstrap_connection(
    config: GrammarExtensionConfig,
    *,
    prepared_extension_path: Path | None = None,
) -> tuple[duckdb.DuckDBPyConnection, DuckDBGrammarCapabilities]:
    """Create one hardened v6 connection and optionally activate its grammar."""
    config.validate()
    connect_config: dict[str, Any] = {}
    if config.enabled:
        connect_config["allow_unsigned_extensions"] = True
    con = duckdb.connect(config=connect_config)
    try:
        package_version, source_id, library_version = _build_identity(con)
        con.execute("SET autoinstall_known_extensions=false")
        con.execute("SET autoload_known_extensions=false")
        if config.enabled:
            path = _hash_extension(config, prepared_extension_path)
            con.execute(f"LOAD {_sql_literal(str(path))}")
            con.execute("SET enable_external_access=false")
            if _setting_bool(con, "enable_external_access"):
                raise GrammarExtensionError("DuckDB external access could not be disabled")
            features_sql = "[" + ", ".join(_sql_literal(item) for item in config.active_features) + "]"
            con.execute(f"SET active_grammar_extensions={features_sql}")
            active_row = con.execute("SELECT current_setting('active_grammar_extensions')").fetchone()
            if active_row is None:
                raise GrammarExtensionError("active grammar features setting is missing")
            active = _parse_feature_list(active_row[0])
            if active != config.active_features:
                raise GrammarExtensionError(
                    f"active grammar features mismatch: expected {config.active_features}, got {active}"
                )
            available = _grammar_extension_names(con)
            if not set(config.active_features).issubset(available):
                raise GrammarExtensionError(f"active grammar extension metadata missing: {config.active_features}")
            caps = DuckDBGrammarCapabilities(True, True, active, package_version, source_id, library_version)
        else:
            con.execute("SET enable_external_access=false")
            if _setting_bool(con, "enable_external_access"):
                raise GrammarExtensionError("DuckDB external access could not be disabled")
            caps = DuckDBGrammarCapabilities(False, False, (), package_version, source_id, library_version)
        con.execute("SET memory_limit='512 MiB'")
        return con, caps
    except Exception:
        con.close()
        raise
