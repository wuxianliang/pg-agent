"""Import-safe Stage 41 registry gate, with no consumer or provider execution.

Run: UV_FROZEN=1 uv run python v13/registry/test_registry.py
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from unittest import mock

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
BASE = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
PHASE_D = "78e77c710bf06a0a1c771b822a3837c5db4c66d0"
CE_RUN_TIP = "cbf65cfc3e32cf82e51cafbb71162ac7649bd507"
CONTEXT_KEYS = frozenset(("schema_version", "scope_id", "revision", "tools_revision",
                          "services", "tool_profiles", "prompt_sections", "tools",
                          "unresolved", "context_hash"))
PROVENANCE = frozenset(("name", "scope_id", "registration_id", "valid_from_rev"))
TOOL_KEYS = frozenset(("name", "description", "kind", "handler", "param_spec", "enabled"))


def sql(conn, statement, args=()):
    """One statement, deliberately never commits the caller's transaction."""
    with conn.cursor() as cur:
        cur.execute(statement, args)
        return cur.fetchone()[0] if cur.description else None


def idle(conn):
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise RuntimeError("registry gate requires an IDLE connection")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setup_module():
    name = "registry_gate_setup"
    if name not in sys.modules:
        load_module(Path(__file__).with_name("setup_db.py"), name)
    return sys.modules[name]


def uid():
    return str(uuid.uuid4())


def register(conn, scope, kind, name, value, depends=()):
    return sql(conn, "SELECT public.v13_registry_register(%s::uuid,%s,%s,%s::jsonb,%s::text[])",
               (scope, kind, name, Json(value), None if depends is None else list(depends)))


def retire(conn, scope, kind, name):
    return sql(conn, "SELECT public.v13_registry_retire(%s::uuid,%s,%s)", (scope, kind, name))


def context(conn, scope, revision=None, actor=None, text=False):
    return sql(conn, "SELECT public.v13_registry_context(%s::uuid,%s::bigint,%s::uuid)"
               + ("::text" if text else ""), (scope, revision, actor))


def chain(conn, scope, actor=None):
    return sql(conn, "SELECT coalesce(jsonb_agg(jsonb_build_array(scope_id,depth) ORDER BY depth),'[]') "
               "FROM public.v13_scope_chain(%s::uuid,%s::uuid)", (scope, actor))


class Gate:
    def __init__(self, database):
        self.db, self.setup, self.checks = database, setup_module(), 0
        self.case_failures = []

    def check(self, label, condition, evidence=None):
        self.checks += 1
        if not condition:
            raise AssertionError(f"{label}: {evidence!r}")
        print(f"  ok {self.checks}: {label}", flush=True)

    @contextlib.contextmanager
    def case(self, label):
        try:
            yield
        except Exception as exc:
            self.case_failures.append((label, repr(exc)))
            print("  CASE FAIL", label, repr(exc), flush=True)
            traceback.print_exc()

    @contextlib.contextmanager
    def connection(self, alias="route"):
        conn = (self.setup.connect_owner_database(self.db) if alias in ("owner", "v13_resolve")
                else self.setup.connect_test_database(self.db, role=alias))
        try:
            idle(conn)
            if alias == "v13_resolve":
                # The frozen resolve group is NOLOGIN. Persist SET ROLE only
                # for this connection so error rollbacks retain the downgrade.
                sql(conn, "SET ROLE v13_resolve")
                conn.commit()
                idle(conn)
            yield conn
        finally:
            conn.close()

    def committed(self, func, *args, alias="route", **kwargs):
        with self.connection(alias) as conn:
            with conn:
                return func(conn, *args, **kwargs)

    def audit(self, statement, args=()):
        return self.committed(sql, statement, args, alias="owner")

    def scope(self, parent=None):
        with self.connection("owner") as conn:
            with conn:
                if parent is None:
                    return sql(conn, "SELECT public.v13_open_session('{}'::jsonb)")
                # Fixture only: fork columns are set at INSERT, never retrofitted.
                sql(conn, "SET LOCAL ROLE v13_spawn_owner")
                return sql(conn, "INSERT INTO public.sessions(parent_session_id,parent_cutoff_seq) "
                           "VALUES (%s::uuid,0) RETURNING session_id", (parent,))

    def reg(self, scope, name, kind="service", value=None, depends=()):
        if value is None:
            value = {"provides": ["registry_fake_capability"]} if kind == "service" else {}
        result = self.committed(register, scope, kind, name, value, depends)
        self.check("successful registration " + name, result.get("ok") is True, result)
        return result

    def clock(self):
        return self.audit("SELECT revision FROM public.v13_registry_clock WHERE singleton")

    def fingerprint(self):
        return self.audit("SELECT jsonb_build_array("
                          "(SELECT jsonb_agg(to_jsonb(c)) FROM v13_registry_clock c),"
                          "(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY scope_id),'[]') FROM v13_registry_meta m),"
                          "(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY registration_id),'[]') FROM v13_registrations r),"
                          "(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY session_id,seq),'[]') FROM events e),"
                          "(SELECT jsonb_agg(to_jsonb(s) ORDER BY session_id) FROM sessions s))")

    def denied(self, conn, statement, args=(), code="42501", message=None):
        try:
            sql(conn, statement, args)
        except psycopg2.Error as exc:
            conn.rollback()
            self.check("SQL rejected at expected boundary", exc.pgcode == code
                       and (message is None or message in str(exc)), (exc.pgcode, str(exc)))
        else:
            conn.rollback()
            self.check("SQL must be rejected", False, statement)

    def hash_ok(self, result):
        self.check("context exact ten-key shape", set(result) == CONTEXT_KEYS, result)
        actual = self.audit("SELECT encode(digest((%s::jsonb - 'context_hash')::text,'sha256'),'hex')", (Json(result),))
        self.check("hash includes entire remaining object", actual == result["context_hash"])


