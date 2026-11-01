"""Synchronous M1 control plane over the frozen v24 public API."""
from __future__ import annotations
import argparse, json, uuid
import tempfile
from pathlib import Path
import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import Callable
from v24.host.db import HostDB, is_error
from v24.host.journal import HostJournal
from v24.host.plugins import PluginDispatcher
from v24.host.worker import HostWorker
from v24.host.canonical import compact_json
from v24.host.canonical import pg_jsonb_text, descriptor_digest
from v24.host.registry import AdapterNotFound
from psycopg2.extras import Json
from . import catalog
from .env import open_env, init_env, acquire_lock, release_lock
from .fake import ScriptedUiAdapter

DEFAULT_BUDGET = {"steps":24,"tool_calls":24,"tokens":20000,"wall_ms":600000}
_TERMINAL = frozenset(("completed", "failed", "cancelled", "blocked_unknown"))

@dataclass(frozen=True)
class DriveReport:
    rounds:int; status:str; idle:bool; stalled:bool; cancelled:bool; waiting_interaction:bool; last_revision:int; final_text:str|None

@dataclass
class Discovery:
    run_id: str = ""
    cursor_at: str|None = None
    cursor_id: str|None = None
    active: dict[str,dict] = field(default_factory=dict)
    finalized: set[str] = field(default_factory=set)
    records: list[dict] = field(default_factory=list)

