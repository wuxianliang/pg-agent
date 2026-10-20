"""Targeted regressions from the final read-only review."""
from __future__ import annotations

import contextlib
import io
import sys
import types
from unittest.mock import patch


def test_helper_lifecycle(setup=None):
    """Exercise bounded reap, startup cleanup, and helper-owned handle cleanup."""
    if setup is None:
        from v99.core import setup_db as setup
    assert setup._setup_process is None, 'lifecycle probes must precede real startup'

    class Pipe:
        def __init__(self, error=None):
            self.error = error
            self.closed = False
        def close(self):
            self.closed = True
            if self.error:
                raise self.error

    class Process:
        def __init__(self, waits, pid=808):
            self.stdin, self.stdout = Pipe(), Pipe()
            self.pid = pid
            self.waits = list(waits)
            self.returncode = None
            self.wait_calls = 0
        def wait(self, timeout):
            self.wait_calls += 1
            value = self.waits.pop(0)
            if isinstance(value, BaseException):
                raise value
            self.returncode = value
            return value
        def poll(self):
            return self.returncode

    # Clean EOF is silent, reaped, and drops the saved handle.
    proc = Process([0])
    setup._setup_process, setup._setup_endpoint = proc, {'uri':'unused'}
    with patch.object(setup.os, 'killpg', side_effect=ProcessLookupError):
        setup._close_server_helper(timeout=0.01)
    assert proc.wait_calls == 1 and proc.stdout.closed
    assert setup._setup_process is setup._setup_endpoint is None

    # A stuck helper escalates TERM -> KILL and is reaped. Forced cleanup is
    # surfaced as failure, rather than becoming a successful script at atexit.
    proc = Process([setup.subprocess.TimeoutExpired('uv', 0.01),
                    setup.subprocess.TimeoutExpired('uv', 0.01), -9])
    setup._setup_process, setup._setup_endpoint = proc, {'uri':'unused'}
    signals = []
    with patch.object(setup.os, 'killpg', side_effect=lambda pid, sig: signals.append((pid, sig)) if sig else (_ for _ in ()).throw(ProcessLookupError())):
        try:
            setup._close_server_helper(timeout=0.01)
        except RuntimeError as exc:
            assert 'forced=True' in str(exc) and 'exit=-9' in str(exc)
        else:
            raise AssertionError('forced helper termination was not a failure')
    assert signals == [(proc.pid, setup.signal.SIGTERM), (proc.pid, setup.signal.SIGKILL)]
    assert proc.wait_calls == 3 and proc.stdout.closed
    assert setup._setup_process is setup._setup_endpoint is None

    # If the child cannot be reaped, preserve its global handle for a later
    # cleanup attempt instead of losing the only process reference.
    proc = Process([setup.subprocess.TimeoutExpired('uv', 0.01)] * 3)
    setup._setup_process, setup._setup_endpoint = proc, {'uri':'unused'}
    with patch.object(setup.os, 'killpg', side_effect=lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()) if sig == 0 else None):
        try:
            setup._close_server_helper(timeout=0.01)
        except RuntimeError as exc:
            assert 'could not be reaped' in str(exc)
        else:
            raise AssertionError('unreaped helper was reported as clean')
    assert setup._setup_process is proc and setup._setup_endpoint is not None
    proc.waits = [0]
    with patch.object(setup.os, 'killpg', side_effect=ProcessLookupError):
        setup._close_server_helper(timeout=0.01)

    # Startup endpoint failure cleans the new process and retains the endpoint
    # error even when cleanup itself reports a nonzero child status.
    proc = Process([-15])
    def failed_endpoint(process, timeout=60):
        raise ValueError('injected endpoint failure')
    with patch.object(setup.subprocess, 'Popen', return_value=proc), \
         patch.object(setup, '_read_helper_endpoint', side_effect=failed_endpoint), \
         patch.object(setup.os, 'killpg'):
        try:
            setup._server_and_base_dsn()
        except ValueError as exc:
            assert str(exc) == 'injected endpoint failure'
            assert any('cleanup failed' in note for note in exc.__notes__)
        else:
            raise AssertionError('endpoint error was not preserved')
    assert proc.wait_calls == 1 and proc.stdout.closed
    assert setup._setup_process is setup._setup_endpoint is None

    # Normal-scope cleanup failure reaches the caller and retains the primary
    # test failure in its notes. This closes the atexit-only false-green path.
    proc = Process([-15])
    setup._setup_process, setup._setup_endpoint = proc, {'uri':'unused'}
    try:
        with patch.object(setup.os, 'killpg'):
            with setup.server_helper_scope():
                raise ValueError('primary gate failure')
    except ValueError as exc:
        assert str(exc) == 'primary gate failure'
        assert any('cleanup failed' in note for note in exc.__notes__)
    else:
        raise AssertionError('helper cleanup masked the primary failure')
    assert setup._setup_process is setup._setup_endpoint is None

    # Prove an atexit-only cleanup exception cannot be printed and then exit 0.
    child_code = ("import v99.core.setup_db as s; "
                  "s._close_server_helper=lambda: (_ for _ in ()).throw(RuntimeError('injected atexit failure')); "
                  "s._atexit_server_helper()")
    child = setup.subprocess.run(['uv','run','python','-c',child_code], cwd=setup._REPO_ROOT,
                                 capture_output=True, text=True, timeout=10)
    assert child.returncode == 1 and 'injected atexit failure' in child.stderr, (child.returncode, child.stderr)

    # The helper itself owns a successfully acquired pgembed handle and cleans
    # it when endpoint output fails before readiness is sent.
    class FakeServer:
        cleaned = False
        def get_postmaster_info(self):
            return types.SimpleNamespace(socket_dir=None, port=None)
        def cleanup(self):
            self.cleaned = True
    server = FakeServer()
    old_stdin = setup.sys.stdin
    setup.sys.stdin = io.StringIO('')
    try:
        with patch.dict(sys.modules, {'server': types.SimpleNamespace(get_server=lambda: server)}):
            try:
                setup._server_helper()
            except RuntimeError as exc:
                assert 'did not report' in str(exc)
            else:
                raise AssertionError('invalid endpoint was accepted')
    finally:
        setup.sys.stdin = old_stdin
    assert server.cleaned