class ThreadCall:
    """Explicit entry/result/commit barriers; exceptions are re-raised on join."""
    def __init__(self, connect, action, hold_commit=False):
        self.entered, self.finished, self.release = threading.Event(), threading.Event(), threading.Event()
        self.committed = threading.Event()
        self.result = self.error = self.pid = None
        self.hold_commit = hold_commit
        self.connect, self.action = connect, action
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        conn = None
        try:
            conn = self.connect()
            self.pid = conn.get_backend_pid()
            self.entered.set()
            with conn:
                sql(conn, "SET LOCAL statement_timeout='15s'")
                self.result = self.action(conn)
                self.finished.set()
                if self.hold_commit and not self.release.wait(10):
                    raise TimeoutError("commit barrier not released")
            self.committed.set()
        except BaseException as exc:
            self.error = exc
            self.finished.set()
        finally:
            if conn is not None:
                conn.close()

    def __enter__(self):
        self.thread.start()
        if not self.entered.wait(10):
            raise TimeoutError("thread did not enter")
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(20)
        if self.thread.is_alive():
            raise TimeoutError("database thread leaked")
        if self.error is not None and exc[0] is None:
            raise self.error


def wait_blocked(g, call, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if g.audit("SELECT %s=ANY(pg_blocking_pids(%s))", (blocker, call.pid)):
            g.check("second connection really waits on first transaction", not call.finished.is_set())
            return
        if call.finished.is_set():
            raise AssertionError(f"expected real lock wait: {call.result!r}, {call.error!r}")
    raise TimeoutError("did not observe PostgreSQL lock barrier")


def native_load_untouched(g):
    g.check("real before/after snapshots captured", g.db.before is not None and g.db.after is not None)
    g.setup.validate_stage41_prefix(g.db.before, g.db.prefix)
    g.check("Stage 41 prefix snapshot captured", g.db.prefix is not None)
    g.check("exact eight Stage 41 functions", len(g.setup._registry_function_rows(g.db.prefix, g.db.before)) == 8)
    g.check("Stage 41 prefix bytes pinned", g.setup._registry_sql_parts()[0].encode()
            and hashlib.sha256(g.setup._registry_sql_parts()[0].encode()).hexdigest()
            == g.setup.STAGE41_PREFIX_SHA256)
    load = load_module(ROOT / "load.py", "registry_gate_load")
    g.check("loader Stage 41 exact tail", len(load.SQL_LOAD_ORDER) == 41
            and load.STAGE_THROUGH["registry"] == 41 and load.STAGE_THROUGH["ce_run"] == 40
            and [p.name for p in load.SQL_LOAD_ORDER[-2:]] == ["v13_ce_run.sql", "v13_registry.sql"])
    for path in load.SQL_LOAD_ORDER[:39]:
        rel = str(path.relative_to(REPO))
        rev = PHASE_D if "fair_claim/" in rel else BASE
        original = subprocess.check_output(["git", "show", f"{rev}:{rel}"], cwd=REPO)
        if rel == "v13/plan_arm/v13_plan_arm.sql":
            with g.case("plan_arm baseline restoration and protected scope"):
                load_module(ROOT / "plan_arm/test_plan_arm.py", "registry_gate_r0").r0_source_scope()
                g.check("plan_arm sentinel restores baseline bytes", True)
        else:
            g.check("frozen SQL bytes " + rel, path.read_bytes() == original)
    for filename in ("v13_ce_run.sql", "setup_db.py", "README.md"):
        rel = "v13/ce_run/" + filename
        original = subprocess.check_output(["git", "show", f"{CE_RUN_TIP}:{rel}"], cwd=REPO)
        g.check("CE milestone byte pin " + filename, (REPO / rel).read_bytes() == original)
    rel = "v13/ce_run/test_ce_run.py"
    original = subprocess.check_output(["git", "show", f"{CE_RUN_TIP}:{rel}"], cwd=REPO).decode()
    current = (REPO / rel).read_text()

    def tail_range(source):
        function = next(n for n in ast.parse(source).body
                        if isinstance(n, ast.FunctionDef) and n.name == "native_load_untouched")
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "check"
                 and n.args and isinstance(n.args[0], ast.Constant)
                 and str(n.args[0].value).startswith("loader tail exactly")]
        assert len(calls) == 1
        return calls[0].lineno, calls[0].end_lineno

    old_range, new_range = tail_range(original), tail_range(current)
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff", "--no-textconv", "--unified=0",
                                    CE_RUN_TIP, "--", rel], cwd=REPO).decode()
    for old, old_count, new, new_count in re.findall(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        for start, count, bounds in ((int(old), int(old_count or 1), old_range),
                                     (int(new), int(new_count or 1), new_range)):
            g.check("CE test diff hunk confined to loader-tail assertion",
                    count > 0 and bounds[0] <= start <= start + count - 1 <= bounds[1], diff)
    without = lambda text, bounds: text.splitlines(keepends=True)[:bounds[0] - 1] + text.splitlines(keepends=True)[bounds[1]:]
    g.check("CE test outside loader-tail call byte frozen", without(original, old_range) == without(current, new_range))
    g.check("registry has no CE cross-reference", "v13_ce_" not in Path(__file__).with_name("v13_registry.sql").read_text())
    g.setup.validate_deployment_restrictions(g.db.server, g.db.name, g.db.roles)


def native_plan_arm_closed_set(g):
    plan = load_module(ROOT / "plan_arm/test_plan_arm.py", "registry_gate_plan_arm")
    files = {p.name for p in Path(__file__).parent.iterdir()
             if p.is_file() and p.suffix in (".py", ".sql", ".md")}
    g.check("registry exact source files", files == {
        "v13_registry.sql", "setup_db.py", "test_registry.py", "test_consumer.py", "README.md"
    }, files)
    # Executes real closure plus missing/extra/future-tail/malformed/duplicate/
    # skipped-stage and fresh-file subtraction negative mutations.
    plan.r1_phase_d_prefix_allowance()
    g.check("real plan_arm closure and all synthetic negatives pass", True)
    plan.r0_source_scope()
    g.check("protected source closed set remains frozen", True)


@contextlib.contextmanager
def event_order_fixture(conn):
    """Observe event/meta/clock before row write, without production changes."""
    sql(conn, """
      CREATE FUNCTION public.registry_gate_event_order() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE rev bigint; typ text;
      BEGIN
        rev := CASE WHEN TG_OP='INSERT' THEN NEW.valid_from_rev ELSE NEW.valid_to_rev END;
        typ := CASE WHEN TG_OP='INSERT' THEN 'registry/registered' ELSE 'registry/retired' END;
        IF NOT EXISTS (SELECT 1 FROM public.events WHERE session_id=NEW.scope_id
             AND type=typ AND payload->>'registration_id'=NEW.registration_id::text
             AND (payload->>'revision')::bigint=rev)
           OR (SELECT revision FROM public.v13_registry_clock WHERE singleton) IS DISTINCT FROM rev
           OR (SELECT revision FROM public.v13_registry_meta WHERE scope_id=NEW.scope_id) IS DISTINCT FROM rev THEN
          RAISE EXCEPTION 'registry gate: row preceded event/clock/meta';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER registry_gate_event_order BEFORE INSERT OR UPDATE ON public.v13_registrations
      FOR EACH ROW EXECUTE FUNCTION public.registry_gate_event_order();
    """)
    # On failure, the caller's transaction rolls back the fixture as well.
    # Do not issue cleanup SQL in an aborted transaction and mask that failure.
    yield
    sql(conn, "DROP TRIGGER registry_gate_event_order ON public.v13_registrations; "
              "DROP FUNCTION public.registry_gate_event_order()")


def native_register_happy(g):
    scope = g.scope()
    g.check("meta absent before first write", g.audit("SELECT count(*) FROM v13_registry_meta WHERE scope_id=%s", (scope,)) == 0)
    clock = g.clock()
    with g.connection("owner") as conn:
        with conn:
            with event_order_fixture(conn):
                kinds = (("service", {"schema_version": 1, "provides": ["not_a_pg_proc"], "config": {}}),
                         ("tool_profile", {"handlers": ["fake"], "interruptible": "required"}),
                         ("prompt_section", {"text": "fake"}))
                for offset, (kind, value) in enumerate(kinds, 1):
                    result = register(conn, scope, kind, kind, value)
                    g.check("success exact four keys " + kind, set(result) == {"schema_version", "ok", "registration_id", "revision"}
                            and result["schema_version"] == 1 and result["ok"] is True and result["revision"] == clock + offset, result)
                    g.check("event-before-row and allocated identity " + kind, sql(conn,
                        "SELECT r.valid_from_rev=(e.payload->>'revision')::bigint AND r.scope_id=e.session_id "
                        "FROM v13_registrations r JOIN events e ON e.payload->>'registration_id'=r.registration_id::text "
                        "WHERE r.registration_id=%s", (result["registration_id"],)))
    g.check("meta equals last touched global revision", g.audit("SELECT revision FROM v13_registry_meta WHERE scope_id=%s", (scope,)) == clock + 3)
    g.check("diagnostics reconcile with registry event max", g.audit(
        "SELECT NOT EXISTS (SELECT 1 FROM v13_registry_meta m FULL JOIN "
        "(SELECT session_id,max((payload->>'revision')::bigint) AS revision FROM events "
        "WHERE type IN ('registry/registered','registry/retired') GROUP BY session_id) e "
        "ON e.session_id=m.scope_id WHERE m.revision IS DISTINCT FROM e.revision)"))


def native_retire_no_gap(g):
    scope = g.scope()
    with g.connection("owner") as conn:
        with conn:
            with event_order_fixture(conn):
                a = register(conn, scope, "service", "transient", {"provides": ["fake"]})
                b = retire(conn, scope, "service", "transient")
                g.check("same transaction register/retire consecutive revisions", b["ok"]
                        and b["registration_id"] == a["registration_id"] and b["revision"] == a["revision"] + 1)
                g.check("strict nonempty half-open interval", sql(conn,
                    "SELECT valid_from_rev=%s AND valid_to_rev=%s AND valid_to_rev>valid_from_rev "
                    "FROM v13_registrations WHERE registration_id=%s", (a["revision"], b["revision"], a["registration_id"])))
                g.check("two ordered events without revision gap", sql(conn,
                    "SELECT jsonb_agg(jsonb_build_array(type,(payload->>'revision')::bigint) ORDER BY seq) "
                    "FROM events WHERE session_id=%s", (scope,)) == [["registry/registered", a["revision"]], ["registry/retired", b["revision"]]])
                g.check("visible at from, invisible at to", len(context(conn, scope, a["revision"])["services"]) == 1
                        and context(conn, scope, b["revision"])["services"] == [])


def native_already_live_not_live(g):
    scope, empty = g.scope(), g.scope()
    result = g.reg(scope, "once")
    before = g.fingerprint()
    for _ in range(2):
        actual = g.committed(register, scope, "service", "once", {"provides": ["different"]})
        g.check("already_live returns exact existing identity", actual == {
            "schema_version": 1, "ok": False, "reason": "already_live",
            "registration_id": result["registration_id"], "valid_from_rev": result["revision"]})
        for sid in (scope, empty):
            g.check("not_live exact three keys", g.committed(retire, sid, "service", "missing")
                    == {"schema_version": 1, "ok": False, "reason": "not_live"})
        g.check("conflicts preserve clock/meta/rows/events/session counters", g.fingerprint() == before)
    g.committed(retire, scope, "service", "once")
    before = g.fingerprint()
    for _ in range(2):
        g.check("retirement replay is not_live", g.committed(retire, scope, "service", "once")
                == {"schema_version": 1, "ok": False, "reason": "not_live"})
    g.check("retirement replay is zero-write", g.fingerprint() == before)


def native_frozen_matrix(g):
    scope, other = g.scope(), g.scope()
    rid = g.reg(scope, "frozen")["registration_id"]
    changes = {"registration_id": "gen_random_uuid()", "scope_id": f"'{other}'::uuid",
               "kind": "'prompt_section'", "name": "'renamed'", "value": "'{}'::jsonb",
               "depends_on": "ARRAY['changed']", "valid_from_rev": "valid_from_rev+1",
               "created_at": "created_at+interval '1 second'"}
    for column, expr in changes.items():
        with g.case(column), g.connection("owner") as conn:
            g.denied(conn, f"UPDATE v13_registrations SET {column}={expr} WHERE registration_id=%s", (rid,), "P0001", "immutable")
    with g.connection("owner") as conn:
        g.denied(conn, "DELETE FROM v13_registrations WHERE registration_id=%s", (rid,), "P0001", "no DELETE")
        g.denied(conn, "UPDATE v13_registrations SET valid_to_rev=NULL WHERE registration_id=%s", (rid,), "P0001", "only permitted update")
        g.denied(conn, "UPDATE v13_registrations SET valid_to_rev=valid_from_rev WHERE registration_id=%s", (rid,), "23514")
    for alias in ("route", "recall", "worker", "plain", "v13_resolve"):
        with g.case("direct retirement " + alias), g.connection(alias) as conn:
            g.denied(conn, "UPDATE v13_registrations SET valid_to_rev=valid_from_rev+1 WHERE registration_id=%s", (rid,))
    with g.connection("owner") as conn:
        sql(conn, "UPDATE v13_registrations SET valid_to_rev=valid_from_rev+1 WHERE registration_id=%s", (rid,))
        g.check("only owner operational direct retirement works", sql(conn,
            "SELECT valid_to_rev=valid_from_rev+1 FROM v13_registrations WHERE registration_id=%s", (rid,)))
        conn.commit()
        for expr in ("NULL", "valid_to_rev", "valid_to_rev+1"):
            g.denied(conn, f"UPDATE v13_registrations SET valid_to_rev={expr} WHERE registration_id=%s", (rid,), "P0001", "only permitted update")


def native_one_live_concurrency(g):
    scope = g.scope()
    before = g.clock()
    with g.connection() as first:
        winner = register(first, scope, "service", "concurrent", {"provides": ["fake"]})
        with ThreadCall(lambda: g.setup.connect_route(g.db), lambda c: register(
                c, scope, "service", "concurrent", {"provides": ["fake"]})) as other:
            wait_blocked(g, other, first.get_backend_pid())
            first.commit()
        g.check("one committed winner and one already_live", winner["ok"] and other.committed.is_set()
                and other.result == {"schema_version": 1, "ok": False, "reason": "already_live",
                                     "registration_id": winner["registration_id"], "valid_from_rev": winner["revision"]})
    g.check("race allocates only one revision and one live row", g.clock() == before + 1
            and g.audit("SELECT count(*) FROM v13_registrations WHERE scope_id=%s AND valid_to_rev IS NULL", (scope,)) == 1)
    with g.connection("owner") as conn:
        g.denied(conn, "INSERT INTO v13_registrations(scope_id,kind,name,value,valid_from_rev) "
                 "VALUES (%s,'service','concurrent','{}',%s)", (scope, winner["revision"] + 1), "23505", "ux_v13_registrations_one_live")


def native_chain(g):
    root = g.scope()
    parent = g.scope(root)
    leaf = g.scope(parent)
    g.check("root includes self", g.committed(chain, root) == [[root, 0]])
    g.check("leaf to root depth order", g.committed(chain, leaf) == [[leaf, 0], [parent, 1], [root, 2]])
    ancestry = [root]
    for _ in range(32):
        ancestry.append(g.scope(ancestry[-1]))
    g.check("33-node chain truncates to depths 0..31", g.committed(chain, ancestry[-1])
            == [[sid, i] for i, sid in enumerate(reversed(ancestry[1:]))])
    g.check("exact 32-node chain complete", g.committed(chain, ancestry[-2])
            == [[sid, i] for i, sid in enumerate(reversed(ancestry[:-1]))])
    definition = g.audit("SELECT pg_get_functiondef('v13_registry_chain_inner(uuid)'::regprocedure)")
    g.check("defensive path-array cycle guard present", "ARRAY[s.session_id]" in definition
            and "child.path || parent.session_id" in definition and "NOT (parent.session_id = ANY(child.path))" in definition)
    g.check("unknown scope chain empty", g.committed(chain, uid()) == [])


def native_context_determinism(g):
    root = g.scope()
    child = g.scope(root)
    inherited = g.reg(root, "shared")
    for name in ("zeta", "alpha", "middle"):
        g.reg(child, name)
    chosen = g.reg(child, "shared", value={"provides": ["nearer"]}, depends=("zeta", "alpha"))
    for name in ("z_profile", "a_profile"):
        g.reg(root, name, "tool_profile", {"interruptible": "unsupported"})
    for name in ("z_section", "a_section"):
        g.reg(root, name, "prompt_section", {"name": "forged", "scope_id": "forged",
              "registration_id": "forged", "valid_from_rev": -1, "text": "fixture"})
    revision = g.clock()
    with g.connection() as a, g.connection("recall") as b:
        left, right = context(a, child, revision, text=True), context(b, child, revision, text=True)
        g.check("independent role connections byte-identical at pinned revision", left == right)
    result = g.committed(context, child, revision)
    g.hash_ok(result)
    for key in ("services", "tool_profiles", "prompt_sections", "tools", "unresolved"):
        names = [entry["name"] for entry in result[key]]
        g.check("ordered by name " + key, names == sorted(names))
    shared = next(x for x in result["services"] if x["name"] == "shared")
    g.check("near scope shadows ancestor and dependencies sorted", shared["registration_id"] == chosen["registration_id"]
            and shared["registration_id"] != inherited["registration_id"] and shared["depends_on"] == ["alpha", "zeta"])
    for key, contents in (("services", {"provides", "depends_on"}),
                          ("tool_profiles", {"interruptible"}), ("prompt_sections", {"text"})):
        for entry in result[key]:
            g.check("entry keys and authoritative provenance " + key, set(entry) == PROVENANCE | contents
                    and entry["scope_id"] in (root, child) and entry["valid_from_rev"] > 0
                    and entry["registration_id"] != "forged" and entry["name"] != "forged")
    g.reg(root, "later_ancestor")
    g.check("post-pin ancestor write cannot change old child bytes", g.committed(context, child, revision, text=True) == left)
    live = g.committed(context, child)
    g.check("live child sees new ancestor and global clock", "later_ancestor" in [x["name"] for x in live["services"]]
            and live["revision"] == g.clock())
    with g.connection("owner") as conn:
        sql(conn, "DELETE FROM v13_registry_meta WHERE scope_id IN (%s,%s)", (root, child))
        g.check("reads ignore missing diagnostic metadata", context(conn, child, revision, text=True) == left)
        conn.rollback()


def native_as_of_boundaries(g):
    scope = g.scope()
    a = g.reg(scope, "bounded")
    g.reg(g.scope(), "global_intermediate")
    b = g.committed(retire, scope, "service", "bounded")
    for rev, visible in ((a["revision"] - 1, False), (a["revision"], True), (b["revision"] - 1, True), (b["revision"], False)):
        result = g.committed(context, scope, rev)
        g.check("half-open visibility at " + str(rev), bool(result["services"]) == visible and result["revision"] == rev)
    zero, current = g.committed(context, scope, 0), g.committed(context, scope)
    g.check("revision zero only empties registry arrays", zero["revision"] == 0 and zero["scope_id"] == scope
            and all(zero[k] == [] for k in ("services", "tool_profiles", "prompt_sections", "unresolved"))
            and zero["tools"] == current["tools"] and zero["tools_revision"] == current["tools_revision"])
    g.check("future revision clamps byte-identically to current", g.committed(context, scope, g.clock() + 10000, text=True)
            == g.committed(context, scope, text=True))
    with g.connection() as conn:
        for sid in (scope, uid()):
            g.denied(conn, "SELECT v13_registry_context(%s,-1,NULL)", (sid,), "P0001", "revision must be non-negative")
    g.hash_ok(zero)


def native_unresolved(g):
    scope = g.scope()
    g.reg(scope, "A", depends=("B",))
    g.reg(scope, "B", depends=("C",))
    result = g.committed(context, scope)
    g.check("transitive missing dependency is diagnostic, not an exception", result["services"] == []
            and result["unresolved"] == [{"name": "A", "missing": ["B"]}, {"name": "B", "missing": ["C"]}])
    rows = g.audit("SELECT jsonb_agg(to_jsonb(r) ORDER BY name) FROM v13_registrations r WHERE scope_id=%s", (scope,))
    g.hash_ok(result)
    changed = dict(result, unresolved=[])
    g.check("changing only unresolved changes hash preimage", g.audit(
        "SELECT encode(digest((%s::jsonb-'context_hash')::text,'sha256'),'hex')", (Json(changed),)) != result["context_hash"])
    g.reg(scope, "C")
    resolved = g.committed(context, scope)
    g.check("dependency completion resolves transitive closure", resolved["unresolved"] == []
            and [x["name"] for x in resolved["services"]] == ["A", "B", "C"])
    g.check("original live A/B rows unchanged while diagnostic resolves", g.audit(
        "SELECT jsonb_agg(to_jsonb(r) ORDER BY name) FROM v13_registrations r WHERE scope_id=%s AND name IN ('A','B')", (scope,)) == rows
            and resolved["context_hash"] != result["context_hash"])
    cyclic = g.scope()
    g.reg(cyclic, "A", depends=("B",))
    g.reg(cyclic, "B", depends=("A",))
    result = g.committed(context, cyclic)
    g.check("cycle never enters add-only resolved set", result["services"] == []
            and result["unresolved"] == [{"name": "A", "missing": ["B"]}, {"name": "B", "missing": ["A"]}])
    unordered = g.scope()
    g.reg(unordered, "orphan", depends=("z_missing", "a_missing"))
    g.check("unresolved exact keys and sorted missing names", g.committed(context, unordered)["unresolved"]
            == [{"name": "orphan", "missing": ["a_missing", "z_missing"]}])
    g.hash_ok(result)


def native_value_shape(g):
    scope = g.scope()
    cases = []
    for value in (None, [], "text", 1, True):
        cases.append(("object required", scope, "service", "bad", value, ()))
    for value in ({}, {"provides": None}, {"provides": "x"}, {"provides": []},
                  {"provides": ["x"] * 65}, {"provides": ["x", "x"]}, {"provides": [1]},
                  {"provides": [""]}, {"provides": ["1bad"]}, {"provides": ["bad-name"]},
                  {"provides": ["x" * 64]}, {"provides": ["x"], "config": []},
                  {"provides": ["x"], "config": None}, {"provides": ["x"], "extra": 1},
                  {"provides": ["x"], "schema_version": 2}, {"provides": ["x"], "schema_version": "1"},
                  {"provides": ["x"], "schema_version": None}):
        cases.append(("service shape", scope, "service", "bad", value, ()))
    for value in ({}, {"extra": 1}, {"schema_version": 1}, {"handlers": None}, {"handlers": "x"},
                  {"handlers": []}, {"handlers": ["x"] * 65}, {"handlers": ["x", "x"]},
                  {"handlers": [1]}, {"handlers": [""]}, {"handlers": ["x" * 129]},
                  {"interruptible": None}, {"interruptible": 1}, {"interruptible": "unknown"},
                  {"handlers": ["x"], "extra": 1}):
        cases.append(("profile shape", scope, "tool_profile", "bad", value, ()))
    good = {"provides": ["x"]}
    for deps in (None, (None,), ("",), ("  ",), ("x" * 129,), ("x", "x"), tuple(f"d{i}" for i in range(65))):
        cases.append(("dependency shape", scope, "service", "bad", good, deps))
    for kind in ("tool_profile", "prompt_section"):
        cases.append(("non-service dependencies", scope, kind, "bad",
                      {"handlers": ["x"]} if kind == "tool_profile" else {}, ("x",)))
    for name in (None, "", "  ", "x" * 129, "\u4e2d" * 43):
        cases.append(("name validation", scope, "service", name, good, ()))
    for kind in (None, "hook", "policy", "SERVICE"):
        cases.append(("closed kind set", scope, kind, "bad", good, ()))
    for sid in (None, uid()):
        cases.append(("unknown scope", sid, "service", "bad", good, ()))
    cases.append(("1 MiB bound", scope, "prompt_section", "oversize", {"text": "x" * 1048576}, ()))
    before = g.fingerprint()
    for index, (label, sid, kind, name, value, deps) in enumerate(cases):
        with g.case(f"{label} {index}"), g.connection() as conn:
            g.denied(conn, "SELECT v13_registry_register(%s::uuid,%s,%s,%s::jsonb,%s::text[])",
                     (sid, kind, name, Json(value), None if deps is None else list(deps)), "P0001")
            g.check("invalid register leaves all state unchanged", g.fingerprint() == before)
    for sid, kind, name in ((uid(), "service", "x"), (None, "service", "x"),
                            (scope, None, "x"), (scope, "hook", "x"),
                            (scope, "service", ""), (scope, "service", "x" * 129)):
        with g.case("retire validation"), g.connection() as conn:
            g.denied(conn, "SELECT v13_registry_retire(%s::uuid,%s,%s)", (sid, kind, name), "P0001")
            g.check("invalid retire leaves all state unchanged", g.fingerprint() == before)
    g.reg(scope, "max_provides", value={"provides": [f"cap_{i}" for i in range(64)]})
    g.reg(scope, "max_deps", depends=tuple(f"dep{i}" for i in range(64)))
    g.reg(scope, "open_prompt", "prompt_section", {"arbitrary": [1, None, {"nested": True}]})
    for mode in ("required", "best_effort", "unsupported"):
        g.reg(scope, mode, "tool_profile", {"interruptible": mode})
    g.reg(scope, "max_handlers", "tool_profile", {"handlers": [f"handler{i}" for i in range(64)]})


def native_acl_roles(g):
    root = g.scope()
    parent = g.scope(root)
    scope, sibling, stranger, empty = g.scope(parent), g.scope(parent), g.scope(), g.scope()
    g.reg(scope, "acl")
    read_sql = "SELECT public.v13_registry_context(%s,NULL,NULL)"
    write_sql = "SELECT public.v13_registry_register(%s,'service','acl_new','{\"provides\":[\"x\"]}',ARRAY[]::text[])"
    retire_sql = "SELECT public.v13_registry_retire(%s,'service','acl')"
    for alias in ("route", "recall", "worker", "plain", "v13_resolve"):
        with g.case("ACL " + alias), g.connection(alias) as conn:
            if alias == "route":
                with conn:
                    g.check("route writes through definer", sql(conn, write_sql, (scope,))["ok"])
                    g.check("route retires through definer", sql(conn, retire_sql, (scope,))["ok"])
            else:
                g.denied(conn, write_sql, (scope,))
                g.denied(conn, retire_sql, (scope,))
            if alias in ("route", "recall"):
                g.check("operator NULL-actor role arm reads", sql(conn, read_sql, (scope,))["scope_id"] == scope)
                g.check("operator reads chain", chain(conn, scope) == [[scope, 0], [parent, 1], [root, 2]])
                conn.rollback()
            else:
                g.denied(conn, read_sql, (scope,))
                g.denied(conn, "SELECT * FROM v13_scope_chain(%s,NULL)", (scope,))
            for table in ("v13_registrations", "v13_registry_meta", "v13_registry_clock"):
                if alias in ("route", "recall") and table != "v13_registry_clock":
                    sql(conn, f"SELECT count(*) FROM {table}")
                    conn.rollback()
                    g.check("allowed SELECT " + alias + "/" + table, True)
                else:
                    g.denied(conn, f"SELECT count(*) FROM {table}")
                for statement in (f"INSERT INTO {table} DEFAULT VALUES", f"DELETE FROM {table} WHERE false",
                                  f"UPDATE {table} SET " + ("name=name" if table == "v13_registrations" else "revision=revision") + " WHERE false",
                                  f"TRUNCATE {table}"):
                    g.denied(conn, statement)
    with g.connection("v13_resolve") as conn:
        for statement in ("SELECT v13_registrations_frozen()", "SELECT v13_registry_caller_role()",
                          "SELECT v13_registry_read_ok(NULL,NULL)", "SELECT * FROM v13_registry_chain_inner(NULL)",
                          "SELECT v13_registry_register(NULL,NULL,NULL,NULL,NULL)",
                          "SELECT v13_registry_retire(NULL,NULL,NULL)", "SELECT * FROM v13_scope_chain(NULL,NULL)",
                          "SELECT v13_registry_context(NULL,NULL,NULL)"):
            g.denied(conn, statement)
    canonical = g.committed(context, uid())
    g.hash_ok(canonical)
    g.check("canonical empty exact values", canonical == {
        "schema_version": 1, "scope_id": None, "revision": 0, "tools_revision": 0,
        "services": [], "tool_profiles": [], "prompt_sections": [], "tools": [], "unresolved": [],
        "context_hash": canonical["context_hash"]})
    for actor in (scope, parent):
        g.check("self/direct parent read", g.committed(context, scope, actor=actor)["scope_id"] == scope
                and g.committed(chain, scope, actor) == [[scope, 0], [parent, 1], [root, 2]])
    for actor in (root, sibling, stranger, uid()):
        g.check("grandparent/sibling/stranger/unknown actor fail closed", g.committed(context, scope, actor=actor) == canonical
                and g.committed(chain, scope, actor) == [])
    known = g.committed(context, empty)
    g.hash_ok(known)
    expected = {"scope_id": empty, "revision": g.clock(),
                "tools_revision": g.audit("SELECT revision FROM v13_tools_meta WHERE singleton"),
                "tools": g.audit("SELECT coalesce(jsonb_agg(jsonb_build_object('name',name,'description',description,"
                                 "'kind',kind,'handler',handler,'param_spec',param_spec,'enabled',enabled) ORDER BY name),'[]') FROM tools")}
    for key in CONTEXT_KEYS:
        if key == "context_hash":
            g.check("known-empty hash differs from canonical", known[key] != canonical[key])
        else:
            g.check("known empty vs canonical key " + key, known[key] == expected.get(key, canonical[key]))
    # Temporary EXECUTE grants isolate internal authorization from normal ACLs.
    # Transaction rollback removes every grant and any test write.
    with g.connection("owner") as conn:
        role = g.db.roles["plain"]
        sql(conn, f'GRANT EXECUTE ON FUNCTION v13_registry_context(uuid,bigint,uuid), '
                  f'v13_scope_chain(uuid,uuid), v13_registry_register(uuid,text,text,jsonb,text[]), '
                  f'v13_registry_retire(uuid,text,text) TO "{role}"')
        sql(conn, f'SET LOCAL ROLE "{role}"')
        g.check("SET ROLE downgrade ignores superuser session identity", context(conn, scope) == canonical and chain(conn, scope) == [])
        for actor in (scope, parent):
            g.check("non-NULL actor does not consult caller role", context(conn, scope, actor=actor)["scope_id"] == scope
                    and len(chain(conn, scope, actor)) == 3)
        for statement in (write_sql, retire_sql):
            sql(conn, "SAVEPOINT internal_caller")
            try:
                sql(conn, statement, (scope,))
            except psycopg2.Error as exc:
                sql(conn, "ROLLBACK TO SAVEPOINT internal_caller")
                g.check("write caller check fail-closed behind EXECUTE", exc.pgcode == "P0001" and "caller may not" in str(exc))
            else:
                g.check("downgraded caller must not write", False)
        conn.rollback()


def native_events_and_probe(g):
    scope = g.scope()
    before = g.audit("SELECT v13_probe(%s)", (scope,))
    result = g.reg(scope, "event")
    middle = g.audit("SELECT v13_probe(%s)", (scope,))
    retired = g.committed(retire, scope, "service", "event")
    after = g.audit("SELECT v13_probe(%s)", (scope,))
    for left, right in ((before, middle), (middle, after)):
        g.check("registry events intentionally advance stale fences",
                right["session_version"] > left["session_version"] and right["max_event_seq"] > left["max_event_seq"])
        g.check("global registry revision advances", right["registry_revision"] > left["registry_revision"])
        g.check("other probe keys unchanged", {k: v for k, v in left.items()
                if k not in ("session_version", "max_event_seq", "registry_revision")}
                == {k: v for k, v in right.items()
                    if k not in ("session_version", "max_event_seq", "registry_revision")})
    events = g.audit("SELECT jsonb_agg(jsonb_build_object('session',session_id,'type',type,'payload',payload,"
                     "'source',source_effect_id) ORDER BY seq) FROM events WHERE session_id=%s", (scope,))
    g.check("exact two registry events", len(events) == 2)
    for event, typ, write in zip(events, ("registry/registered", "registry/retired"), (result, retired)):
        g.check("event type/scope/NULL source and exact payload", event == {
            "session": scope, "type": typ, "source": None,
            "payload": {"schema_version": 1, "registration_id": result["registration_id"],
                        "kind": "service", "name": "event", "revision": write["revision"]}})


def native_static_setup(g):
    for alias in ("route", "recall", "worker", "plain"):
        with contextlib.closing(getattr(g.setup, "connect_" + alias)(g.db.name, server=g.db.server)) as conn:
            idle(conn)
            g.check("string wrapper uses temporary " + alias + " identity", sql(conn,
                "SELECT ARRAY[session_user::text, current_user::text]") == [g.db.roles[alias]] * 2)
    with contextlib.closing(g.setup.connect_test_database(g.db.name, server=g.db.server)) as conn:
        idle(conn)
        g.check("string default uses temporary route identity", sql(conn,
            "SELECT ARRAY[session_user::text, current_user::text]") == [g.db.roles["route"]] * 2)
    with contextlib.closing(g.setup.connect_owner_database(g.db)) as conn:
        idle(conn)
        owner_identity = sql(conn, "SELECT ARRAY[session_user::text, current_user::text]")
    with contextlib.closing(g.setup.connect_test_database(g.db.name, server=g.db.server, role=None)) as conn:
        idle(conn)
        g.check("string None uses URI owner identity", sql(conn,
            "SELECT ARRAY[session_user::text, current_user::text]") == owner_identity)
    with contextlib.closing(g.setup.connect_test_database(g.db.name, server=g.db.server,
                                                        role=g.db.roles["plain"])) as conn:
        idle(conn)
        g.check("string explicit role passes through unchanged", sql(conn,
            "SELECT ARRAY[session_user::text, current_user::text]") == [g.db.roles["plain"]] * 2)
    try:
        with contextlib.closing(g.setup.connect_test_database(g.db.name)):
            g.check("string connection must require server", False)
    except ValueError as exc:
        g.check("string missing server retains exact error", str(exc) == "server is required when database is a name")
    source = Path(__file__).read_text()
    setup_source = Path(__file__).with_name("setup_db.py").read_text()
    for text in (source, setup_source):
        tree = ast.parse(text)
        g.check("no external network/provider imports", not any(isinstance(n, (ast.Import, ast.ImportFrom))
                and any(word in ast.unparse(n) for word in ("socket", "requests", "httpx", "openai", "DeepSeekProvider"))
                for n in ast.walk(tree)))
        g.check("no SQL sleep or Python sleep calls", "pg_" + "sleep" not in text
                and not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "sleep" for n in ast.walk(tree)))
    with mock.patch.object(psycopg2, "connect", side_effect=AssertionError("import connected")), \
            mock.patch.object(subprocess, "run", side_effect=AssertionError("import subprocess")), \
            mock.patch.object(subprocess, "check_output", side_effect=AssertionError("import subprocess")), \
            mock.patch.object(threading.Thread, "start", side_effect=AssertionError("import thread")):
        load_module(Path(__file__), "registry_gate_import_safe")
        load_module(Path(__file__).with_name("setup_db.py"), "registry_gate_setup_import_safe")
    g.check("both imports have zero DB/subprocess/thread side effects", True)
    with mock.patch.object(g.setup, "_new_name", return_value=g.db.name):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("same name refused with original OID intact", "exists" in str(exc)
                    and g.setup._database_oid(g.db.server, g.db.name) == g.db.oid)
        else:
            g.check("same-name create must fail", False)
    real_run = g.setup.run_psql

    def fail_create(server, name, statement, **kwargs):
        if statement.startswith('CREATE DATABASE '):
            raise RuntimeError("registry_gate_create_failure")
        return real_run(server, name, statement, **kwargs)

    with mock.patch.object(g.setup, "run_psql", side_effect=fail_create), \
            mock.patch.object(g.setup, "_drop_database_exact", side_effect=AssertionError("failed CREATE attempted DROP")):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("failed CREATE never deletes unknown database", str(exc) == "registry_gate_create_failure")
        else:
            g.check("injected CREATE failure must propagate", False)
    with mock.patch.object(g.setup, "run_psql", side_effect=AssertionError("OID mismatch attempted DROP")):
        try:
            g.setup._drop_database_exact(g.db.server, g.db.name, g.db.oid + 1)
        except RuntimeError as exc:
            g.check("database OID mismatch refuses deletion", "OID changed" in str(exc))
        else:
            g.check("OID mismatch must fail", False)
        try:
            g.setup._drop_role_exact(g.db.server, g.db.roles["plain"], g.db.role_oids["plain"] + 1)
        except RuntimeError as exc:
            g.check("role OID mismatch refuses deletion", "OID changed" in str(exc))
        else:
            g.check("role OID mismatch must fail", False)
    original = RuntimeError("registry_gate_original_failure")
    with mock.patch.object(g.setup, "create_test_database", return_value=g.db), \
            mock.patch.object(g.setup, "drop_test_database", side_effect=RuntimeError("registry_gate_cleanup_failure")), \
            contextlib.redirect_stderr(io.StringIO()) as errors:
        try:
            with g.setup.test_database():
                raise original
        except RuntimeError as exc:
            g.check("cleanup error never masks original exception", exc is original and "cleanup_failure" in errors.getvalue())
        else:
            g.check("original failure must propagate", False)
    with mock.patch.object(g.setup, "probe_extension", side_effect=RuntimeError("extension_absent")), \
            mock.patch.object(g.setup, "run_psql", side_effect=AssertionError("extension failure attempted DDL")):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("extension failure performs no DDL", str(exc) == "extension_absent")
        else:
            g.check("extension failure must propagate", False)
    for bad in ("agent_v13_registry", f"ll_registry_{os.getpid()}_ABCDEF", "ll_registry_x_abcdef",
                "ll_registry_0_abcdef", f"ll_registry_{os.getpid()}_abcdef_extra"):
        with g.case("database name " + bad):
            try:
                g.setup._validate_name(bad)
            except ValueError:
                g.check("strict lifecycle name rejected", True)
            else:
                g.check("bad lifecycle name accepted", False, bad)
    g.check("setup loads prefix once then only local SQL", 'load_stage(server, name, "ce_run")' in setup_source
            and 'load_stage(server, name, "registry")' not in setup_source and "LIKE 'll_registry_" not in setup_source)
    with g.setup.test_database(server=g.db.server, load_sql=False) as prefix:
        with contextlib.closing(g.setup.connect_owner_database(prefix)) as conn:
            g.check("load_sql=False has CE prefix but no registry", sql(conn,
                "SELECT to_regclass('v13_ce_runs') IS NOT NULL AND to_regclass('v13_registry_clock') IS NULL"))
        prefix_name, prefix_roles = prefix.name, dict(prefix.roles)
    g.check("cleanup removes exact database and host roles only", not g.setup.name_exists(g.db.server, prefix_name)
            and all(g.setup._role_oid_by_name(g.db.server, role) is None for role in prefix_roles.values())
            and g.setup._database_oid(g.db.server, g.db.name) == g.db.oid)
    scope = g.scope()
    with g.connection("owner") as conn:
        sql(conn, "DELETE FROM v13_registry_clock")
        for action in (lambda: register(conn, scope, "service", "seed", {"provides": ["x"]}),
                       lambda: retire(conn, scope, "service", "seed"), lambda: context(conn, scope)):
            sql(conn, "SAVEPOINT missing_seed")
            try:
                action()
            except psycopg2.Error as exc:
                sql(conn, "ROLLBACK TO SAVEPOINT missing_seed")
                g.check("missing clock seed raises on write/read", exc.pgcode == "P0001" and "clock seed missing" in str(exc))
            else:
                g.check("missing clock seed must not silently fall back", False)
        conn.rollback()
    sql_source = Path(__file__).with_name("v13_registry.sql").read_text()
    g.check("profile comment documents function-first and no consumer", "v13_interruptible()" in sql_source
            and "profile" in sql_source and "\u51fd\u6570\u4f18\u5148" in sql_source and "\u65e0\u6d88\u8d39\u8005" in sql_source)