class AgentRuntime:
    """One serialized owner of HostDB, journal, worker and registry state."""
    def __init__(self, env, *, mode="fake", adapter=None, workspace_root=None, max_rounds_per_turn=64):
        if workspace_root is not None and Path(workspace_root).resolve() != env.workspace_root.resolve():
            raise RuntimeError("workspace_mismatch")
        self.env=env; self.mode=mode; self.adapter=adapter; self.max_rounds_per_turn=max_rounds_per_turn
        self.db=HostDB(env.admin_dsn, env.service_dsn)
        self.journal=HostJournal.open(env.journal_path)
        self.dispatcher=PluginDispatcher(self.db,catalog.build_registry(()))
        self.worker=HostWorker(self.db,self.journal,adapter=adapter,tool_handler=self.dispatcher.tool_handler,resource_handler=self.dispatcher.resource_handler,default_lease_ms=30000)
        self.caches={}; self.scopes={}; self.plugins={}; self.discoveries={}; self._active_run=None; self.seq=0

    def _rpc(self, statement, params=(), *, service=False):
        conn = self.db.service if service else self.db.control
        try:
            with conn.cursor() as cur:
                cur.execute(statement, params)
                value = cur.fetchone()[0]
            # SQL domain-error envelopes are ordinary RPC results and commit.
            conn.commit()
            if not self.db.idle(conn):
                raise RuntimeError("rpc_connection_not_idle")
            return value
        except Exception:
            # A database exception must never leave either HostDB connection
            # inside an aborted transaction before worker/external I/O.
            try:
                conn.rollback()
            except Exception:
                pass
            if not self.db.idle(conn):
                raise RuntimeError("rpc_connection_not_idle")
            raise

    def _refresh_registry(self):
        self.dispatcher.registry=catalog.build_registry(tuple(self.plugins.values()))

    def create_scope(self, realm):
        value=self._rpc("SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",(realm,f"{realm}-root-{uuid.uuid4().hex}"))
        if value.get("disposition")!="committed": raise RuntimeError(value)
        scope=str(value["emitted"][0]); self.scopes[scope]=realm; return scope

    def install_tools(self, scope, families):
        installed=self.caches.setdefault(scope,{})
        old_cache, old_plugins = dict(installed), dict(self.plugins)
        admitted = []
        try:
            for family in families:
                key=(scope,family.identity)
                if key in installed: continue
                plugin=catalog.build_plugin(family,self.env)
                self.plugins[key]=plugin; self._refresh_registry()
                value=self._rpc("SELECT v24.install(%s,%s,%s,%s,%s)",
                    (scope,None,compact_json(catalog.manifest(family)),bytes.fromhex(plugin.artifact_digest),f"ui-install-{uuid.uuid4().hex}"))
                if value.get("disposition") not in ("committed","replay"): raise RuntimeError("install_rejected")
                install_id=str(value["emitted"][0]); admitted.append(install_id)
                for _ in range(64):
                    self.worker.run_once(scope)
                    rows=self.db.host_scope_installs(scope,None,64).get("items",[])
                    row=next((x for x in rows if str(x.get("install_id"))==install_id),None)
                    if row and row.get("state")=="installed": break
                else: raise RuntimeError("install_not_ready")
                fibers=self.db.host_install_fibers(install_id,None,64).get("items",[])
                if len(fibers)!=1: raise RuntimeError("fiber_missing")
                fiber=fibers[0]
                value=self._rpc("SELECT v24.fiber_control(%s,'on',%s,%s)",(fiber["fiber_id"],fiber["control_seq"],f"ui-on-{uuid.uuid4().hex}"))
                if value.get("disposition") not in ("committed","deferred"): raise RuntimeError("activation_rejected")
                installed[key]=(install_id,str(fiber["fiber_id"]))
        except Exception as original:
            self.caches[scope]=old_cache
            try:
                for install_id in reversed(admitted): self._retire_install(scope,install_id)
            except Exception as cleanup:
                # Keep approvals available for host_release and expose the
                # unfinished resource IDs rather than losing cleanup state.
                self._pending_cleanup=(scope,tuple(admitted))
                raise RuntimeError("install_cleanup_incomplete") from original
            self.plugins=old_plugins; self._refresh_registry()
            raise
        return {identity: value[0] for (sc,identity),value in installed.items() if sc==scope}

    def _retire_install(self, scope, install_id):
        fibers=self.db.host_install_fibers(install_id,None,64).get("items",[])
        for fiber in fibers:
            if fiber.get("disposed_at") is not None: continue
            value=self._rpc("SELECT v24.fiber_control(%s,'off',%s,%s)",
                (fiber["fiber_id"],fiber["control_seq"],f"ui-off-{uuid.uuid4().hex}"))
            if value.get("disposition") not in ("committed","deferred","replay"): raise RuntimeError("close_incomplete")
        value=self._rpc("SELECT v24.dispose(%s,%s)",(install_id,f"ui-dispose-{uuid.uuid4().hex}"))
        if value.get("disposition") not in ("committed","replay"): raise RuntimeError("close_incomplete")
        for _ in range(64):
            self.worker.run_once(scope)
            rows=self.db.host_scope_installs(scope,None,64).get("items",[])
            row=next((x for x in rows if str(x.get("install_id"))==install_id),{})
            if row.get("disposed_at") is not None: return
        raise RuntimeError("close_incomplete")

    def fiber_for(self, scope, identity):
        try: return self.caches[scope][(scope,identity)][1]
        except KeyError: raise RuntimeError("fiber_missing") from None

    def _families(self, scope, toolset): return catalog.families(self.scopes[scope],toolset)

    def start_run(self, scope, owner_fiber_id, messages, *, toolset="exec", budget=None, key=None):
        families=self._families(scope,toolset); requires=[{"key":k} for k in catalog.toolset_keys(toolset,families)]
        if len(requires)>16: raise RuntimeError("invalid_args")
        payload={"messages":messages,"requires":requires,"max_output_tokens":512}
        value=self._rpc("SELECT v24.start(%s,%s,%s,%s,%s)",(scope,owner_fiber_id,Json(payload),Json(budget or DEFAULT_BUDGET),key or f"ui-start-{uuid.uuid4().hex}"))
        if value.get("disposition")!="committed": raise RuntimeError(value)
        emitted=tuple(str(x) for x in value["emitted"])
        self._active_run=emitted[0]
        return emitted

    def run_state(self, run_id, after_revision=0):
        return self._rpc("SELECT v24.poll(%s,%s)",(run_id,after_revision))

    def discovery(self, run_id):
        return self.discoveries.setdefault(str(run_id),Discovery(run_id=str(run_id)))

    def advance(self, discovery, *, on_effect=None):
        run_id=discovery.run_id
        while True:
            page=self.db.host_run_effects(run_id,discovery.cursor_at,discovery.cursor_id,64)
            for item in page.get("items",[]):
                effect_id=str(item["effect_id"]); discovery.cursor_at=item.get("created_at"); discovery.cursor_id=effect_id
                if effect_id not in discovery.finalized: discovery.active.setdefault(effect_id,item)
            if not page.get("has_more"): break
        for effect_id, old in list(discovery.active.items()):
            current=self.db.host_effect(effect_id).get("effect")
            if not isinstance(current,dict): continue
            status=current.get("status")
            if status in ("succeeded","failed","cancelled","unknown"):
                if effect_id not in discovery.finalized:
                    discovery.finalized.add(effect_id); discovery.records.append(current)
                    if on_effect: on_effect(current)
                discovery.active.pop(effect_id,None)
            else: discovery.active[effect_id]=current
        return discovery

    def replay(self, run_id):
        d=Discovery(run_id=str(run_id)); self._active_run=str(run_id); self.advance(d); return list(d.records)

    def drive(self, scope, *, stop=None, on_effect=None, on_state=None):
        run_id=str(self._active_run); d=self.discovery(run_id); last=0
        for round_no in range(1,self.max_rounds_per_turn+1):
            if stop is not None and stop.is_set(): self.cancel(run_id,f"{scope}-cancel-{uuid.uuid4().hex}")
            stats=self.worker.run_once(scope); self.advance(d,on_effect=on_effect)
            projection=self.run_state(run_id,last); run=projection.get("run") or {}; last=int(projection.get("revision",run.get("revision",last)) or last)
            if on_state: on_state(projection)
            status=run.get("status")
            if status in _TERMINAL:
                return DriveReport(round_no,status,stats.idle,False,status=="cancelled",False,last,(run.get("result") or {}).get("final_text"))
            if status=="waiting" and run.get("interaction"):
                return DriveReport(round_no,status,False,False,False,True,last,None)
            if stats.progress==0: return DriveReport(round_no,"stalled",True,True,False,False,last,None)
        return DriveReport(self.max_rounds_per_turn,"stalled",False,True,False,False,last,None)

    def _generation(self, run_id):
        return int((self.run_state(run_id,0).get("run") or {}).get("driving_generation",0))
    def cancel(self, run_id, key): return self._rpc("SELECT v24.cancel(%s,%s,%s)",(run_id,self._generation(run_id),key))
    def steer(self, run_id, instruction, key): return self._rpc("SELECT v24.steer(%s,%s,%s,%s)",(run_id,self._generation(run_id),instruction,key))
    def respond(self, run_id, interaction_id, response, key): return self._rpc("SELECT v24.respond(%s,%s,%s,%s,%s)",(run_id,interaction_id,Json(response),self._generation(run_id),key))

    def rehydrate(self, scope, realm, workspace_root, toolset):
        from pathlib import Path
        if Path(workspace_root).resolve() != self.env.workspace_root.resolve() or toolset not in ("read","write","exec"):
            raise RuntimeError("catalog_changed")
        self.scopes[str(scope)]=realm
        families=self._families(str(scope),toolset); expected={f.identity:catalog.build_plugin(f,self.env) for f in families}
        rows=self.db.host_scope_installs(scope,None,64).get("items",[])
        if len(rows)!=len(expected): raise RuntimeError("catalog_changed")
        cache={}
        for row in rows:
            plugin=expected.get(row.get("identity"))
            if plugin is None or row.get("manifest_digest")!=plugin.manifest_digest or row.get("artifact_digest")!=plugin.artifact_digest or row.get("adapter_digest")!=plugin.adapter_digest or compact_json(row.get("manifest")) != compact_json(catalog.manifest(next(f for f in families if f.identity==plugin.identity))): raise RuntimeError("catalog_changed")
            fibers=self.db.host_install_fibers(row["install_id"],None,64).get("items",[])
            if len(fibers)!=1 or fibers[0].get("disposed_at") is not None or row.get("state")!="installed": raise RuntimeError("catalog_changed")
            cache[(scope,plugin.identity)]=(str(row["install_id"]),str(fibers[0]["fiber_id"])); self.plugins[(scope,plugin.identity)]=plugin
        self.caches[scope]=cache; self._refresh_registry(); return None

    def uninstall_tools(self, scope, identities):
        for identity in identities:
            value=self.caches.get(scope,{}).get((scope,identity));
            if not value: continue
            install,fiber=value; self._retire_install(scope, install)
            self.caches[scope].pop((scope,identity),None); self.plugins.pop((scope,identity),None)
        self._refresh_registry()
    def _fiber_seq(self, scope, install, fiber):
        rows=self.db.host_install_fibers(install,None,64).get("items",[])
        row=next((item for item in rows if str(item.get("fiber_id"))==str(fiber)),None)
        if row is None: raise RuntimeError("fiber_missing")
        return row["control_seq"]
    def close_scope(self, scope):
        for (sc,identity) in list(self.caches.get(scope,{})):
            self.uninstall_tools(scope,[identity])
        value=self._rpc("SELECT v24.scope_control('close',%s,NULL,NULL,%s)",(scope,f"ui-close-{uuid.uuid4().hex}"))
        if value.get("disposition") not in ("committed", "replay"): raise RuntimeError("close_incomplete")
        self.scopes.pop(scope,None); self.caches.pop(scope,None); return value
    def close(self):
        try:self.journal.close()
        finally:self.db.close()