def test_wait_exception_cleanup(db, t):
    """SQL and LISTEN setup failures restore IDLE, UNLISTEN, and keep cause."""
    operator = db.connect('operator')
    started = t.good(t.call(operator, 'start', None, 'wait fault', 'review-wait-start'))
    run = started['run_id']
    operator.commit()
    original_call = t.call

    for listening in (False, True):
        def failing_call(conn, name, *args):
            if name == 'wait_check':
                with conn.cursor() as cur:
                    cur.execute('SELECT 1/0')
            return original_call(conn, name, *args)
        t.call = failing_call
        try:
            t.ce_wait(operator, None, run, 1, 1, 0, timeout=0.1, listen=listening)
        except Exception as exc:
            assert getattr(exc, 'pgcode', None) == '22012', (type(exc).__name__, exc)
        else:
            raise AssertionError('wait SQL failure was swallowed')
        finally:
            t.call = original_call
        assert operator.info.transaction_status == t.TRANSACTION_STATUS_IDLE
        assert t.sql(operator, "SELECT ARRAY(SELECT pg_listening_channels())") == []
        operator.commit()

    class CursorProxy:
        def __init__(self, cursor):
            self.cursor = cursor
        def __enter__(self):
            self.cursor.__enter__()
            return self
        def __exit__(self, *args):
            return self.cursor.__exit__(*args)
        def execute(self, statement, params=None):
            if statement == 'LISTEN v99_core_run_changed':
                self.cursor.execute(statement, params)
                raise RuntimeError('injected after LISTEN')
            return self.cursor.execute(statement, params)
        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class ConnectionProxy:
        def __init__(self, conn):
            self.conn = conn
            self.info = conn.info
            self.closed = conn.closed
        def cursor(self, *args, **kwargs):
            return CursorProxy(self.conn.cursor(*args, **kwargs))
        def commit(self): return self.conn.commit()
        def rollback(self): return self.conn.rollback()

    try:
        t.ce_wait(ConnectionProxy(operator), None, run, 1, 1, 0,
                  timeout=0.1, listen=True)
    except RuntimeError as exc:
        assert str(exc) == 'injected after LISTEN'
    else:
        raise AssertionError('LISTEN initialization failure was swallowed')
    assert operator.info.transaction_status == t.TRANSACTION_STATUS_IDLE
    assert t.sql(operator, "SELECT ARRAY(SELECT pg_listening_channels())") == []
    operator.commit()
    operator.close()


