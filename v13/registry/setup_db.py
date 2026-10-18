"""Lifecycle helpers for an isolated v13 registry test database.

Importing this module is side-effect free.  Call :func:`create_test_database`
to create and validate a database, then use :func:`connect_test_database` for
role-specific probes.  Cleanup is deliberately limited to the database and
OID created by that call.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import get_server
from v13.load import load_stage, run_psql

ROOT = Path(__file__).resolve().parent
_NAME_RE = re.compile(r"^ll_registry_[0-9]+_[0-9a-f]{6}$")
EXPECTED_TABLES = {
    "public.v13_registrations",
    "public.v13_registry_clock",
    "public.v13_registry_meta",
}
EXPECTED_STAGE42_TABLES = {
    "public.v13_effect_context_pins",
    "public.v13_effect_context_event_pins",
}
EXPECTED_STAGE42_FUNCTIONS = {
    "v13_effect_context_pin_frozen",
    "v13_effect_context_event_pin_frozen",
    "v13_effect_context_event_capture",
    "v13_registry_fences",
    "v13_effect_context_pin_insert",
    "v13_effect_context_pin_lookup",
    "v13_effect_context_pin_matches",
    "v13_effect_context_event_current",
    "v13_effect_context_effect_current",
    "v13_complete_contextual",
    "v13_complete",
}

STAGE42_REPLACEMENTS = {
    "v13_claim(text,integer)", "v13_claim_fair(text,integer)",
    "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
    "v13_probe(uuid)", "v13_judgment_envelope(uuid)", "v13_snap_of(jsonb)",
    "v13_effect_envelope(jsonb)", "v13_advance(uuid,jsonb)",
    "v13_route(uuid,jsonb)", "v13_canonical_state(uuid)", "v13_parse(uuid)",
    "v13_triage_fold_reason(uuid)", "v13_triage_block_explore_spawn(uuid)",
    "v13_recover_idle()", "v13_scheduler_hint(uuid)",
    "v13_cap_answer_anchor(uuid,uuid)", "v13_cap_human_answered(uuid,uuid)",
    "v13_harness_tail_gap(uuid,uuid)", "v13_tail_gap_cap_exempt(uuid,uuid)",
    "v13_closeout(uuid,text,text,boolean)",
}
STAGE42_COMPLETION = {
    "v13_complete(uuid,uuid,integer,bigint,text,jsonb,bigint)",
    "v13_complete_contextual(uuid,uuid,integer,bigint,text,jsonb,bigint,boolean)",
}
STAGE42_SIGNATURES = STAGE42_COMPLETION | {
    "v13_effect_context_pin_frozen()", "v13_effect_context_event_pin_frozen()",
    "v13_effect_context_event_capture()", "v13_registry_fences()",
    "v13_effect_context_pin_insert(uuid,integer,bigint,uuid,bigint,bigint)",
    "v13_effect_context_pin_lookup(uuid,integer,bigint)",
    "v13_effect_context_pin_matches(uuid,integer,bigint,bigint)",
    "v13_effect_context_event_current(uuid,bigint)",
    "v13_effect_context_effect_current(uuid)",
}

STAGE42_BEGIN = "-- STAGE42_CONSUMER_OVERLAY_BEGIN\n"
STAGE42_END = "-- STAGE42_CONSUMER_OVERLAY_END\n"
# The Stage 41 bytes are an installation boundary.  The hash is deliberately
# checked over the exact byte prefix, including its final newline.
STAGE41_PREFIX_SHA256 = "e5222e1499001f3a734292d8456d2b431fcfcd2a5862952bfcc38137caee34d4"


@dataclass(frozen=True)
class TestDatabase:
    """A database created by one lifecycle invocation."""

    server: object
    name: str
    oid: int
    roles: dict[str, str]
    role_oids: dict[str, int]
    before: dict | None = None
    after: dict | None = None
    prefix: dict | None = None
    overlay_after: dict | None = None

    @property
    def uri(self) -> str:
        return self.server.get_uri(self.name)


def _new_name() -> str:
    return f"ll_registry_{os.getpid()}_{secrets.token_hex(3)}"


def _validate_name(name: str) -> None:
    match = _NAME_RE.fullmatch(name)
    if match is None or name.startswith("agent_v13_"):
        raise ValueError(f"illegal registry test database name: {name}")
    pid = int(name.split("_")[2])
    if pid != os.getpid():
        raise ValueError(f"registry test database belongs to pid {pid}, current pid is {os.getpid()}")


def _database_oid(server, name: str) -> int | None:
    with psycopg2.connect(server.get_uri("postgres")) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT oid FROM pg_database WHERE datname=%s", (name,))
            row = cur.fetchone()
    return None if row is None else int(row[0])


def name_exists(server, name: str) -> bool:
    """Return whether *name* exists; no database is created or removed."""
    return _database_oid(server, name) is not None


def _role_names(database_name: str) -> dict[str, str]:
    token = database_name.removeprefix("ll_registry_")
    return {alias: f"ll_registry_{token}_{alias}" for alias in ("route", "recall", "worker", "plain")}


def _create_host_roles(server, database_name: str) -> tuple[dict[str, str], dict[str, int]]:
    roles = _role_names(database_name)
    groups = {"route": "v13_route", "recall": "v13_recall", "worker": "v13_worker"}
    _validate_name(database_name)
    # Role DDL is transactional: no partial role creation can escape failure.
    with contextlib.closing(psycopg2.connect(server.get_uri("postgres"))) as conn:
        with conn:
            with conn.cursor() as cur:
                for alias, role in roles.items():
                    inheritance = "INHERIT" if alias in {"route", "recall", "worker"} else "NOINHERIT"
                    cur.execute(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE {inheritance} NOREPLICATION NOBYPASSRLS')
                for alias, group in groups.items():
                    cur.execute(f'GRANT "{group}" TO "{roles[alias]}"')
                cur.execute("SELECT rolname, oid::bigint FROM pg_roles WHERE rolname = ANY(%s)", (list(roles.values()),))
                by_name = {name: int(oid) for name, oid in cur.fetchall()}
                if set(by_name) != set(roles.values()):
                    raise RuntimeError("host role creation did not produce all role OIDs")
                result = roles, {alias: by_name[role] for alias, role in roles.items()}
    return result


def _role_oid_by_name(server, role: str) -> int | None:
    with psycopg2.connect(server.get_uri("postgres")) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT oid::bigint FROM pg_roles WHERE rolname=%s", (role,))
            row = cur.fetchone()
    return None if row is None else int(row[0])


def _drop_role_exact(server, role: str, role_oid: int) -> None:
    current = _role_oid_by_name(server, role)
    if current is None:
        return
    if current != role_oid:
        raise RuntimeError(f"refusing role cleanup: OID changed for {role}")
    run_psql(server, "postgres", f'DROP ROLE "{role}";')


def _drop_host_roles_values(server, roles: dict[str, str], role_oids: dict[str, int]) -> None:
    with psycopg2.connect(server.get_uri("postgres")) as conn:
        with conn.cursor() as cur:
            for alias, role in roles.items():
                cur.execute("SELECT oid,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s", (role,))
                row = cur.fetchone()
                if row is None:
                    continue
                expected_inherit = alias in {"route", "recall", "worker"}
                if int(row[0]) != role_oids[alias] or tuple(row[1:]) != (False, expected_inherit, False, False, True, False, False):
                    raise RuntimeError(f"refusing role cleanup: identity changed for {role}")
                cur.execute("SELECT parent.rolname FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid WHERE m.member=%s::regrole", (role,))
                expected_group = {"route": "v13_route", "recall": "v13_recall", "worker": "v13_worker"}.get(alias)
                if {r[0] for r in cur.fetchall()} != ({expected_group} if expected_group else set()):
                    raise RuntimeError(f"refusing role cleanup: membership changed for {role}")
                cur.execute(f'DROP ROLE "{role}"')
            conn.commit()


def _drop_host_roles(database: TestDatabase) -> None:
    _drop_host_roles_values(database.server, database.roles, database.role_oids)


def probe_extension(server) -> None:
    with psycopg2.connect(server.get_uri("postgres")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM pg_available_extensions "
                "WHERE name IN ('stannum','pg_jsonschema')"
            )
            found = {r[0] for r in cur.fetchall()}
    missing = {"stannum", "pg_jsonschema"} - found
    if missing:
        raise RuntimeError("missing extensions: " + ",".join(sorted(missing)))


def _registry_sql_parts() -> tuple[str, str]:
    path = ROOT / "v13_registry.sql"
    source = path.read_text()
    if source.count(STAGE42_BEGIN) != 1 or source.count(STAGE42_END) != 1:
        raise RuntimeError("registry SQL must contain one Stage 42 overlay boundary")
    prefix, rest = source.split(STAGE42_BEGIN, 1)
    overlay, tail = rest.split(STAGE42_END, 1)
    if tail.strip():
        raise RuntimeError("unexpected SQL after Stage 42 overlay")
    if hashlib.sha256(prefix.encode()).hexdigest() != STAGE41_PREFIX_SHA256:
        raise RuntimeError("Stage 41 SQL prefix bytes changed")
    return prefix, overlay


def load_registry_prefix(server, database: str) -> None:
    prefix, _ = _registry_sql_parts()
    run_psql(server, database, prefix, on_error_stop=True)


def load_registry_overlay(server, database: str) -> None:
    _, overlay = _registry_sql_parts()
    run_psql(server, database, overlay, on_error_stop=True)


def load_registry(server, database: str) -> None:
    """Apply the complete registry SQL after the cumulative prefix is loaded."""
    path = ROOT / "v13_registry.sql"
    if not path.is_file():
        raise FileNotFoundError(path)
    run_psql(server, database, path.read_text(), on_error_stop=True)


def _fetch_snapshot(server, database: str) -> dict:
    """Capture the complete pre-registry public/role contract in canonical tuples."""
    with psycopg2.connect(server.get_uri(database)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid),
                       pg_get_userbyid(p.proowner), coalesce(p.proacl::text,''),
                       p.prorettype::regtype::text, l.lanname, p.provolatile,
                       p.prosecdef, p.proisstrict, p.pronargdefaults,
                       coalesce(p.proconfig::text,'')
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                JOIN pg_language l ON l.oid=p.prolang
                WHERE n.nspname='public' ORDER BY 1
                """
            )
            functions = [tuple(r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT p.oid::regprocedure::text,
                       coalesce(jsonb_agg(jsonb_build_array(x.grantee,x.privilege_type,x.is_grantable)
                         ORDER BY x.grantee,x.privilege_type) FILTER (WHERE x.grantee IS NOT NULL),'[]')::text
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                LEFT JOIN LATERAL aclexplode(p.proacl) x ON true
                WHERE n.nspname='public' GROUP BY p.oid ORDER BY 1
                """
            )
            function_acl = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute(
                """
                SELECT c.oid::bigint, format('%I.%I',n.nspname,c.relname), c.relkind,
                       pg_get_userbyid(c.relowner), coalesce(c.relacl::text,''),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(a.attnum,a.attname,
                         a.atttypid::regtype::text,a.attnotnull,pg_get_expr(ad.adbin,ad.adrelid))
                         ORDER BY a.attnum) FROM pg_attribute a
                         LEFT JOIN pg_attrdef ad ON ad.adrelid=a.attrelid AND ad.adnum=a.attnum
                         WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped)::text,'[]'),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(a.attname,coalesce(a.attacl::text,''))
                         ORDER BY a.attnum) FROM pg_attribute a
                         WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped)::text,'[]'),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(t.tgname, t.tgenabled,
                         pg_get_triggerdef(t.oid)) ORDER BY t.tgname) FROM pg_trigger t
                         WHERE t.tgrelid=c.oid AND NOT t.tgisinternal)::text,'[]'),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(x.grantee,x.privilege_type,x.is_grantable)
                         ORDER BY x.grantee,x.privilege_type) FROM aclexplode(c.relacl) x)::text,'[]'),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(i.indexrelid::regclass::text,
                         pg_get_indexdef(i.indexrelid),i.indisunique,i.indisprimary)
                         ORDER BY i.indexrelid::regclass::text) FROM pg_index i
                         WHERE i.indrelid=c.oid)::text,'[]'),
                       coalesce((SELECT jsonb_agg(jsonb_build_array(con.conname,con.contype,
                         pg_get_constraintdef(con.oid)) ORDER BY con.conname) FROM pg_constraint con
                         WHERE con.conrelid=c.oid)::text,'[]')
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','S') ORDER BY 2
                """
            )
            relations = [tuple(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT nspname,coalesce(nspacl::text,'') FROM pg_namespace "
                "WHERE nspname='public'"
            )
            schema_acl = [tuple(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT datname,coalesce(datacl::text,'') FROM pg_database "
                "WHERE datname=current_database()"
            )
            db_acl = [tuple(r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
                       rolcanlogin,rolreplication,rolbypassrls,coalesce(rolconfig::text,'')
                FROM pg_roles ORDER BY rolname
                """
            )
            roles = [tuple(r) for r in cur.fetchall()]
            role_oids = {}
            cur.execute("SELECT rolname,oid::bigint FROM pg_roles ORDER BY rolname")
            role_oids = {r[0]: int(r[1]) for r in cur.fetchall()}
            cur.execute(
                """
                SELECT member.rolname, parent.rolname, am.admin_option
                FROM pg_auth_members am
                JOIN pg_roles parent ON parent.oid=am.roleid
                JOIN pg_roles member ON member.oid=am.member
                ORDER BY 1,2
                """
            )
            memberships = [tuple(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT sequence_schema,sequence_name FROM information_schema.sequences "
                "WHERE sequence_schema='public' ORDER BY 1,2"
            )
            sequences = [tuple(r) for r in cur.fetchall()]
    return {
        "functions": functions,
        "function_acl": function_acl,
        "relations": relations,
        "schema_acl": schema_acl,
        "db_acl": db_acl,
        "roles": roles,
        "role_oids": role_oids,
        "memberships": memberships,
        "sequences": sequences,
    }


def snapshot(server, database: TestDatabase | str) -> dict:
    """Return the complete public/role baseline for a test database."""
    name = database.name if isinstance(database, TestDatabase) else database
    return _fetch_snapshot(server, name)


def _acl_entries(raw: str) -> list[tuple[int, str, bool]]:
    """Decode aclexplode JSON while preserving grantee=0 (PUBLIC)."""
    return [
        (int(grantee), privilege, bool(grantable))
        for grantee, privilege, grantable in json.loads(raw or "[]")
    ]


def _role_oid(snapshot_data: dict, role: str) -> int:
    try:
        return snapshot_data["role_oids"][role]
    except KeyError as exc:
        raise RuntimeError(f"required role missing: {role}") from exc


def _fixed_search_path(config: str) -> bool:
    return "search_path=pg_catalog,public" in config.replace(" ", "").strip("{}")


def _registry_function_rows(after: dict, before: dict) -> list[tuple]:
    old = {r[0] for r in before["functions"]}
    return [r for r in after["functions"] if r[0] not in old]


def _function_name(signature: str) -> str:
    return signature.split("(", 1)[0].split(".")[-1]


def _validate_function_contracts(after: dict, before: dict, allowed_names: set[str]) -> list[tuple]:
    additions = _registry_function_rows(after, before)
    observed = {_function_name(row[0]) for row in additions}
    if observed != allowed_names:
        raise RuntimeError(f"unexpected registry function delta: {sorted(observed ^ allowed_names)}")
    role_rows = {r[0]: r for r in after["roles"]}
    owner_oids = {_role_oid(after, role) for role in ("v13_route", "v13_recall", "v13_resolve", "v13_spawn_owner", "v13_worker")}
    for row in additions:
        oid, definition, owner, acl, rettype, language, volatility, definer, strict, defaults, config = row
        role = role_rows.get(owner)
        function_name = _function_name(oid)
        expected_volatility = {
            "v13_registrations_frozen": "v", "v13_registry_caller_role": "s",
            "v13_registry_read_ok": "s", "v13_registry_chain_inner": "s",
            "v13_scope_chain": "s", "v13_registry_register": "v",
            "v13_registry_retire": "v", "v13_registry_context": "s",
            "v13_effect_context_pin_frozen": "v",
            "v13_effect_context_event_pin_frozen": "v",
            "v13_effect_context_event_capture": "v",
            "v13_registry_fences": "s", "v13_effect_context_pin_insert": "v",
            "v13_effect_context_pin_lookup": "s", "v13_effect_context_pin_matches": "s",
            "v13_effect_context_event_current": "s",
            "v13_effect_context_effect_current": "s",
            "v13_complete_contextual": "v",
            "v13_complete": "v",
        }[function_name]
        expected_defaults = {
            "v13_scope_chain": 1,
            "v13_registry_register": 1,
            "v13_registry_context": 2,
        }.get(_function_name(oid), 0)
        expected_definer = function_name not in {"v13_complete", "v13_complete_contextual"}
        if (role is None or role[1] is not True or definer != expected_definer or not _fixed_search_path(config)
                or volatility != expected_volatility or defaults != expected_defaults):
            raise RuntimeError(f"function contract missing for {oid}")
        owner_oid = _role_oid(after, owner)
        for grantee, privilege, grantable in _acl_entries(after["function_acl"].get(oid, "[]")):
            if grantee == owner_oid:
                continue
            if privilege != "EXECUTE" or grantable or grantee == 0 or grantee not in owner_oids:
                raise RuntimeError(f"unexpected function ACL for {oid}")
    return additions


def validate_stage41_prefix(before: dict, prefix: dict) -> None:
    """Validate the immutable Stage 41 installation boundary."""
    old_rel = {r[1]: r for r in before["relations"]}
    new_rel = {r[1]: r for r in prefix["relations"]}
    added = {name for name, row in new_rel.items() if name not in old_rel and row[2] in ("r", "p")}
    if added != EXPECTED_TABLES:
        raise RuntimeError(f"unexpected Stage 41 table delta: {added}")
    additions = _validate_function_contracts(
        prefix, before,
        {"v13_registrations_frozen", "v13_registry_caller_role", "v13_registry_read_ok",
         "v13_registry_chain_inner", "v13_scope_chain", "v13_registry_register",
         "v13_registry_retire", "v13_registry_context"},
    )
    if prefix["sequences"] != before["sequences"]:
        raise RuntimeError("Stage 41 changed sequences")
    for key in ("schema_acl", "db_acl", "roles", "role_oids", "memberships"):
        if prefix[key] != before[key]:
            raise RuntimeError(f"Stage 41 changed {key}")
    print("[prefix] Stage 41 tables +3, functions +8, roles/ACL/sequences frozen: PASS")


def _validate_pin_relation(row: tuple) -> None:
    name = row[1].removeprefix("public.")
    pin = name == "v13_effect_context_pins"
    columns = ([('effect_id','uuid'), ('attempt_no','integer'), ('fence','bigint'),
                ('scope_id','uuid'), ('context_revision','bigint'), ('tools_revision','bigint'),
                ('claimed_at','timestamp with time zone')] if pin else
               [('session_id','uuid'), ('event_seq','bigint'), ('effect_id','uuid'),
                ('attempt_no','integer'), ('fence','bigint')])
    expected_columns = [[i,n,t,True,'clock_timestamp()' if n == 'claimed_at' else None]
                        for i,(n,t) in enumerate(columns,1)]
    if json.loads(row[5]) != expected_columns or any(acl for _,acl in json.loads(row[6])):
        raise RuntimeError(f"Stage 42 column shape/ACL changed: {name}")
    constraints = ({
        (name+'_effect_id_fkey','f','FOREIGN KEY (effect_id) REFERENCES effects(effect_id)'),
        (name+'_scope_id_fkey','f','FOREIGN KEY (scope_id) REFERENCES sessions(session_id)'),
        (name+'_attempt_no_check','c','CHECK ((attempt_no > 0))'),
        (name+'_fence_check','c','CHECK ((fence > 0))'),
        (name+'_context_revision_check','c','CHECK ((context_revision >= 0))'),
        (name+'_tools_revision_check','c','CHECK ((tools_revision >= 0))'),
        (name+'_pkey','p','PRIMARY KEY (effect_id, attempt_no)'),
        (name+'_effect_id_attempt_no_fence_key','u','UNIQUE (effect_id, attempt_no, fence)'),
    } if pin else {
        (name+'_pkey','p','PRIMARY KEY (session_id, event_seq)'),
        (name+'_session_id_event_seq_fkey','f','FOREIGN KEY (session_id, event_seq) REFERENCES events(session_id, seq)'),
        (name+'_effect_id_attempt_no_fence_fkey','f','FOREIGN KEY (effect_id, attempt_no, fence) REFERENCES v13_effect_context_pins(effect_id, attempt_no, fence)'),
    })
    observed_constraints = {tuple(c) for c in json.loads(row[10])}
    if any(kind == 'n' for _,kind,_ in observed_constraints):
        constraints |= {(name+'_'+n+'_not_null','n','NOT NULL '+n) for n,_ in columns}
    if observed_constraints != constraints:
        raise RuntimeError(f"Stage 42 constraint closure changed: {name}: {row[10]}")
    index_specs = ([(name+'_pkey','effect_id, attempt_no',True,True),
                    (name+'_effect_id_attempt_no_fence_key','effect_id, attempt_no, fence',True,False)] if pin else
                   [(name+'_pkey','session_id, event_seq',True,True),
                    ('ix_v13_effect_context_event_pins_effect','effect_id, attempt_no, fence',False,False)])
    expected_indexes = {(n, f"CREATE {'UNIQUE ' if unique else ''}INDEX {n} ON public.{name} USING btree ({cols})", unique, primary)
                        for n,cols,unique,primary in index_specs}
    if {tuple(i) for i in json.loads(row[9])} != expected_indexes:
        raise RuntimeError(f"Stage 42 index closure changed: {name}")
    trigger_name = 'trg_v13_effect_context_pin_frozen' if pin else 'trg_v13_effect_context_event_pin_frozen'
    function_name = 'v13_effect_context_pin_frozen' if pin else 'v13_effect_context_event_pin_frozen'
    operations = 'UPDATE OR DELETE' if pin else 'INSERT OR DELETE OR UPDATE'
    # pg_get_triggerdef emits operations in INSERT/DELETE/UPDATE order.
    if pin:
        operations = 'DELETE OR UPDATE'
    expected_trigger = [[trigger_name,'O',f'CREATE TRIGGER {trigger_name} BEFORE {operations} ON public.{name} FOR EACH ROW EXECUTE FUNCTION {function_name}()']]
    if json.loads(row[7]) != expected_trigger:
        raise RuntimeError(f"Stage 42 trigger closure changed: {name}: {row[7]}")


def validate_stage42_overlay(prefix: dict, after: dict) -> None:
    """Validate the additive Stage 42 object closure and helper ACL matrix."""
    old_rel = {r[1]: r for r in prefix["relations"]}
    new_rel = {r[1]: r for r in after["relations"]}
    added = {name for name, row in new_rel.items() if name not in old_rel and row[2] in ("r", "p")}
    if added != EXPECTED_STAGE42_TABLES:
        raise RuntimeError(f"unexpected Stage 42 table delta: {added}")
    _validate_function_contracts(after, prefix, EXPECTED_STAGE42_FUNCTIONS)
    old_functions = {r[0]: r for r in prefix["functions"]}
    new_functions = {r[0]: r for r in after["functions"]}
    changed = {sig for sig, row in old_functions.items() if new_functions.get(sig) != row}
    if changed != STAGE42_REPLACEMENTS:
        raise RuntimeError(f"unexpected Stage 42 replacements: {changed ^ STAGE42_REPLACEMENTS}")
    for sig in changed:
        old, new = old_functions[sig], new_functions[sig]
        # Only claim changes language/search_path; other replacements retain metadata.
        allowed = {1} | ({5, 10} if sig == "v13_claim(text,integer)" else set())
        if any(a != b for i, (a, b) in enumerate(zip(old, new)) if i not in allowed):
            raise RuntimeError(f"Stage 42 replacement metadata changed: {sig}")
        if sig == "v13_claim(text,integer)" and (new[5] != "plpgsql" or not _fixed_search_path(new[10])):
            raise RuntimeError("Stage 42 claim language/search_path contract changed")
    additions = set(new_functions) - set(old_functions)
    if additions != STAGE42_SIGNATURES:
        raise RuntimeError(f"unexpected Stage 42 signatures: {additions ^ STAGE42_SIGNATURES}")
    if after["sequences"] != prefix["sequences"]:
        raise RuntimeError("Stage 42 changed sequences")
    for key in ("schema_acl", "db_acl", "roles", "role_oids", "memberships"):
        if after[key] != prefix[key]:
            raise RuntimeError(f"Stage 42 changed {key}")
    added_relations = {name for name in new_rel if name not in old_rel}
    if added_relations != EXPECTED_STAGE42_TABLES:
        raise RuntimeError(f"unexpected Stage 42 relation/index closure: {added_relations}")
    superusers = {r[0] for r in after["roles"] if r[1] is True}
    for name in EXPECTED_STAGE42_TABLES:
        row = new_rel[name]
        _validate_pin_relation(row)
        if row[3] not in superusers:
            raise RuntimeError(f"Stage 42 table owner is not a superuser: {name}")
        if any(grantee != _role_oid(after, row[3]) for grantee, _, _ in _acl_entries(row[8])):
            raise RuntimeError(f"Stage 42 table has non-owner ACL: {name}")
    print(f"[overlay] Stage 42 tables +2, functions +11, replacements {len(STAGE42_REPLACEMENTS)}; roles/sequences/schema/db ACL unchanged: PASS")


def validate_schema_owner(server, database: str) -> None:
    """The registry schema owner must be a trusted superuser/operator in practice."""
    with psycopg2.connect(server.get_uri(database)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            if cur.fetchone() != (True,):
                raise RuntimeError("registry schema owner must be a trusted superuser")
            cur.execute("SELECT public.v13_control_operator()")
            if cur.fetchone() != (True,):
                raise RuntimeError("registry schema owner is not a v13 control operator")


def validate_delta(before: dict, after: dict) -> None:
    old_rel = {r[1]: r for r in before["relations"]}
    new_rel = {r[1]: r for r in after["relations"]}
    added_tables = {
        name for name, row in new_rel.items()
        if name not in old_rel and row[2] in ("r", "p")
    }
    if added_tables != EXPECTED_TABLES | EXPECTED_STAGE42_TABLES:
        raise RuntimeError(f"unexpected table delta: {added_tables}")
    added_sequences = {
        name for name, row in new_rel.items()
        if name not in old_rel and row[2] == "S"
    }
    if len(added_sequences) != 0:
        raise RuntimeError(f"expected zero registry sequences, got {added_sequences}")
    if before["sequences"] != after["sequences"]:
        raise RuntimeError("sequences changed while applying registry SQL")
    for key in ("schema_acl", "db_acl", "roles", "role_oids", "memberships"):
        if before[key] != after[key]:
            raise RuntimeError(f"{key} changed while applying registry SQL")
    for key in ("functions", "relations"):
        old = {r[0] if key == "functions" else r[1]: r for r in before[key]}
        new = {r[0] if key == "functions" else r[1]: r for r in after[key]}
        for ident, row in old.items():
            if ident not in new:
                raise RuntimeError(f"frozen {key} changed: {ident}")
            if key == "functions" and ident in STAGE42_REPLACEMENTS:
                continue
            if key == "relations" and ident == "public.events":
                # Stage 42 may add its capture trigger only; preserve all other
                # relation metadata, including the existing append-only trigger.
                old_row, new_row = list(row), list(new[ident])
                old_triggers = json.loads(old_row[7])
                new_triggers = json.loads(new_row[7])
                if len(new_triggers) != len(old_triggers) + 1 or not set(map(str, old_triggers)).issubset(set(map(str, new_triggers))):
                    raise RuntimeError("events trigger delta is not exactly one additive capture trigger")
                capture = [entry for entry in new_triggers if entry not in old_triggers]
                if len(capture) != 1 or "v13_effect_context_event_capture" not in capture[0][2]:
                    raise RuntimeError("events capture trigger identity mismatch")
                old_row[7] = new_row[7]
                if tuple(old_row) != tuple(new_row):
                    raise RuntimeError(f"frozen relation changed: {ident}")
            elif new[ident] != row:
                raise RuntimeError(f"frozen {key} changed: {ident}")
    additions = _validate_function_contracts(
        after, before,
        {"v13_registrations_frozen", "v13_registry_caller_role", "v13_registry_read_ok",
         "v13_registry_chain_inner", "v13_scope_chain", "v13_registry_register",
         "v13_registry_retire", "v13_registry_context", *EXPECTED_STAGE42_FUNCTIONS},
    )
    role_rows = {r[0]: r for r in after["roles"]}
    acl_by_name = after["function_acl"]
    for row in additions:
        oid, definition, owner, acl, rettype, language, volatility, definer, strict, defaults, config = row
        role = role_rows.get(owner)
        if role is None or role[1] is not True:
            raise RuntimeError(f"registry function {oid} is not owned by a trusted superuser")
        function_name = _function_name(oid)
        expected_defaults = {
            "v13_scope_chain": 1,
            "v13_registry_register": 1,
            "v13_registry_context": 2,
        }.get(function_name, 0)
        expected_definer = function_name not in {"v13_complete", "v13_complete_contextual"}
        if definer != expected_definer or not _fixed_search_path(config) or defaults != expected_defaults:
            raise RuntimeError(f"registry definer/search_path contract missing: {oid}")
        callable_route = {"v13_registry_register", "v13_registry_retire"}
        callable_read = {"v13_scope_chain", "v13_registry_context"}
        allowed = set()
        if function_name in callable_route | callable_read:
            allowed.add(_role_oid(after, "v13_route"))
        if function_name in callable_read:
            allowed.add(_role_oid(after, "v13_recall"))
        if function_name == "v13_registry_fences":
            allowed = {_role_oid(after, role) for role in ("v13_route", "v13_recall", "v13_resolve")}
        elif function_name == "v13_effect_context_pin_insert":
            allowed = {_role_oid(after, "v13_route")}
        elif function_name == "v13_effect_context_pin_lookup":
            allowed = {_role_oid(after, "v13_route")}
        elif function_name == "v13_effect_context_pin_matches":
            allowed = {_role_oid(after, "v13_route"), _role_oid(after, "v13_spawn_owner")}
        elif function_name in {"v13_effect_context_event_current", "v13_effect_context_effect_current"}:
            allowed = {_role_oid(after, "v13_route"), _role_oid(after, "v13_resolve")}
            if function_name == "v13_effect_context_event_current":
                allowed.update(_role_oid(after, role) for role in ("v13_recall", "v13_spawn_owner"))
        elif function_name in {"v13_complete", "v13_complete_contextual"}:
            allowed = {_role_oid(after, "v13_route"), _role_oid(after, "v13_spawn_owner")}
        observed = set()
        for grantee, privilege, grantable in _acl_entries(acl_by_name.get(oid, "[]")):
            if privilege != "EXECUTE":
                raise RuntimeError(f"unexpected registry function ACL for {oid}")
            if grantee == _role_oid(after, owner):
                continue
            if grantee not in allowed or grantable:
                raise RuntimeError(f"unexpected registry function grantee for {oid}")
            observed.add(grantee)
        if observed != allowed:
            raise RuntimeError(f"registry function ACL matrix mismatch for {oid}")
    new_relations = [r for name, r in new_rel.items() if name not in old_rel]
    for row in new_relations:
        owner = row[3]
        role = role_rows.get(owner)
        if role is None or role[1] is not True:
            raise RuntimeError(f"new registry relation is not superuser-owned: {row[1]}")
        allowed = set()
        if row[1] in {"public.v13_registrations", "public.v13_registry_meta"}:
            allowed = {_role_oid(after, "v13_recall"), _role_oid(after, "v13_route")}
        observed = set()
        for grantee, privilege, grantable in _acl_entries(row[8]):
            if grantee == _role_oid(after, owner):
                continue
            if grantee not in allowed or privilege != "SELECT" or grantable:
                raise RuntimeError(f"unexpected registry relation ACL: {row[1]}")
            observed.add(grantee)
        if observed != allowed:
            raise RuntimeError(f"registry relation ACL matrix mismatch: {row[1]}")
        for column, raw_acl in json.loads(row[6]):
            if raw_acl:
                raise RuntimeError(f"unexpected registry column ACL: {row[1]}.{column}")
    print("[delta] tables +5: " + ", ".join(sorted(added_tables)))
    print("[delta] sequences +0; functions +" + str(len(additions)) + ": "
          + ", ".join(r[0] for r in additions))
    print("[delta] frozen objects/roles/ACL unchanged; superuser owners, "
          "SECURITY DEFINER, fixed search_path and registry ACL matrix: PASS")


def restrict_database(server, database: str) -> None:
    run_psql(server, database, f'''
      REVOKE TEMPORARY ON DATABASE "{database}" FROM PUBLIC;
      REVOKE CREATE ON SCHEMA public FROM PUBLIC;
      REVOKE TEMPORARY ON DATABASE "{database}" FROM v13_route, v13_recall, v13_worker;
      REVOKE CREATE ON SCHEMA public FROM v13_route, v13_recall, v13_worker;
    ''')


def validate_host_role_boundaries(server, database: str, roles: dict[str, str]) -> None:
    """Verify each ephemeral host identity has only its intended group rights."""
    with psycopg2.connect(server.get_uri(database)) as conn:
        with conn.cursor() as cur:
            for alias, role in roles.items():
                cur.execute(
                    "SELECT has_database_privilege(%s,current_database(),'TEMPORARY'), "
                    "has_schema_privilege(%s,'public','CREATE'), "
                    "pg_has_role(%s,'v13_spawn_owner','USAGE')",
                    (role, role, role),
                )
                temporary, create, spawn = cur.fetchone()
                if temporary or create or spawn:
                    raise RuntimeError(f"host role boundary violated: {alias}/{role}")
            cur.execute("SELECT rolinherit FROM pg_roles WHERE rolname=%s", (roles["plain"],))
            if cur.fetchone() != (False,):
                raise RuntimeError("plain host role unexpectedly inherits")
            for alias, group in (("route", "v13_route"), ("recall", "v13_recall"), ("worker", "v13_worker")):
                cur.execute("SELECT pg_has_role(%s,%s,'USAGE')", (roles[alias], group))
                if cur.fetchone() != (True,):
                    raise RuntimeError(f"host role missing intended membership: {alias}/{group}")


def validate_deployment_restrictions(server, database: str, roles: dict[str, str] | None = None) -> None:
    """Verify the test deployment's database/schema creation boundary."""
    with psycopg2.connect(server.get_uri(database)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT has_schema_privilege('public','public','CREATE')")
            public_schema_create = cur.fetchone()[0]
            if public_schema_create:
                raise RuntimeError("PUBLIC still has CREATE on schema public")
            cur.execute("SELECT has_database_privilege('public', current_database(), 'TEMPORARY')")
            public_db_temp = cur.fetchone()[0]
            if public_db_temp:
                raise RuntimeError("PUBLIC still has TEMPORARY on registry database")
            cur.execute("""
                SELECT EXISTS (SELECT 1 FROM pg_namespace n, LATERAL aclexplode(n.nspacl) x
                               WHERE n.nspname='public' AND x.grantee=0 AND x.privilege_type='CREATE'),
                       EXISTS (SELECT 1 FROM pg_database d, LATERAL aclexplode(d.datacl) x
                               WHERE d.datname=current_database() AND x.grantee=0 AND x.privilege_type='TEMPORARY')
            """)
            acl_schema_create, acl_db_temp = cur.fetchone()
            if acl_schema_create != public_schema_create or acl_db_temp != public_db_temp:
                raise RuntimeError("PUBLIC has_* result disagrees with grantee=0 ACL")
            cur.execute(
                "SELECT rolname, has_database_privilege(rolname,current_database(),'TEMPORARY'), "
                "has_schema_privilege(rolname,'public','CREATE') "
                "FROM pg_roles WHERE rolname IN ('v13_route','v13_recall','v13_worker') "
                "ORDER BY rolname"
            )
            for role, temporary, create in cur.fetchall():
                if temporary or create:
                    raise RuntimeError(f"deployment restriction missing for {role}")
    if roles is not None:
        validate_host_role_boundaries(server, database, roles)


def connect_test_database(database: TestDatabase | str, *, server=None, role: str | None = "route"):
    """Connect using a test database handle or name.

    A ``TestDatabase`` resolves the four aliases from its recorded temporary
    roles.  A string name requires ``server`` and resolves aliases with the
    deterministic temporary names from ``_role_names``.  ``role=None`` omits
    the user parameter so the server URI chooses its default identity; any
    other string is passed through as an explicit PostgreSQL role name.
    """
    if isinstance(database, TestDatabase):
        server = database.server
        name = database.name
        roles = database.roles
    else:
        if server is None:
            raise ValueError("server is required when database is a name")
        name = database
        roles = _role_names(name)
    role = roles.get(role, role) if role is not None else None
    kwargs = {} if role is None else {"user": role}
    return psycopg2.connect(server.get_uri(name), **kwargs)


def connect_owner_database(database: TestDatabase | str, *, server=None):
    """Connect with the server's owner identity for setup probes and audit."""
    if isinstance(database, TestDatabase):
        return psycopg2.connect(database.server.get_uri(database.name))
    if server is None:
        raise ValueError("server is required when database is a name")
    return psycopg2.connect(server.get_uri(database))


def connect_route(database: TestDatabase | str, *, server=None):
    return connect_test_database(database, server=server, role="route")


def connect_recall(database: TestDatabase | str, *, server=None):
    return connect_test_database(database, server=server, role="recall")


def connect_worker(database: TestDatabase | str, *, server=None):
    return connect_test_database(database, server=server, role="worker")


def connect_plain(database: TestDatabase | str, *, server=None):
    return connect_test_database(database, server=server, role="plain")


def _drop_database_exact(server, name: str, oid: int, force: bool = True) -> None:
    _validate_name(name)
    current_oid = _database_oid(server, name)
    if current_oid is not None and current_oid != oid:
        raise RuntimeError(f"refusing cleanup: OID changed for {name}")
    if current_oid is None:
        return
    suffix = " WITH (FORCE)" if force else ""
    run_psql(server, "postgres", f'DROP DATABASE "{name}"{suffix};')


def drop_test_database(database: TestDatabase, *, force: bool = True) -> None:
    """Drop only the exact database/OID and host roles recorded for this call."""
    db_error: BaseException | None = None
    role_error: BaseException | None = None
    try:
        _drop_database_exact(database.server, database.name, database.oid, force)
    except BaseException as exc:
        db_error = exc
        print(f"[cleanup failed] {database.name}: {exc}", file=sys.stderr)
    try:
        # Roles are independently identity-checked; this remains safe even if
        # another process already removed the database.
        _drop_host_roles_values(database.server, database.roles, database.role_oids)
    except BaseException as exc:
        role_error = exc
        print(f"[cleanup failed] host roles for {database.name}: {exc}", file=sys.stderr)
    if db_error is not None:
        raise db_error
    if role_error is not None:
        raise role_error


def create_test_database(*, server=None, load_sql: bool = True, validate: bool = True) -> TestDatabase:
    """Create a strict temporary database and optionally load/validate Stage 41."""
    server = server or get_server()
    name = _new_name()
    _validate_name(name)
    probe_extension(server)
    if name_exists(server, name):
        raise RuntimeError(f"database exists, refusing to drop: {name}")

    created = False
    oid: int | None = None
    roles: dict[str, str] = {}
    role_oids: dict[str, int] = {}
    database: TestDatabase | None = None
    try:
        run_psql(server, "postgres", f'CREATE DATABASE "{name}";')
        created = True
        oid = _database_oid(server, name)
        if oid is None:
            raise RuntimeError(f"created database disappeared: {name}")
        # Load Stages 1-40 exactly once before host memberships and the snapshot.
        load_stage(server, name, "ce_run")
        roles, role_oids = _create_host_roles(server, name)
        database = TestDatabase(server, name, oid, roles, role_oids)
        restrict_database(server, name)
        validate_deployment_restrictions(server, name, roles)
        validate_schema_owner(server, name)
        before = snapshot(server, name)
        if load_sql:
            load_registry_prefix(server, name)
            prefix = snapshot(server, name)
            load_registry_overlay(server, name)
            after = snapshot(server, name)
            if validate:
                validate_stage41_prefix(before, prefix)
                validate_stage42_overlay(prefix, after)
                validate_delta(before, after)
            database = TestDatabase(server, name, oid, roles, role_oids,
                                    before=before, after=after, prefix=prefix)
        else:
            database = TestDatabase(server, name, oid, roles, role_oids,
                                    before=before, after=before, prefix=before)
        return database
    except BaseException as original:
        cleanup_error: BaseException | None = None
        if database is not None:
            try:
                drop_test_database(database)
            except BaseException as exc:
                cleanup_error = exc
        else:
            # Handle failures before TestDatabase construction without broad
            # name-only deletion. Retry OID lookup; unknown identity is kept.
            if created:
                try:
                    confirmed_oid = oid if oid is not None else _database_oid(server, name)
                    if confirmed_oid is not None:
                        _drop_database_exact(server, name, confirmed_oid)
                except BaseException as exc:
                    cleanup_error = exc
                if roles:
                    try:
                        _drop_host_roles_values(server, roles, role_oids)
                    except BaseException as exc:
                        print(f"[host role cleanup failed] {exc}", file=sys.stderr)
                        if cleanup_error is None:
                            cleanup_error = exc
        if cleanup_error is not None:
            print(f"[cleanup failed while preserving original error] {cleanup_error}", file=sys.stderr)
        raise original


@contextlib.contextmanager
def test_database(*, server=None, load_sql: bool = True, validate: bool = True) -> Iterator[TestDatabase]:
    """Yield a test DB and clean it without masking an active exception."""
    database = create_test_database(server=server, load_sql=load_sql, validate=validate)
    try:
        yield database
    except BaseException as original:
        try:
            drop_test_database(database)
        except BaseException as cleanup_error:
            print(f"[cleanup failed while preserving original error] {cleanup_error}", file=sys.stderr)
        raise original
    else:
        drop_test_database(database)


# Explicit aliases make the lifecycle contract discoverable to W4 without
# coupling it to the CLI's historical names.
create_database = create_test_database
connect_database = connect_test_database
drop_database = drop_test_database


def probe_session_owner_boundary(database: TestDatabase | str, *, server=None) -> None:
    """Run the existing negative probe in one transaction and roll it back."""
    with connect_owner_database(database, server=server) as conn:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT registry_owner_probe")
            try:
                cur.execute("INSERT INTO public.sessions DEFAULT VALUES")
            except psycopg2.Error as exc:
                msg = str(exc)
                cur.execute("ROLLBACK TO SAVEPOINT registry_owner_probe")
                if "sessions insert owner" not in msg:
                    raise RuntimeError(f"unexpected direct sessions INSERT failure: {msg}") from exc
                print("[probe] direct superuser sessions INSERT rejected: sessions insert owner")
            else:
                raise RuntimeError("frozen sessions INSERT trigger did not reject direct INSERT")
            cur.execute("SAVEPOINT registry_owner_probe")
            cur.execute("SELECT public.v13_open_session('{}'::jsonb)")
            sid = cur.fetchone()[0]
            try:
                cur.execute(
                    "UPDATE public.sessions SET parent_session_id=gen_random_uuid(), "
                    "parent_cutoff_seq=0 WHERE session_id=%s",
                    (sid,),
                )
            except psycopg2.Error as exc:
                msg = str(exc)
                cur.execute("ROLLBACK TO SAVEPOINT registry_owner_probe")
                if "fork columns are write-once" not in msg:
                    raise RuntimeError(f"unexpected fork-column update failure: {msg}") from exc
                print("[probe] open_session child retrofit rejected: fork columns are write-once")
            else:
                raise RuntimeError("frozen fork-column trigger did not reject retrofit")
            conn.rollback()


def main() -> int:
    # CLI keeps a handle so cleanup is exact even when loading/validation fails.
    database = create_test_database()
    active_error = False
    try:
        if "--probe-session-owner" in sys.argv[1:]:
            probe_session_owner_boundary(database)
        print("[ready]", database.name)
        return 0
    except BaseException:
        active_error = True
        raise
    finally:
        try:
            drop_test_database(database)
        except BaseException:
            # Preserve an active probe/setup exception; expose cleanup errors on success.
            if not active_error:
                raise


if __name__ == "__main__":
    raise SystemExit(main())