def selftest():
    env=open_env(); fd=acquire_lock(env.data_dir); rt=None; fixture=None
    try:
        init_env(env)
        fixture=env.workspace_root / f"m1-selftest-{uuid.uuid4().hex}.txt"
        fixture_text="# v24 ui selftest\n"
        fixture.write_text(fixture_text,encoding="utf-8")
        adapter=ScriptedUiAdapter([{"kind":"tool","key":"read","args":{"path":fixture.name,"limit":5}},{"kind":"final","text":"done"},{"kind":"final","text":"second done"}])
        rt=AgentRuntime(env,adapter=adapter); realm=f"ui-{uuid.uuid4().hex[:8]}"; scope=rt.create_scope(realm); rt.install_tools(scope,catalog.families(realm,"exec"))
        run_id,_=rt.start_run(scope,rt.fiber_for(scope,"v24.ui.pi_tools"),[{"role":"user","content":"read README"}],toolset="exec",key=f"ui-selftest-{uuid.uuid4().hex}"); rt._active_run=run_id
        pins=rt.db.host_run_pins(run_id,None,64).get("items",[])
        initial_run=rt.run_state(run_id,0).get("run") or {}
        raw_token_samples=[]
        token_samples=[]
        def capture_state(projection):
            run=projection.get("run") or {}
            raw=run.get("remaining_tokens")
            raw_token_samples.append(raw)
            # Admission reserves are refunded at settlement.  Add outstanding
            # model reservations to measure the unspent budget, not liquidity.
            effects=rt.db.host_run_effects(run_id,None,None,64)
            assert not effects.get('has_more')
            reserved=sum(int((e.get('request',{}).get('reserve') or {}).get('tokens',0))
                         for e in effects.get('items',[]) if e.get('kind')=='model_call' and e.get('status') in ('ready','claimed'))
            token_samples.append(raw+reserved)
        capture_state({'run':initial_run})
        timeline=[]
        report=rt.drive(scope,on_effect=lambda effect: timeline.append(effect),on_state=capture_state)
        install_rows=rt.db.host_scope_installs(scope,None,64).get("items",[])
        assert len(install_rows)==1 and install_rows[0].get("state")=="installed", install_rows
        assert str(install_rows[0].get("install_id")) == rt.caches[scope][(scope,"v24.ui.pi_tools")][0], install_rows
        for row in install_rows:
            family=next(f for f in catalog.families(realm,"exec") if f.identity==row['identity'])
            plugin=catalog.build_plugin(family,env)
            assert rt.dispatcher.registry.lookup_install(row)==plugin
            raw=catalog.manifest(family)
            assert row['manifest']==raw
            for name in ('identity','version','manifest_digest','artifact_digest','adapter_digest'):
                assert row[name]==getattr(plugin,name),(name,row[name])
            assert plugin.manifest_digest==hashlib.sha256(compact_json(raw)).hexdigest()
            assert '\\x'+plugin.adapter_digest==raw['adapter_digest']
            assert row['provides']==raw['provides']
            for provided in row['provides']:
                expected=next(p for p in raw['provides'] if p['key']==provided['key'])
                assert pg_jsonb_text(provided['descriptor'])==pg_jsonb_text(expected['descriptor'])
                assert descriptor_digest(provided['descriptor'])==plugin.tool_for(provided['key']).descriptor_digest
            fibers=rt.db.host_install_fibers(row['install_id'],None,64).get('items',[])
            assert len(fibers)==1 and str(fibers[0]['install_id'])==str(row['install_id'])
            def rejects(changed):
                try: catalog.build_registry((changed,)).lookup_install(row)
                except AdapterNotFound as exc: assert exc.reason=='adapter_not_approved'
                else: raise AssertionError('negative registry accepted')
            with tempfile.TemporaryDirectory(prefix="v24-ui-artifact-") as directory:
                changed_artifact=Path(directory)/family.artifact.name
                changed_artifact.write_bytes(family.artifact.read_bytes()+b'\n')
                rejects(catalog.build_plugin(dataclasses.replace(family,artifact=changed_artifact),env))
            rejects(catalog.build_plugin(dataclasses.replace(family,realm=realm+'x'),env))
        print('[catalog] DB install/fiber/digest assertions and rebuilt artifact/realm negatives passed')
        for service in (False,True):
            conn=rt.db.service if service else rt.db.control
            for statement, exception in [('SELECT 1/0', Exception),('SELECT 1 WHERE false', TypeError)]:
                try: rt._rpc(statement,service=service)
                except exception: pass
                else: raise AssertionError('RPC exception missing')
                assert rt.db.idle(conn)
            rejected=rt._rpc("SELECT jsonb_build_object('disposition','rejected')",service=service)
            assert rejected['disposition']=='rejected' and rt.db.idle(conn)
        print('[rpc] Python/SQL errors rolled back; returned rejected envelopes committed; both connections IDLE')
        try:
            second=rt.start_run(scope,rt.fiber_for(scope,"v24.ui.pi_tools"),[{"role":"user","content":"second"}],toolset="exec",key=f"ui-second-{uuid.uuid4().hex}")
            rt._active_run=second[0]
            second_report=rt.drive(scope)
            second_result=f"committed run={second[0]} status={second_report.status}"
        except Exception as exc: second_result=f"failed {type(exc).__name__}:{exc}"
        tools=sorted({item.get("function",{}).get("name") for item in (adapter.calls[0].get("tools",[]) if adapter.calls else [])})
        assert token_samples and all(type(value) is int for value in token_samples), token_samples
        assert all(later <= earlier for earlier,later in zip(token_samples,token_samples[1:])), token_samples
        tokens_spent=token_samples[0]-token_samples[-1]
        print(f"[selftest] run={run_id} status={report.status} final={report.final_text!r} pins={sorted(p.get('key') for p in pins)} tools={tools} raw_remaining_tokens={raw_token_samples} unspent_tokens={token_samples} tokens_spent={tokens_spent} second_start={second_result}")
        for effect in timeline:
            print(f"[effect] id={effect.get('effect_id')} kind={effect.get('kind')} status={effect.get('status')} ordinal={effect.get('ordinal')} created_at={effect.get('created_at')}")
        tool_effects=[effect for effect in timeline if effect.get("kind")=="tool_call"]
        assert len(tool_effects)==1 and tool_effects[0].get("status")=="succeeded", tool_effects
        output=tool_effects[0]["outcome"]["body"]["result"]["output"]
        assert output["value"]=={"text":fixture_text,"truncated":False,"spill_path":""}, output
        assert output["content"]==[{"type":"text","text":fixture_text}], output
        rt.close_scope(scope)
        assert report.status=="completed" and report.final_text=="done" and {p.get("key") for p in pins}=={"read"}
        assert tools==["read"], tools
        assert tokens_spent>0, token_samples
        return 0
    finally:
        if fixture: fixture.unlink(missing_ok=True)
        if rt: rt.close()
        release_lock(fd)

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--selftest",action="store_true"); a=p.parse_args(argv)
    if a.selftest:return selftest()
    p.error("use --selftest")
if __name__=="__main__": raise SystemExit(main())
