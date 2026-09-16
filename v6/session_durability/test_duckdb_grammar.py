"""Fake-connector and optional native gates for DuckDB grammar bootstrap."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from v6.dialect_guardrails.duckdb_validation import validate_read_query
from v6.kernel_freeze.worker import AgentWorker
from v6.session_durability.duckdb_grammar import (
    DEFAULT_EXTENSION_SHA256,
    DEFAULT_FEATURE,
    DuckDBGrammarCapabilities,
    EXPECTED_LIBRARY_VERSION,
    EXPECTED_PACKAGE,
    EXPECTED_SOURCE_ID,
    GrammarExtensionConfig,
    GrammarExtensionError,
    _parse_feature_list,
    bootstrap_connection,
)
from v6.session_durability.duckdb_runtime import DuckSessionManager, SessionError

NATIVE_EXT = Path(
    "/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/extension/"
    "loadable_grammar_extension_demo.duckdb_extension"
)
NATIVE_TRUE = {"1", "true", "yes", "on"}


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def expect_error(label: str, fn, type_: type[Exception] = GrammarExtensionError) -> Exception:
    try:
        fn()
    except Exception as exc:
        check(label, isinstance(exc, type_), f"{type(exc).__name__}: {exc}")
        return exc
    raise AssertionError(f"expected {type_.__name__} for {label}")


def _index(calls: list[str], needle: str) -> int:
    for i, item in enumerate(calls):
        if needle.lower() in item.lower():
            return i
    raise AssertionError(f"missing call containing {needle!r} in {calls}")


class FakeDuck:
    def __init__(self) -> None:
        self.__version__ = EXPECTED_PACKAGE
        self.connect_configs: list[dict] = []
        self.calls: list[str] = []
        self.library = EXPECTED_LIBRARY_VERSION
        self.source = EXPECTED_SOURCE_ID
        self.active_value: object = [DEFAULT_FEATURE]
        self.grammar_rows = [(DEFAULT_FEATURE, "pipe")]
        self.fail_sql: dict[str, Exception] = {}
        self.connections: list["FakeCon"] = []

    def connect(self, config=None):
        cfg = dict(config or {})
        self.connect_configs.append(cfg)
        con = FakeCon(self)
        self.connections.append(con)
        return con


class FakeCon:
    def __init__(self, owner: FakeDuck) -> None:
        self.owner = owner
        self.closed = False
        self.last_sql = ""
        self.description = (("name",), ("description",))

    def execute(self, sql: str, *args, **kwargs):
        if self.closed:
            raise RuntimeError("closed")
        self.last_sql = sql
        self.owner.calls.append(sql)
        for needle, exc in self.owner.fail_sql.items():
            if needle.lower() in sql.lower():
                raise exc
        return self

    def fetchone(self):
        sql = self.last_sql.lower()
        if "pragma_version" in sql:
            return (self.owner.library, self.owner.source)
        if "current_setting('enable_external_access')" in sql:
            return (False,)
        if "current_setting('active_grammar_extensions')" in sql:
            return (self.owner.active_value,)
        return None

    def fetchall(self):
        if "duckdb_grammar_extensions" in self.last_sql.lower():
            return list(self.owner.grammar_rows)
        return []

    def close(self) -> None:
        self.closed = True
        self.owner.calls.append("CLOSE")


def _ext_file(directory: Path, payload: bytes = b"demo-extension") -> tuple[Path, str]:
    path = directory / "demo.duckdb_extension"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def _enabled_config(path: Path, digest: str) -> GrammarExtensionConfig:
    return GrammarExtensionConfig(
        enabled=True,
        extension_path=path,
        extension_sha256=digest,
        active_features=(DEFAULT_FEATURE,),
    )


def test_from_env_disabled(monkey_env: dict[str, str]) -> None:
    with unittest.mock.patch.dict(os.environ, monkey_env, clear=False):
        cfg = GrammarExtensionConfig.from_env()
        cfg.validate()
        check("disabled path is None", cfg.extension_path is None)
        check("disabled hash is None", cfg.extension_sha256 is None)
        check("disabled features empty", cfg.active_features == ())
        check("disabled flag", cfg.enabled is False)


def test_config_errors() -> None:
    expect_error(
        "external access rejected while disabled",
        lambda: GrammarExtensionConfig(enable_external_access=True).validate(),
    )
    expect_error(
        "bad feature",
        lambda: GrammarExtensionConfig(
            enabled=True, extension_path=Path("x.duckdb_extension"),
            extension_sha256="a" * 64, active_features=("nope",),
        ).validate(),
    )
    expect_error(
        "bad hash format",
        lambda: GrammarExtensionConfig(
            enabled=True, extension_path=Path("x.duckdb_extension"),
            extension_sha256="zzz", active_features=(DEFAULT_FEATURE,),
        ).validate(),
    )


def test_parse_features() -> None:
    check("list features", _parse_feature_list(["pipe_query_syntax"]) == (DEFAULT_FEATURE,))
    check("varchar features", _parse_feature_list("['pipe_query_syntax']") == (DEFAULT_FEATURE,))
    expect_error("malformed features", lambda: _parse_feature_list("not-a-list"))


def test_disabled_bootstrap_order() -> None:
    fake = FakeDuck()
    with unittest.mock.patch("v6.session_durability.duckdb_grammar.duckdb", fake):
        con, caps = bootstrap_connection(GrammarExtensionConfig(
            enabled=False, extension_path=Path("/missing/not-used.duckdb_extension"),
            extension_sha256="a" * 64,
        ))
    check("disabled connect has no unsigned key", "allow_unsigned_extensions" not in fake.connect_configs[0], fake.connect_configs)
    joined = "\n".join(fake.calls)
    check("disabled skips LOAD", "LOAD " not in joined)
    check("disabled skips active grammar", "active_grammar_extensions" not in joined)
    check("disabled capabilities", caps.enabled is False and caps.loaded is False and caps.active_features == ())
    check("disabled connection open", con.closed is False)
    idx_id = _index(fake.calls, "pragma_version")
    idx_auto = _index(fake.calls, "autoinstall_known_extensions")
    idx_load_ext = _index(fake.calls, "autoload_known_extensions")
    idx_ext = _index(fake.calls, "enable_external_access=false")
    check("disabled identity before hardening", idx_id < idx_auto < idx_load_ext < idx_ext)


def test_enabled_bootstrap_order(tmp_path: Path) -> None:
    path, digest = _ext_file(tmp_path)
    fake = FakeDuck()
    with unittest.mock.patch("v6.session_durability.duckdb_grammar.duckdb", fake):
        con, caps = bootstrap_connection(_enabled_config(path, digest), prepared_extension_path=path.resolve())
    check("unsigned only when enabled", fake.connect_configs[0] == {"allow_unsigned_extensions": True})
    calls = fake.calls
    order = [
        _index(calls, "pragma_version"),
        _index(calls, "autoinstall_known_extensions"),
        _index(calls, "autoload_known_extensions"),
        _index(calls, "LOAD "),
        _index(calls, "enable_external_access=false"),
        _index(calls, "current_setting('enable_external_access')"),
        _index(calls, "active_grammar_extensions="),
        _index(calls, "current_setting('active_grammar_extensions')"),
        _index(calls, "duckdb_grammar_extensions"),
    ]
    check("enabled SQL order", order == sorted(order), order)
    check("pipe capability", caps.pipe_query_syntax is True)
    check("prompt has pipe", "pipe_query_syntax" in caps.prompt_text() and "|>" in caps.prompt_text())
    text = caps.prompt_text()
    check("prompt hides secrets", "sha256" not in text.lower() and "unsigned" not in text.lower() and str(path) not in text)
    con.close()


def test_hash_mismatch_closes(tmp_path: Path) -> None:
    path, _ = _ext_file(tmp_path, b"one")
    other = hashlib.sha256(b"two").hexdigest()
    fake = FakeDuck()
    with unittest.mock.patch("v6.session_durability.duckdb_grammar.duckdb", fake):
        expect_error("hash mismatch", lambda: bootstrap_connection(_enabled_config(path, other)))
    check("hash mismatch closed connection", fake.connections[0].closed is True)
    check("hash mismatch did not LOAD", all("LOAD " not in item for item in fake.calls), fake.calls)


def test_load_error_closes(tmp_path: Path) -> None:
    path, digest = _ext_file(tmp_path)
    fake = FakeDuck()
    fake.fail_sql["LOAD "] = RuntimeError("load failed")
    with unittest.mock.patch("v6.session_durability.duckdb_grammar.duckdb", fake):
        expect_error("LOAD failure", lambda: bootstrap_connection(_enabled_config(path, digest)), RuntimeError)
    check("LOAD failure closed", fake.connections[0].closed is True)


def test_bootstrap_error_wrapped() -> None:
    mgr = DuckSessionManager.__new__(DuckSessionManager)
    mgr._grammar_config = GrammarExtensionConfig()
    mgr._prepared_extension_path = None

    def boom(*args, **kwargs):
        raise GrammarExtensionError("nope")

    with unittest.mock.patch("v6.session_durability.duckdb_runtime.bootstrap_connection", boom):
        exc = expect_error("wrapped bootstrap", mgr._open_connection, SessionError)
    check("wrapped type", exc.envelope["Type"] == "DUCK_GRAMMAR_BOOTSTRAP_FAILED", exc.envelope)


def test_prompt_gating() -> None:
    original = [{"role": "user", "content": "hi"}]
    payload = {"messages": original, "run_id": "run-1"}
    enabled = DuckDBGrammarCapabilities(True, True, (DEFAULT_FEATURE,), EXPECTED_PACKAGE, EXPECTED_SOURCE_ID, EXPECTED_LIBRARY_VERSION)
    disabled = DuckDBGrammarCapabilities(False, False, (), EXPECTED_PACKAGE, EXPECTED_SOURCE_ID, EXPECTED_LIBRARY_VERSION)

    class Proc:
        def __init__(self, text: str):
            self.text = text
        def prompt_text_for_run(self, run_id):
            if not run_id:
                return ""
            return self.text

    worker = AgentWorker.__new__(AgentWorker)
    worker.duck_processor = Proc(enabled.prompt_text())
    worker.llm_fn = lambda messages, **kwargs: messages
    worker.model = "m"
    worker.api_uri = ""
    worker.api_key = ""
    worker.llm_retries = 1
    messages = worker._messages_for_llm(payload)
    check("payload messages unchanged", payload["messages"] is original)
    check("copy is new list", messages is not original)
    check("fragment appended", messages[-1]["role"] == "system" and "pipe_query_syntax" in messages[-1]["content"])
    seen: list[object] = []
    def llm_fn(msgs, **kwargs):
        seen.append(msgs)
        if len(seen) == 1:
            raise RuntimeError("retry")
        return "ok"
    worker.llm_fn = llm_fn
    worker._invoke_llm(payload)
    check("retry uses same list", len(seen) == 2 and seen[0] is seen[1], seen)

    worker.duck_processor = Proc(disabled.prompt_text())
    empty = worker._messages_for_llm(payload)
    check("disabled prompt omitted", empty == original)

    worker.duck_processor = Proc(enabled.prompt_text())
    missing = worker._messages_for_llm({"messages": original})
    check("missing run keeps copy without forcing session", missing == original)


def test_native_marker(tmp_path: Path) -> None:
    requested = os.environ.get("PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST", "").strip().lower() in NATIVE_TRUE
    if not requested:
        print("[SKIP] native grammar integration (PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST unset)")
        return
    if not NATIVE_EXT.is_file() or NATIVE_EXT.is_symlink():
        raise AssertionError(f"native test requested but extension missing: {NATIVE_EXT}")
    digest = hashlib.sha256(NATIVE_EXT.read_bytes()).hexdigest()
    check("pinned extension digest", digest == DEFAULT_EXTENSION_SHA256, digest)
    cfg = GrammarExtensionConfig(
        enabled=True,
        extension_path=NATIVE_EXT,
        extension_sha256=DEFAULT_EXTENSION_SHA256,
        active_features=(DEFAULT_FEATURE,),
    )
    con, caps = bootstrap_connection(cfg)
    try:
        check("native identity", caps.package_version == EXPECTED_PACKAGE and caps.source_id == EXPECTED_SOURCE_ID and caps.library_version == EXPECTED_LIBRARY_VERSION)
        check("native capability", caps.pipe_query_syntax is True)
        text = caps.prompt_text()
        check("native prompt", "pipe_query_syntax" in text and "|>" in text)
        check("native prompt secrecy", str(NATIVE_EXT) not in text and DEFAULT_EXTENSION_SHA256 not in text and "unsigned" not in text.lower())
        pipe = "FROM (SELECT 1 AS x) t |> WHERE x > 0 |> SELECT x"
        validated = validate_read_query(pipe, con)
        rows = con.execute(validated.sql).fetchall()
        check("pipe executes", rows == [(1,)], rows)
        other, other_caps = bootstrap_connection(cfg)
        try:
            check("second connection independent", other_caps.pipe_query_syntax is True)
            check("second connection pipe", other.execute(pipe).fetchall() == [(1,)])
        finally:
            other.close()
        check("first still works after second close", con.execute(pipe).fetchall() == [(1,)])
    finally:
        con.close()
    off, off_caps = bootstrap_connection(GrammarExtensionConfig())
    try:
        check("disabled native caps", off_caps.pipe_query_syntax is False)
        try:
            off.execute("FROM (SELECT 1 AS x) t |> WHERE x > 0 |> SELECT x")
            check("disabled rejects pipe", False)
        except Exception:
            check("disabled rejects pipe", True)
    finally:
        off.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_from_env_disabled({
            "PG_AGENT_DUCKDB_GRAMMAR_ENABLED": "0",
            "PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_PATH": "/missing/x.duckdb_extension",
            "PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_SHA256": "b" * 64,
            "PG_AGENT_DUCKDB_GRAMMAR_FEATURES": "pipe_query_syntax",
        })
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG_AGENT_DUCKDB_GRAMMAR_")}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            test_from_env_disabled({})
        test_config_errors()
        test_parse_features()
        test_disabled_bootstrap_order()
        test_enabled_bootstrap_order(tmp)
        test_hash_mismatch_closes(tmp)
        test_load_error_closes(tmp)
        test_bootstrap_error_wrapped()
        test_prompt_gating()
        test_native_marker(tmp)
    print("[grammar] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