def native_tools_revision(g):
    scope = g.scope()
    g.reg(scope, "tool_pin")
    revision = g.clock()
    before = g.committed(context, scope, revision)
    g.check("tools revision equals authoritative meta", before["tools_revision"]
            == g.audit("SELECT revision FROM v13_tools_meta WHERE singleton"))
    enabled, disabled = "registry_enabled_" + uid(), "registry_disabled_" + uid()
    for name, flag in ((enabled, True), (disabled, False)):
        g.audit("INSERT INTO tools(name,description,kind,handler,param_spec,enabled) VALUES (%s,'Registry fake tool','tool','registry_fake','{}',%s)", (name, flag))
        result = g.committed(context, scope, revision)
        entry = next(x for x in result["tools"] if x["name"] == name)
        g.check("raw tool row exact six keys and enabled flag", set(entry) == TOOL_KEYS and entry == {
            "name": name, "description": "Registry fake tool", "kind": "tool", "handler": "registry_fake", "param_spec": {}, "enabled": flag})
        g.check("tools write changes second scalar and hash at old registry revision", result["revision"] == revision
                and result["tools_revision"] == g.audit("SELECT revision FROM v13_tools_meta WHERE singleton")
                and result["tools_revision"] > before["tools_revision"] and result["tools"] != before["tools"]
                and result["context_hash"] != before["context_hash"] and result["services"] == before["services"])
        g.hash_ok(result)
        before = result
    g.check("disabled tool visible even at registry revision zero", any(
        x["name"] == disabled and x["enabled"] is False for x in g.committed(context, scope, 0)["tools"]))