def test_fakehost_restart(db, t):
    """A new host cannot renew the old owner's claim or repeat unknown IO."""
    operator, owner = db.connect('operator'), db.connect('admin')
    started = t.good(t.call(operator, 'start', None, 'restart claim', 'review-restart-start'))
    run = started['run_id']
    operator.commit()
    first, restarted = t.FakeHost(db, t.FakeLLM([])), t.FakeHost(db, t.FakeLLM([]))
    assert first.driver != restarted.driver
    first.start_driver(run)
    token = t.good(t.call(first.conn, 'claim_effect', run, started['execution_operation_id'], first.driver, first.fence))
    first.conn.commit()
    before = t.state(owner, run)
    owner.commit()
    try:
        restarted.start_driver(run)
    except AssertionError as exc:
        assert exc.args[0] == {'schema_version':1,'ok':False,'reason':'driver_required'}
    else:
        raise AssertionError('new FakeHost renewed the original live lease')
    t._idle(restarted.conn)
    assert t.state(owner, run) == before
    owner.commit()
    t.sql(owner, "UPDATE v99_core.core_runs SET driver_lease_until=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run,))
    owner.commit()
    restarted.start_driver(run)
    assert restarted.fence == first.fence + 1
    assert t.sql(owner, 'SELECT status FROM v99_core.core_runs WHERE run_id=%s', (run,)) == 'blocked_unknown'
    assert t.sql(owner, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (token['effect_id'],)) == 'unknown'
    assert t.sql(owner, "SELECT count(*) FROM v99_core.core_effect_pins WHERE effect_id=%s", (token['effect_id'],)) == 1
    before = t.state(owner, run)
    t.refused(t.call(restarted.conn, 'discover', run, restarted.driver, restarted.fence), 'unknown_wall')
    restarted.conn.commit()
    assert t.state(owner, run) == before
    assert first.io_count == restarted.io_count == first.llm.calls == restarted.llm.calls == 0
    assert first.tool.calls == restarted.tool.calls == 0
    owner.commit()
    for conn in (operator, owner, first.conn, restarted.conn):
        conn.close()


def test_failed_tool_result_history(db, t):
    """Current and stale failed tools publish a history event consumed by LLM."""
    from v99.core.infrastructure_checks import _request

    # Current-chain failed tool still cancels successors and closes failed, but
    # its structured tool error is available in the history projection.
    operator = db.connect('operator')
    started = t.good(t.call(operator, 'start', None, 'current failed tool', 'review-tool-current'))
    run = started['run_id']
    operator.commit()
    llm = t.FakeLLM([{'schema_version':1,'tool_calls':[
        {'id':'failed','name':'spawn_subsession','args':{'task':'fail-current'}},
        {'id':'untouched','name':'spawn_subsession','args':{'task':'cancel-current'}}]}])
    class FailingTool:
        calls = 0
        def execute(self, request):
            self.calls += 1
            return {'schema_version':1,'error':{'code':'fake_tool_failure','message':request['params']['task']}}
    host = t.FakeHost(db, llm, tool=FailingTool())
    host.start_driver(run)
    assert t.good(host.step(run))['status'] == 'running'
    terminal = t.good(host.step(run))
    assert terminal['status'] == 'failed'
    assert llm.calls == host.tool.calls == 1 and host.io_count == 2
    service = db.connect('service')
    history = t.good(t.call(service, 'worker_history', run, host.driver, host.fence))['events']
    failure_event = [event for event in history if event['type']=='tool/result']
    assert len(failure_event) == 1 and failure_event[0]['payload']['result']['error']['code']=='fake_tool_failure'
    owner = db.connect('admin')
    with owner.cursor() as cur:
        cur.execute("SELECT e.status,o.archive_reason FROM v99_core.core_effects e JOIN v99_core.core_operations o USING(operation_id) WHERE o.run_id=%s AND o.verb='admit_tool' ORDER BY o.attempt_seq", (run,))
        assert cur.fetchall() == [('failed',None),('cancelled','upstream_failed')]
    service.close(); owner.close(); host.conn.close(); operator.close()

    # A failed old tool after active steer is archived stale, but its error
    # remains visible and is actually passed into the next driving LLM call.
    operator = db.connect('operator')
    started = t.good(t.call(operator, 'start', None, 'stale failed tool', 'review-tool-stale'))
    run = started['run_id']; operator.commit()
    class InspectingLLM(t.FakeLLM):
        def complete(self, history):
            if self.calls == 0:
                return super().complete(history)
            failed = [event for event in history if event['type']=='tool/result'
                      and event['payload']['result'].get('error',{}).get('code')=='fake_tool_failure']
            assert len(failed) == 1 and failed[0]['payload']['result']['error']['message']=='fail-stale'
            return super().complete(history)
    llm = InspectingLLM([{'schema_version':1,'tool_calls':[
        {'id':'failed-stale','name':'spawn_subsession','args':{'task':'fail-stale'}}]},
        {'schema_version':1,'text':'failure consumed','ce_status':'completed'}])
    host = t.FakeHost(db, llm, tool=FailingTool())
    host.start_driver(run)
    assert t.good(host.step(run))['status']=='running'
    oldop = t.good(t.call(operator, 'steer', None, run, 'new driving chain', _request('review-stale-steer'), 1))['execution_operation_id']
    operator.commit()
    failed = t.good(host.step(run))
    assert failed['disposition']=='archived_stale'
    assert t.good(host.step(run))['status']=='completed'
    assert llm.calls==2 and host.tool.calls==1 and host.io_count==3
    service = db.connect('admin')
    assert t.sql(service, 'SELECT status FROM v99_core.core_operations WHERE operation_id=%s', (oldop,))=='completed'
    with service.cursor() as cur:
        cur.execute("SELECT e.status,o.archive_reason FROM v99_core.core_effects e JOIN v99_core.core_operations o USING(operation_id) WHERE o.run_id=%s AND o.verb='admit_tool'", (run,))
        assert cur.fetchall() == [('failed','archived_stale')]
    assert t.sql(service, "SELECT count(*) FROM v99_core.core_events WHERE run_id=%s AND type='tool/result' AND payload->'result'->'error'->>'message'='fail-stale'", (run,)) == 1
    service.commit()
    service.close(); host.conn.close(); operator.close()


def run_checks(db, t):
    test_wait_exception_cleanup(db, t)
    test_fakehost_restart(db, t)
    test_failed_tool_result_history(db, t)
    print('[review fixes] ce_wait exception recovery, bounded helper cleanup, unique FakeHost identity, failed-tool history')
