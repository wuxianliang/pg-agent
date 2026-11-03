"""M3 fake Chainlit UI. The hub exclusively owns one synchronous worker thread."""
import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host.canonical import descriptor_digest, pg_jsonb_text
from v24.ui import catalog
from v24.ui.control import AgentRuntime, DEFAULT_BUDGET, Discovery
from v24.ui.env import acquire_lock, open_env, release_lock, status_env
from v24.ui.fake import ScriptedUiAdapter
from v24.ui.render import (StepRecord, _record, render_effect, render_generating,
                           render_run_start, render_state)
from v24.ui.sessions import SessionStore, TERMINAL


UI_BODY_BYTE_CEILING = 8000


def build_system_prompt(skills_block: str, history: str) -> str:
    return (
        "You are a workspace assistant. Use small steps.\n"
        "stream:false; each reply is the complete answer. Reply in the user's language.\n"
        "| Tool choice | Pi | RPCE |\n|---|---|---|\n"
        "| Read | read: verbatim, offset paging | read_file: start_line; -N takes tail, never with limit |\n"
        "| Search | grep: glob/literal | file_search: mode/filter/regex |\n"
        "| Edit | edit: one edits batch against the same original, no overlaps | apply_edits: exactly one of rewrite, search+replace, edits; on_missing only with rewrite |\n"
        'Each reply has a 512-token cap including reasoning; finish_reason="length" causes '
        '_unknown("finish_length") and terminates the run, rather than truncating an answer or arguments. '
        "Keep tool arguments small; split new content into small write.append calls.\n"
        "When a skill matches the task, first use read or read_file to read its location in full.\n"
        + skills_block + "\n" + history
    )


class FakeAppAdapter(ScriptedUiAdapter):
    """Derive the fake script from the durable effect cause, including on restart."""
    def __init__(self):
        super().__init__([])
        self.body_byte_ceiling = UI_BODY_BYTE_CEILING

    def send(self, prepared):
        # Visible fake latency makes the actual stop/steer UI exercisable.
        # This sleep runs on the worker thread, never on the event loop.
        time.sleep(0.5)
        return super().send(prepared)

    def build(self, effect, history, pins):
        prepared = super().build(effect, history, pins)
        request = effect["request"]
        users = [m["content"] for m in prepared.messages if m["role"] == "user"]
        text = users[-1] if users else ""
        cause = request["cause"]
        if cause == "start":
            self.outcomes = ([{"kind": "interaction", "payload": {"prompt": "Continue?"}}]
                             if "interaction" in text.lower() else
                             [{"kind": "tool", "key": "read", "args": {"path": "README.md", "limit": 5}}])
        elif cause == "respond":
            self.outcomes = [{"kind": "final", "text": "answered"}]
        elif cause == "steer":
            self.outcomes = [{"kind": "final", "text": "steered: " + text}]
        else:
            self.outcomes = [{"kind": "final", "text": "echo: " + text}]
        return prepared


@dataclass(frozen=True)
class UiEvent:
    kind: str
    value: str | StepRecord = ""
    run_id: str = ""
    interaction_id: str = ""


@dataclass
class ThreadState:
    sid: str
    conversation_id: str
    scope: str
    realm: str
    run_id: str | None = None
    busy: bool = False
    readonly: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    seen: set[str] = field(default_factory=set)
    rounds: int = 0
    pending_steer: str | None = None
    attached: bool = True
    inbox: list[tuple[str, str]] = field(default_factory=list)