PROBES = (native_load_untouched, native_plan_arm_closed_set, native_register_happy,
          native_retire_no_gap, native_already_live_not_live, native_frozen_matrix,
          native_one_live_concurrency, native_chain, native_context_determinism,
          native_as_of_boundaries, native_unresolved, native_value_shape,
          native_acl_roles, native_events_and_probe, native_static_setup, native_tools_revision)


def main():
    failures = []
    setup = setup_module()
    if sys.argv[1:]:
        raise SystemExit("usage: test_registry.py")
    with setup.test_database() as database:
        gate = Gate(database)
        print("Registry gate database:", database.name, "OID:", database.oid, flush=True)
        for probe in PROBES:
            print("\nGROUP", probe.__name__, flush=True)
            before, cases_before = gate.checks, len(gate.case_failures)
            try:
                probe(gate)
                if len(gate.case_failures) != cases_before:
                    raise AssertionError(f"independent cases failed: {gate.case_failures[cases_before:]}")
            except Exception as exc:
                failures.append(probe.__name__)
                print("GROUP FAIL", probe.__name__, repr(exc), flush=True)
                traceback.print_exc()
            else:
                print("GROUP PASS", probe.__name__, "checks", gate.checks - before, flush=True)
        print("\nSUMMARY groups", len(PROBES), "passed", len(PROBES) - len(failures), "failed", len(failures),
              "checks", gate.checks, "independent_case_failures", len(gate.case_failures), "failures", failures, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