class Backend:
    """Every method, constructor and close executes in the same executor thread.

    Commands are drained by the async hub before each bounded round. A round
    does one run_once per busy scope; no blocking drive() occupies the inbox.
    """
    def __init__(self, emit, *, env=None, check_environment=True):
        self.owner = threading.get_ident()
        self.emit_callback = emit
        self.states = {}
        self.seq = 0
        self.lock_fd = None
        self.rt = None
        self.store = None
        self.toolset = "exec"
        # pgembed INFO logs include its subprocess environment. Suppress that
        # logger before any server startup; never send credentials to logs.
        logging.getLogger("pgembed").setLevel(logging.WARNING)
        self.mode = os.environ.get("V24_UI_MODE", "fake")
        if self.mode not in ("fake", "real"):
            raise RuntimeError("invalid_mode")
        # Real provider activation is M5; M3 never constructs a real adapter.
        if self.mode == "real":
            raise RuntimeError("real_mode_not_enabled")
        data_dir = env.data_dir if env else ROOT / ".uidata"
        data_dir.mkdir(mode=0o700, exist_ok=True)
        self.lock_fd = acquire_lock(data_dir)
        try:
            self.env = env or open_env()
            if check_environment:
                status = status_env(self.env)
                if status.get("status") != "ok":
                    raise RuntimeError(status.get("status", status.get("reason", "schema_drift")))
            configured = os.environ.get("V24_UI_WORKSPACE_ROOT")
            workspace = Path(configured) if configured else self.env.workspace_root
            if not workspace.is_absolute() or workspace.resolve() != workspace or not workspace.is_dir():
                raise RuntimeError("workspace_invalid")
            self.env = dataclasses.replace(self.env, workspace_root=workspace)
            self.toolset = os.environ.get("V24_UI_TOOLSET", "read" if configured else "exec")
            if self.toolset not in ("read", "write", "exec"):
                raise RuntimeError("invalid_toolset")
            if not configured:
                fixture = workspace / "README.md"
                try:
                    fd = os.open(fixture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "w") as stream:
                        stream.write("# v24 ui scratch\n")
            self.skills_block = catalog.available_skills()
            self.rt = AgentRuntime(self.env, adapter=FakeAppAdapter())
            self.store = SessionStore(data_dir, read_run=self.run)
        except BaseException:
            self.close()
            raise

    def check_thread(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("runtime_thread_mismatch")

    def send(self, st, kind, value="", *, interaction_id=""):
        if st.attached:
            self.emit_callback(st.sid, UiEvent(kind, value, st.run_id or "", interaction_id))

    def step(self, st, record):
        if record:
            self.send(st, "step", record)

    def key(self, st, verb):
        self.seq += 1
        # Random process prefix prevents request-key collision across restarts.
        return f"{st.scope}-{st.run_id or 'new'}-{verb}-{self.request_prefix}-{self.seq}"

    @property
    def request_prefix(self):
        if not hasattr(self, "_request_prefix"):
            self._request_prefix = uuid.uuid4().hex
        return self._request_prefix

    def run(self, run_id):
        return self.rt.run_state(run_id).get("run") or {}

    def families(self, realm):
        return catalog.families(realm, self.toolset)

    def digest(self, realm):
        return catalog.catalog_digest(self.families(realm))

    def _rehydrate(self, binding):
        if (binding.get("workspace_root") != str(self.env.workspace_root)
                or binding.get("toolset") != self.toolset
                or binding.get("catalog_digest") != self.digest(binding.get("realm", ""))):
            raise RuntimeError("catalog_changed")
        scope, realm = binding["scope_id"], binding["realm"]
        self.rt.rehydrate(scope, realm, binding["workspace_root"], binding["toolset"])
        rows = self.rt.db.host_scope_installs(scope, None, 64)
        if rows.get("has_more"):
            raise RuntimeError("catalog_changed")
        for row in rows["items"]:
            plugin = self.rt.dispatcher.registry.lookup_install(row)
            family = next(f for f in self.families(realm) if f.identity == row["identity"])
            manifest = catalog.manifest(family)
            for name in ("identity", "version", "manifest_digest", "artifact_digest", "adapter_digest"):
                if row[name] != getattr(plugin, name):
                    raise RuntimeError("catalog_changed")
            if row["manifest"] != manifest or row["provides"] != manifest["provides"]:
                raise RuntimeError("catalog_changed")
            for provide in row["provides"]:
                expected = next(p for p in manifest["provides"] if p["key"] == provide["key"])
                if (pg_jsonb_text(provide["descriptor"]) != pg_jsonb_text(expected["descriptor"])
                        or descriptor_digest(provide["descriptor"]) != plugin.tool_for(provide["key"]).descriptor_digest):
                    raise RuntimeError("catalog_changed")
            fibers = self.rt.db.host_install_fibers(row["install_id"], None, 64)
            if fibers.get("has_more") or len(fibers["items"]) != 1 or str(fibers["items"][0]["install_id"]) != str(row["install_id"]):
                raise RuntimeError("catalog_changed")

    def _reclaim(self):
        if len(self.store.conversations) < 32:
            return True
        attached = {s.conversation_id for s in self.states.values() if s.attached}
        for row in sorted(self.store.conversations, key=lambda r: r["created_at"]):
            if row["conversation_id"] in attached:
                continue
            if row.get("setup_incomplete"):
                continue
            if all(self.run(b["run_id"]).get("status") in (TERMINAL - {"blocked_unknown"}) for b in row["bindings"]):
                try:
                    self._rehydrate(row)
                    self.rt.close_scope(row["scope_id"])
                except Exception:
                    continue
                self.store.remove(row["conversation_id"])
                return True
        return False

    def new(self, sid, stop):
        self.check_thread()
        if not self._reclaim():
            self.states[sid] = ThreadState(sid, "", "", "", stop=stop)
            self.emit_callback(sid, UiEvent("message", "session_capacity; token-based /resume remains available"))
            self.emit_callback(sid, UiEvent("idle"))
            return
        realm = "ui-" + uuid.uuid4().hex[:8]
        scope = self.rt.create_scope(realm)
        # Persist ownership before admission can fail. Partial installs remain
        # reachable via this token and scope ID, including after process restart.
        row, token = self.store.new_conversation(scope_id=scope, realm=realm,
            workspace_root=str(self.env.workspace_root), toolset=self.toolset,
            catalog_digest=self.digest(realm), setup_incomplete=True)
        st = ThreadState(sid, row["conversation_id"], scope, realm, stop=stop)
        self.states[sid] = st
        try:
            installs = self.rt.install_tools(scope, self.families(realm))
        except Exception:
            self.send(st, "message", f"setup_incomplete; /close to clean up; recovery: /resume {scope} {token}")
            self.send(st, "idle")
            return
        row.pop("setup_incomplete")
        self.store.flush()
        for identity in installs:
            self.step(st, StepRecord("install · " + identity.rsplit(".", 1)[-1], "run", "installed; fiber on"))
        keys = catalog.toolset_keys(self.toolset, self.families(realm))
        self.send(st, "message", f"FAKE · db={self.env.db_name} · workspace={self.env.workspace_root}\n"
                  f"toolset={self.toolset} (effective {len(keys)}) · scope={scope[:8]}\n"
                  f"max_out=512 token（含推理；超限本轮失败） · safe-args={catalog.MAX_SAFE_ARGS_BYTES or 'unmeasured'}\n"
                  f"resume token: `{token}`\n"
                  "`/resume <run_id> [token]` · `/cancel` · `/steer <text>` · `/close` · `/tools` · `/skills`\n"
                  "发第一条消息即开始 run。")
        if self.store.warnings:
            self.send(st, "message", "session state: " + ", ".join(self.store.warnings))
        self.send(st, "idle")

    def _turn(self, st, text):
        self.seq += 1
        self.store.append_turn(conversation_id=st.conversation_id, run_id=st.run_id, seq=self.seq, user_text=text)

    def _activate(self, st):
        st.busy = True
        st.rounds = 0
        st.seen.clear()
        st.stop.clear()
        self.step(st, render_generating())

    def command(self, sid, text):
        self.check_thread()
        st = self.states.get(sid)
        if st is None:
            self.emit_callback(sid, UiEvent("message", "session_unavailable"))
            self.emit_callback(sid, UiEvent("idle"))
            return
        text = text.strip()
        if not text:
            return
        verb, _, rest = text.partition(" ")
        waiting_prompt = False
        if verb == "/resume":
            waiting_prompt = self.resume(st, rest)
        elif verb == "/close":
            self.close_conversation(st)
        elif verb == "/tools":
            self.send(st, "message", "\n".join(t.key + ": " + t.description for f in self.families(st.realm) for t in f.tools))
        elif verb == "/skills":
            self.send(st, "message", self.skills_block)
        elif st.run_id and self.run(st.run_id).get("status") == "blocked_unknown":
            self.send(st, "message", "blocked_unknown; replay only")
        elif (self.store.get(st.conversation_id) or {}).get("setup_incomplete"):
            self.send(st, "message", "setup_incomplete; use /close")
        elif st.readonly or not st.scope:
            self.send(st, "message", "catalog_changed" if st.readonly else "conversation_closed")
        elif verb == "/cancel":
            if st.run_id:
                st.stop.set()
                self.send(st, "message", "已请求停止…")
                st.busy = True
        elif verb == "/steer" or st.busy:
            instruction = rest if verb == "/steer" else text
            if instruction and st.run_id:
                self._steer(st, instruction)
        elif st.run_id and self.run(st.run_id).get("status") == "waiting":
            interaction = self.run(st.run_id).get("interaction") or {}
            self.answer(sid, st.run_id, interaction.get("interaction_id"), text)
        else:
            if st.run_id and self.run(st.run_id).get("status") not in TERMINAL:
                self.send(st, "message", "run_active; use /resume or /cancel")
                self.send(st, "idle")
                return
            row = self.store.get(st.conversation_id)
            if any(b["run_id"] != st.run_id and self.run(b["run_id"]).get("status") not in (TERMINAL - {"blocked_unknown"}) for b in row["bindings"]):
                self.send(st, "message", "run_busy; resume the active run first")
                self.send(st, "idle")
                return
            if st.scope not in self.rt.caches:
                try:
                    self._rehydrate(row)
                except Exception:
                    st.readonly = True
                    self.send(st, "message", "catalog_changed")
                    self.send(st, "idle")
                    return
            history = self.store.history_block(st.conversation_id)
            system = build_system_prompt(self.skills_block, history)
            st.run_id, _ = self.rt.start_run(st.scope, self.rt.fiber_for(st.scope, "v24.ui.pi_tools"),
                [{"role": "system", "content": system}, {"role": "user", "content": text}],
                toolset=self.toolset, key=self.key(st, "start"))
            self.store.bind(st.conversation_id, st.scope, st.run_id, realm=st.realm,
                workspace_root=self.env.workspace_root, toolset=self.toolset, catalog_digest=self.digest(st.realm))
            self._turn(st, text)
            self.step(st, render_run_start(scope=st.scope, run_id=st.run_id, budget=DEFAULT_BUDGET,
                requires=catalog.toolset_keys(self.toolset, self.families(st.realm))))
            self.send(st, "message", "run_id=" + st.run_id)
            self._activate(st)
        if not st.busy and not waiting_prompt:
            self.send(st, "idle")

    def _steer(self, st, text):
        if self.run(st.run_id).get("status") in TERMINAL:
            self.send(st, "message", "already_terminal")
            return
        st.inbox.append((st.run_id, text))
        self._turn(st, text)
        self.step(st, StepRecord("run · steer queued", "run", "普通文本已作为 steer 入队"))
        st.busy = True
        st.rounds = 0

    def _flush_inbox(self, st):
        st.inbox = [(run_id, text) for run_id, text in st.inbox if run_id == st.run_id]
        if self.run(st.run_id).get("status") in TERMINAL:
            st.inbox.clear()
        elif st.inbox and self.rt.worker._history(st.run_id):
            pending, st.inbox = st.inbox, []
            for _, text in pending:
                self._apply_steer(st, text)

    def _apply_steer(self, st, text):
        before = self.run(st.run_id)
        receipt = self.rt.steer(st.run_id, text, self.key(st, "steer"))
        if receipt.get("disposition") not in ("committed", "deferred", "replay"):
            self.send(st, "message", "steer rejected; projection refreshed")
            return
        if st.pending_steer and before.get("pending_steer"):
            self.step(st, StepRecord("run · steer superseded", "error", "上一条 steer 被覆盖，未送达模型"))
        st.pending_steer = text

    def answer(self, sid, run_id, interaction_id, text):
        self.check_thread()
        st = self.states[sid]
        if not text or not text.strip():
            return  # Waiting stays durable; no empty respond RPC.
        if st.readonly or st.run_id != run_id:
            self.send(st, "message", "catalog_changed" if st.readonly else "interaction_mismatch")
            self.send(st, "idle")
            return
        value = self.rt.respond(run_id, interaction_id, {"text": text}, self.key(st, "respond"))
        if value.get("disposition") not in ("committed", "deferred", "replay"):
            self.send(st, "message", "respond rejected; projection refreshed")
            self.project(st)
            self.send(st, "idle")
            return
        self._turn(st, text)
        self._activate(st)

    def _presentation_refused(self, st):
        # No raw exception, tool bytes, final bubble or waiting prompt escapes.
        st.busy = False
        self.step(st, StepRecord("run · presentation refused", "error", "render_secret_detected; durable/model history retained"))

    def project(self, st):
        projection = self.rt.run_state(st.run_id)
        run = projection.get("run") or {}
        interaction = run.get("interaction") or {}
        payload = None
        if interaction:
            effect = self.rt.db.host_effect(interaction["interaction_id"]).get("effect") or {}
            result = ((effect.get("outcome") or {}).get("body") or {}).get("result") or {}
            payload = (result.get("interaction") or (result.get("result") or {}).get("interaction") or {}).get("payload", {})
        records = render_state(projection, seen=frozenset(st.seen), interaction_payload=payload)
        for record in records:
            self.step(st, record)
            st.seen.add(record.effect_id)
        status = run.get("status")
        if status in TERMINAL:
            st.inbox.clear()
            st.busy = False
            if status == "completed":
                final = (run.get("result") or {}).get("final_text")
                if isinstance(final, str):
                    self.send(st, "final", _record("final", "llm", final).output)
        elif status == "waiting" and interaction:
            st.busy = False
            # render_state scans the complete payload before this prompt is sent.
            self.send(st, "ask", str((payload or {}).get("prompt", "Continue?")), interaction_id=interaction["interaction_id"])
        return run

    def tick(self):
        self.check_thread()
        for st in tuple(self.states.values()):
            if not st.busy or st.readonly:
                continue
            try:
                self.rt._active_run = st.run_id
                if st.stop.is_set():
                    self.rt.cancel(st.run_id, self.key(st, "cancel"))
                    st.stop.clear()
                # A steer before the initial model starts would cancel the
                # only seed effect and cause frozen adapter history_missing.
                # Keep it in the inbox until the first model round journals
                # seed history; then deliver at the next round boundary.
                self._flush_inbox(st)
                stats = self.rt.worker.run_once(st.scope)
                self._flush_inbox(st)
                self.rt.advance(self.rt.discovery(st.run_id), on_effect=lambda e: self.step(st, render_effect(e)))
                run = self.project(st)
                if not st.busy and run.get("status") != "waiting":
                    self.send(st, "idle")
                st.rounds += 1
                if not run.get("pending_steer"):
                    st.pending_steer = None
                if st.busy and (stats.progress == 0 or st.rounds >= self.rt.max_rounds_per_turn):
                    st.busy = False
                    self.step(st, StepRecord("run · stalled", "error", "stalled; use /resume to inspect"))
                    self.send(st, "idle")
            except ValueError as exc:
                if str(exc) != "render_secret_detected":
                    raise
                self._presentation_refused(st)
                self.send(st, "idle")
            except Exception:
                st.busy = False
                self.send(st, "message", "runtime_error; durable state retained")
                self.send(st, "idle")
            if not st.attached and not st.busy:
                self.states.pop(st.sid, None)

    def resume(self, st, text):
        parts = text.split()
        row = self.store.find_by_token(parts[1]) if len(parts) == 2 else self.store.get(st.conversation_id)
        binding = next((b for b in (row or {}).get("bindings", []) if b["run_id"] == (parts[0] if parts else "")), None)
        setup_resume = bool(row and row.get("setup_incomplete") and len(parts) == 2 and parts[0] == row.get("scope_id"))
        if len(parts) not in (1, 2) or (binding is None and not setup_resume):
            self.send(st, "message", "not_found_or_denied")
            return
        if any(s is not st and s.attached and s.conversation_id == row["conversation_id"] for s in self.states.values()):
            self.send(st, "message", "conversation_attached")
            return
        if st.busy:
            self.send(st, "message", "run_busy")
            return
        # Preserve the fresh conversation and its token; detach without disposal.
        self.store.detach(st.conversation_id)
        st.conversation_id = row["conversation_id"]
        st.inbox.clear()
        st.pending_steer = None
        st.stop.clear()
        if setup_resume:
            st.scope, st.realm, st.run_id = row["scope_id"], row["realm"], None
            st.readonly = False
            self.send(st, "message", "setup_incomplete; use /close")
            return
        st.scope, st.realm, st.run_id = binding["scope_id"], binding.get("realm", ""), binding["run_id"]
        st.readonly = False
        st.seen.clear()
        run = self.run(st.run_id)
        try:
            if (binding.get("catalog_digest") != self.digest(st.realm)
                    or binding.get("workspace_root") != str(self.env.workspace_root)
                    or binding.get("toolset") != self.toolset):
                st.readonly = True
            if run.get("status") not in TERMINAL and not st.readonly:
                self._rehydrate(binding)
        except Exception:
            st.readonly = True
        for sid, old in list(self.states.items()):
            if old is not st and not old.attached and old.conversation_id == st.conversation_id:
                self.states.pop(sid)
        self.store.active_conversation_id = st.conversation_id
        row["active_binding"] = binding
        self.store.flush()
        try:
            discovery = Discovery(run_id=st.run_id)
            self.rt.advance(discovery)
            self.rt.discoveries[st.run_id] = discovery
            for effect in discovery.records:
                self.step(st, render_effect(effect))
            if st.readonly:
                self.send(st, "message", "catalog_changed; replay only")
                # Still show safe terminal state, but never ask/drive/respond.
                for record in render_state({"run": run}, seen=frozenset()):
                    self.step(st, record)
                return
            self.rt._active_run = st.run_id
            if run.get("status") == "running":
                self._activate(st)
            else:
                self.project(st)
                return run.get("status") == "waiting"
        except ValueError as exc:
            if str(exc) != "render_secret_detected":
                raise
            self._presentation_refused(st)

    def close_conversation(self, st):
        if not st.scope:
            self.send(st, "message", "conversation_closed")
            return
        if st.readonly:
            self.send(st, "message", "catalog_changed; close_incomplete")
            return
        row = self.store.get(st.conversation_id)
        if row and row.get("setup_incomplete"):
            try:
                # Rebuild approvals for host_release, including partial admission.
                if (row.get("workspace_root") != str(self.env.workspace_root)
                        or row.get("toolset") != self.toolset
                        or row.get("catalog_digest") != self.digest(st.realm)):
                    raise RuntimeError("catalog_changed")
                for family in self.families(st.realm):
                    self.rt.plugins[(st.scope, family.identity)] = catalog.build_plugin(family, self.env)
                self.rt._refresh_registry()
                rows = self.rt.db.host_scope_installs(st.scope, None, 64)
                if rows.get("has_more"):
                    raise RuntimeError("close_incomplete")
                for install in rows["items"]:
                    self.rt.dispatcher.registry.lookup_install(install)
                    if install.get("disposed_at") is None:
                        self.rt._retire_install(st.scope, install["install_id"])
                self.rt.caches.pop(st.scope, None)
                self.rt.close_scope(st.scope)
            except Exception:
                self.send(st, "message", "close_incomplete; setup metadata retained")
                return
            self.store.remove(st.conversation_id)
            st.scope = ""
            self.step(st, StepRecord("scope · closed", "run", "partial setup disposed; bindings removed"))
            return
        for binding in (row or {}).get("bindings", []):
            run_id = binding["run_id"]
            status = self.run(run_id).get("status")
            if status == "blocked_unknown":
                self.send(st, "message", "close_incomplete")
                return
            if status not in TERMINAL:
                self.rt.cancel(run_id, self.key(st, "close-cancel"))
                self.rt._active_run = run_id
                report = self.rt.drive(st.scope)
                if report.status not in TERMINAL or report.status == "blocked_unknown":
                    self.send(st, "message", "close_incomplete")
                    return
        try:
            if st.scope not in self.rt.caches:
                self._rehydrate(row)
            self.step(st, StepRecord("run · converged", "run", "all bound runs terminal"))
            self.rt.uninstall_tools(st.scope, [f.identity for f in self.families(st.realm)])
            self.step(st, StepRecord("install · off/dispose", "run", "fibers off; installs disposed"))
            self.rt.close_scope(st.scope)
        except Exception:
            self.send(st, "message", "close_incomplete")
            return
        self.store.remove(st.conversation_id)
        st.busy = False
        st.scope = ""
        self.step(st, StepRecord("scope · closed", "run", "bindings removed"))

    def detach(self, sid):
        self.check_thread()
        st = self.states.get(sid)
        if st:
            st.attached = False
            self.store.detach(st.conversation_id)
            if not st.busy:
                self.states.pop(sid, None)

    def close(self):
        self.check_thread()
        try:
            try:
                if self.store:
                    self.store.flush()
            finally:
                if self.rt:
                    try:
                        self.rt.close()
                    finally:
                        self.rt = None
        finally:
            release_lock(self.lock_fd)
            self.lock_fd = None


# Chainlit is imported only by its app runner; backend tests use the root uv env.
_HUB_TASK = None
_DISPATCH = None
_EXECUTOR = None
_BACKEND = None
SESSIONS = {}


@dataclass
class UiSession:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    stop: threading.Event = field(default_factory=threading.Event)
    consuming: bool = False
    ask_task: asyncio.Task | None = None
    consumer_task: asyncio.Task | None = None


async def _ensure_hub():
    global _HUB_TASK, _DISPATCH, _EXECUTOR
    if _HUB_TASK is None:
        _DISPATCH = asyncio.Queue()
        _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v24-ui")
        _HUB_TASK = asyncio.create_task(_hub())


async def _hub():
    global _BACKEND
    loop = asyncio.get_running_loop()
    def emit(sid, event):
        if sid in SESSIONS:
            loop.call_soon_threadsafe(SESSIONS[sid].queue.put_nowait, event)
    try:
        construction = loop.run_in_executor(_EXECUTOR, lambda: Backend(emit))
        try:
            _BACKEND = await asyncio.shield(construction)
        except asyncio.CancelledError:
            # Cancellation cannot stop an already running constructor. Recover
            # its result so finally closes it on the owning executor thread.
            _BACKEND = await construction
            raise
        while True:
            try:
                job = await asyncio.wait_for(_DISPATCH.get(), timeout=0.15)
            except asyncio.TimeoutError:
                job = None
            while job is not None:
                method, args, done = job
                try:
                    result = await loop.run_in_executor(_EXECUTOR, lambda: getattr(_BACKEND, method)(*args))
                    done.set_result(result)
                except Exception:
                    if args and args[0] in SESSIONS:
                        emit(args[0], UiEvent("message", "runtime_error; durable state retained"))
                        emit(args[0], UiEvent("idle"))
                    done.set_result(None)
                try:
                    job = _DISPATCH.get_nowait()
                except asyncio.QueueEmpty:
                    job = None
            await loop.run_in_executor(_EXECUTOR, _BACKEND.tick)
    finally:
        if _BACKEND:
            await loop.run_in_executor(_EXECUTOR, _BACKEND.close)
            _BACKEND = None


async def _submit(method, *args):
    await _ensure_hub()
    if _HUB_TASK.done():
        error = _HUB_TASK.exception()
        code = str(error) if str(error) in {"already_running", "invalid_mode", "invalid_toolset", "invalid_skill", "workspace_invalid", "real_mode_not_enabled", "schema_drift", "migration_required", "not_initialized"} else "startup_failed"
        raise RuntimeError(code)
    done = asyncio.get_running_loop().create_future()
    await _DISPATCH.put((method, args, done))
    # Startup may fail before the hub takes its first job.
    completed, _ = await asyncio.wait([done, _HUB_TASK], return_when=asyncio.FIRST_COMPLETED)
    if done in completed:
        return done.result()
    return await _submit(method, *args)


async def shutdown():
    global _HUB_TASK, _EXECUTOR, _DISPATCH
    try:
        if _HUB_TASK:
            _HUB_TASK.cancel()
            try:
                await _HUB_TASK
            except (asyncio.CancelledError, RuntimeError):
                pass
    finally:
        _HUB_TASK = None
        if _EXECUTOR:
            _EXECUTOR.shutdown(wait=True)
            _EXECUTOR = None
        _DISPATCH = None


def register_chainlit():
    import chainlit as cl

    cl.on_app_shutdown(shutdown)

    async def ask(sid, event):
        try:
            response = await cl.AskUserMessage(content=event.value, timeout=3600, raise_on_timeout=False).send()
        finally:
            # Chainlit 2.12 restarts its task in send_ask_user's finally.
            # This background task has no callback wrapper to end it for us.
            await cl.context.emitter.task_end()
        answer = (response or {}).get("output", "")
        if answer.strip() and sid in SESSIONS:
            await _submit("answer", sid, event.run_id, event.interaction_id, answer)

    async def consume(sid):
        session = SESSIONS[sid]
        if session.consuming:
            return
        session.consuming = True
        try:
            while True:
                event = await session.queue.get()
                if event.kind == "idle":
                    continue
                if event.kind == "step":
                    record = event.value
                    # Chainlit's StepType has no 'error'; preserve semantic type
                    # via is_error and use a supported step category.
                    step = cl.Step(name=record.name, type="run" if record.type == "error" else record.type)
                    step.is_error = record.type == "error"
                    step.output = record.output
                    await step.send()
                elif event.kind == "ask":
                    if session.ask_task and not session.ask_task.done():
                        session.ask_task.cancel()
                    session.ask_task = asyncio.create_task(ask(sid, event))
                else:
                    await cl.Message(content=event.value).send()
        finally:
            session.consuming = False

    @cl.on_chat_start
    async def start():
        sid = cl.user_session.get("id")
        SESSIONS[sid] = UiSession()
        try:
            await _submit("new", sid, SESSIONS[sid].stop)
            SESSIONS[sid].consumer_task = asyncio.create_task(consume(sid))
        except RuntimeError as exc:
            await cl.Message(content=str(exc)).send()

    @cl.on_message
    async def message(message):
        sid = cl.user_session.get("id")
        await _submit("command", sid, message.content)
        session = SESSIONS[sid]
        # Chainlit 2.12 disables submission until on_message returns. Consume
        # in the captured session context so busy messages can reach the inbox.
        if not session.consumer_task or session.consumer_task.done():
            session.consumer_task = asyncio.create_task(consume(sid))

    @cl.on_stop
    async def stop():
        sid = cl.user_session.get("id")
        if sid in SESSIONS:
            SESSIONS[sid].stop.set()
        await cl.Message(content="已请求停止…").send()

    @cl.on_chat_end
    async def end():
        sid = cl.user_session.get("id")
        if _HUB_TASK and not _HUB_TASK.done():
            await _submit("detach", sid)
        session = SESSIONS.pop(sid, None)
        if session:
            for task in (session.ask_task, session.consumer_task):
                if task:
                    task.cancel()


if __name__ != "v24.ui.app":
    register_chainlit()
