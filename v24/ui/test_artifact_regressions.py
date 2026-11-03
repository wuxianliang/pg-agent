#!/usr/bin/env python3
"""No-network M4 artifact regressions; standalone and safe for disposable workspaces.

Run: uv run python v24/ui/test_artifact_regressions.py
Reproduce the historical kill boundary without accepting it as a pass:
  uv run python v24/ui/test_artifact_regressions.py --kill-probe-artifact /abs/old_pi.py
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = Path(__file__).resolve().parent / 'plugins'


def load(name):
    spec = importlib.util.spec_from_file_location('m4_repair_' + name, PLUGIN_ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(tool, args):
    return (json.dumps(dict(v=2, operation='invoke', reservation='m4-regression', tool=tool, args=args)) + '\n').encode()


def invoke(artifact, tool, args):
    result = subprocess.run([sys.executable, str(artifact), 'serve'], input=frame(tool, args),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=23, env=tool_env())
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def tool_env():
    return {k: v for k, v in os.environ.items()
            if k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'V24_WORKSPACE_ROOT', 'V24_SPILL_ROOT', 'V24_SKILLS_ROOT')}


def command(source):
    return shlex.quote(sys.executable) + ' -I -c ' + shlex.quote(source)


def group_absent(pgid):
    try: os.killpg(pgid, 0)
    except ProcessLookupError: return True
    return False


def kill_probe(artifact, workspace):
    """No stdout: SIGPIPE cannot hide a surviving shell after artifact SIGKILL."""
    rows = []
    for killed in (False, True):
        name = 'kill' if killed else 'control'
        pid_path, sentinel = workspace / (name + '.pid'), workspace / (name + '.sentinel')
        process = subprocess.Popen([sys.executable, str(artifact), 'serve'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=tool_env(), start_new_session=True)
        pgid = None
        try:
            process.stdin.write(frame('bash', dict(command=f'echo $$ > {name}.pid; sleep 0.8; echo done > {name}.sentinel')))
            process.stdin.close()
            deadline = time.monotonic() + 4
            while not pid_path.exists() and time.monotonic() < deadline: time.sleep(0.01)
            assert pid_path.exists(), 'shell did not become ready'
            pgid = os.getpgid(int(pid_path.read_text()))
            if killed: os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            # Wait beyond the command's sentinel time, regardless of pipe activity.
            deadline = time.monotonic() + 1.1
            while time.monotonic() < deadline: time.sleep(0.02)
            rows.append(dict(killed=killed, sentinel=sentinel.exists(), group_absent=group_absent(pgid),
                             artifact_returncode=process.returncode))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            if pgid is not None and not group_absent(pgid):
                try: os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError: pass
            process.stdout.close()
            process.stderr.close()
    return rows


def supervisor_variant(directory, name, transform):
    """Fault only a disposable artifact copy; never add public production fault switches."""
    source = (PLUGIN_ROOT / 'pi_tools.py').read_text()
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == '_BASH_SUPERVISOR' for target in node.targets))
    script = ast.literal_eval(node.value)
    lines = source.splitlines(keepends=True)
    copies = directory / 'fault-copies'
    copies.mkdir(exist_ok=True)
    path = copies / (name + '.py')
    path.write_text(''.join(lines[:node.lineno - 1]) + '_BASH_SUPERVISOR = ' + repr(transform(script)) + '\n' + ''.join(lines[node.end_lineno:]))
    return path


def shell_exit_probe(artifact, workspace, *, action='artifact_group', label='exit'):
    """First prove main-shell exit; a continuing EPIPE-tolerant writer cannot hide behind SIGPIPE."""
    worker = ("import os,time\n"
              f"open('{label}.background','w').write(str(os.getpid())+' '+str(os.getpgrp()))\n"
              "for _ in range(45):\n"
              "    try: os.write(1,b'.\\n')\n"
              "    except BrokenPipeError: pass\n"
              "    time.sleep(.03)\n"
              f"open('{label}.sentinel','w').write('survived')\n")
    background = command(worker)
    tail = 'sleep 3' if action == 'monitor' else 'exit 0'
    process = subprocess.Popen([sys.executable, str(artifact), 'serve'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=tool_env(), start_new_session=True)
    pgid = None
    try:
        process.stdin.write(frame('bash', dict(command=background + f' & echo $$ > {label}.shell; while ! test -s {label}.background; do sleep .005; done; ' + tail)))
        process.stdin.close()
        deadline = time.monotonic() + 4
        metadata, shell_path = workspace / (label + '.background'), workspace / (label + '.shell')
        while not metadata.exists() or not shell_path.exists():
            assert time.monotonic() < deadline
            time.sleep(.005)
        shell = int(shell_path.read_text())
        _, pgid = map(int, metadata.read_text().split())
        shell_exited = False
        if action != 'monitor':
            while True:
                try: os.kill(shell, 0)
                except ProcessLookupError:
                    shell_exited = True
                    break
                assert time.monotonic() < deadline
                time.sleep(.005)
        running = process.poll() is None
        if action == 'monitor':
            assert running
            os.kill(pgid, signal.SIGKILL)  # PID only: surviving artifact must clean remaining group.
        elif running:
            try:
                if action == 'artifact_pid': os.kill(process.pid, signal.SIGKILL)
                else: os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError): pass  # Natural completion may win; Darwin zombie EPERM.
        process.wait(timeout=4)
        time.sleep(1.5)
        stdout, stderr = process.stdout.read(), process.stderr.read()
        assert not stderr, stderr
        return dict(main_shell_exited=shell_exited, artifact_running_after_shell=running,
                    sentinel=(workspace / (label + '.sentinel')).exists(), group_absent=group_absent(pgid),
                    artifact_returncode=process.returncode, reply=json.loads(stdout) if stdout else None)
    finally:
        if process.poll() is None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError): pass
            process.wait(timeout=3)
        if pgid is not None and not group_absent(pgid):
            try: os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.stdout.close(); process.stderr.close()


def abort_probe(artifact, workspace, reason):
    """Artifact abort keeps its monitor alive until every known same-group child is gone."""
    worker = ("import os,time;"
              f"open('{reason}.background','w').write(str(os.getpid())+' '+str(os.getpgrp()));"
              "time.sleep(1.2);"
              f"open('{reason}.sentinel','w').write('survived')")
    tail = command('import os;os.write(1,b"x"*4194304)') if reason == 'output_too_large' else 'sleep 3'
    shell = command(worker) + f' & while ! test -s {reason}.background; do sleep .01; done; ' + tail
    code, reply = invoke(artifact, 'bash', dict(command=shell, timeout_ms=350 if reason == 'timeout' else 20000))
    metadata = workspace / (reason + '.background')
    assert metadata.exists(), 'abort probe never established child'
    _, pgid = map(int, metadata.read_text().split())
    time.sleep(1.4)
    row = dict(reason=reason, code=code, group_absent=group_absent(pgid), sentinel=(workspace / (reason + '.sentinel')).exists())
    assert code == 3 and reply['error']['code'] == reason and row['group_absent'] and not row['sentinel'], (row, reply)
    return row


def reconstruct(module, path, *, rp=False, limit=500):
    offset, pieces, pages = 1, [], 0
    while True:
        value = module.read_file_tool(dict(path=path, start_line=offset, limit=limit)) if rp else module.read_tool(dict(path=path, offset=offset, limit=limit))
        pages += 1
        assert len(value['text'].encode()) <= 32768 and len(value['text'].splitlines()) <= 2000
        if value['truncated']:
            assert value['spill_path'] == path
            notice = re.search(r'\[Showing lines \d+-\d+ of \d+\. Use (?:offset|start_line)=(\d+) to continue\. Full text: [^\]]+\]$', value['text'])
            assert notice, value
            pieces.append(value['text'][:notice.start()])
            following = int(notice.group(1))
            assert following > offset
            offset = following
        else:
            assert value['spill_path'] == ''
            pieces.append(value['text'])
            return ''.join(pieces), pages


def run(workspace, spill):
    pi, rp = load('pi_tools'), load('rp_tools')
    begin, end = '# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====', '# ==== END SHARED CORE ===='
    source = [(PLUGIN_ROOT / (name + '.py')).read_text() for name in ('pi_tools', 'rp_tools')]
    shared = [text[text.index(begin):text.index(end) + len(end)] for text in source]
    assert shared[0] == shared[1]
    for text, (lines, size) in zip(source, ((1392, 63279), (1346, 62667))):
        assert len(text.splitlines()) <= lines and len(text.encode()) <= size
    assert pi.MAX_FILE_BYTES == rp.MAX_FILE_BYTES == 1048576
    assert pi.MAX_SPILL_BYTES == rp.MAX_SPILL_BYTES == 8388608
    assert pi.MAX_MANAGED_SPILL_BYTES == rp.MAX_MANAGED_SPILL_BYTES == 4194304

    # Normal source pages retain the contract and reuse one immutable full snapshot.
    original = ''.join(f'{index:04}: source\n' for index in range(500))
    (workspace / 'pages.txt').write_text(original)
    for module, reader, coordinate in ((pi, pi.read_tool, 'offset'), (rp, rp.read_file_tool, 'start_line')):
        first = reader(dict(path='pages.txt', limit=20))
        assert first['truncated'] and first['spill_path']
        before = {p.name: p.stat().st_mtime_ns for p in spill.glob('*.txt')}
        second = reader(dict(path='pages.txt', limit=20, **{coordinate: 21}))
        assert second['truncated'] and second['spill_path'] == first['spill_path']
        assert before == {p.name: p.stat().st_mtime_ns for p in spill.glob('*.txt')}
        assert (spill / Path(first['spill_path']).name).read_text() == original
    (workspace / 'pages.txt').write_text(original + 'changed\n')
    assert pi.read_tool(dict(path='pages.txt', limit=20))['spill_path'] != first['spill_path']
    fake = spill / ('f' * 32 + '.txt')
    outside = workspace / 'outside.txt'
    unique = original + 'symlink candidate only\n'
    outside.write_text(unique)
    fake.symlink_to(outside)
    safe_path = pi.spill_write(unique)
    assert safe_path != '.v24/spill/' + fake.name
    assert (spill / Path(safe_path).name).read_text() == unique
    fake.unlink()
    racing_payload = 'candidate removed before open\n'
    racing_path = pi.spill_write(racing_payload)
    real_open = pi.os.open
    def removed_before_open(path, flags, *args, **kwargs):
        if path == Path(racing_path).name and flags & os.O_NOFOLLOW and not flags & os.O_CREAT:
            (spill / path).unlink(missing_ok=True)
        return real_open(path, flags, *args, **kwargs)
    with patch.object(pi.os, 'open', removed_before_open):
        replacement = pi.spill_write(racing_payload)
    assert replacement != racing_path and (spill / Path(replacement).name).read_text() == racing_payload

    # Real content failures are visible; a deterministic read race exercises io_error accounting.
    (workspace / 'normal.py').write_text('needle\n')
    (workspace / 'latin.py').write_bytes(b'\xffneedle')
    (workspace / 'large.py').write_bytes(b'needle\n' + b'x' * pi.MAX_FILE_BYTES)
    (workspace / 'binary.py').write_bytes(b'needle\x00')
    for module, search in ((pi, pi.grep_tool), (rp, rp.file_search)):
        args = dict(pattern='needle', **(dict(glob='*.py') if module is pi else dict(filter=dict(extensions=['.py'], paths=[]))))
        text = search(args)['text']
        for expected in ('matches=1;', 'skipped_binary=1;', 'skipped_not_utf8=1;', 'skipped_too_large=1;', 'skipped_io_error=0;'):
            assert expected in text, text
        real_read = module.read_utf8
        def racing(path):
            if path.name == 'normal.py': raise ValueError('io_error')
            return real_read(path)
        with patch.object(module, 'read_utf8', racing):
            assert 'skipped_io_error=1;' in search(args)['text']
    assert 'matches=1;' in rp.file_search(dict(pattern='needle', filter=dict(paths=[], extensions=['.py'])))['text']
    with patch.object(rp, '_search_root') as root_access, patch.object(rp, '_walk') as walk:
        try: rp.file_search(dict(pattern='needle', filter=dict(extensions=['py'], paths=['missing/root'])))
        except ValueError as exc: assert str(exc) == 'invalid_arguments'
        else: raise AssertionError('extension without dot admitted')
        root_access.assert_not_called(); walk.assert_not_called()

    # Full output above the old 1 MiB boundary survives to command completion.
    line = 'head-middle-tail ' + 'x' * 64 + '\n'
    count = 15000
    raw = line * count
    assert len(raw.encode()) > pi.MAX_FILE_BYTES
    source_cmd = command('import sys;sys.stdout.write(' + repr(raw[:len(line)]) + '*' + str(count) + ')')
    code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command=source_cmd + '; echo done > large.sentinel; exit 7'))
    assert code == 0 and reply['ok'], reply
    value = reply['result']['value']
    expected = raw.rstrip('\r\n') + '\n\nCommand exited with code 7'
    assert value['exit_code'] == 7 and value['truncated'] and (workspace / 'large.sentinel').exists()
    assert 'head-middle-tail' in value['text']
    stored = spill / Path(value['spill_path']).name
    assert stored.read_bytes() == expected.encode()
    names = {p.name for p in spill.glob('*.txt')}
    for module, is_rp in ((pi, False), (rp, True)):
        recovered, pages = reconstruct(module, value['spill_path'], rp=is_rp)
        assert recovered == expected and pages > 1
        assert names == {p.name for p in spill.glob('*.txt')}
    print(f'[checked] bash full spill bytes={len(expected.encode())}; both readers reconstruct exact bytes')

    # Cap is measured after replacement; no partial snapshot is advertised.
    maximum = pi.MAX_MANAGED_SPILL_BYTES - 256
    for length, allowed in ((maximum, True), (maximum + 1, False)):
        pre, post = workspace / 'cap.pre', workspace / 'cap.post'
        pre.unlink(missing_ok=True); post.unlink(missing_ok=True)
        source_cmd = command('import os;os.write(1,b"x"*' + str(length) + ')')
        before = {p.name for p in spill.glob('*.txt')}
        code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command='echo ready > cap.pre; ' + source_cmd + '; sleep 0.2; echo done > cap.post'))
        assert pre.exists()
        if allowed:
            assert code == 0 and reply['ok'] and post.exists(), reply
        else:
            assert code == 3 and reply['error']['code'] == 'output_too_large', reply
            assert 'partially executed' in reply['error']['message'] and not post.exists()
            assert before == {p.name for p in spill.glob('*.txt')}
            from v24.host.line_json import _classify_v2
            assert _classify_v2((pi.frame(reply) + '\n').encode(), operation='invoke', exit_code=3)[0] == 'known_error'
    code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command=command('import os;os.write(1,b"a\\x00\\xffb");os.write(2,b"stderr")') + '; exit 9'))
    assert code == 0 and reply['result']['value']['exit_code'] == 9
    assert 'a\ufffd\ufffdbstderr' in reply['result']['value']['text'] and '\x00' not in reply['result']['value']['text']
    code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command=command('import os,time;os.write(1,b"\\xe4");time.sleep(.03);os.write(1,b"\\xb8\\xad")')))
    assert code == 0 and reply['result']['value']['text'] == '中'
    # The isolated supervisor cannot import attacker-controlled workspace modules.
    for filename in ('subprocess.py', 'signal.py', 'time.py'):
        (workspace / filename).write_text('raise RuntimeError("workspace shadow imported")\n')
    for shell_command, expected_code in (('exit 1', 1), ('exit 7', 7), ('exit 9', 9), ('exit 127', 127), ('kill -9 $$', 247)):
        code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command=shell_command))
        assert code == 0 and reply['result']['value']['exit_code'] == expected_code, reply
    print('[checked] shell return codes 1/7/9/127 and signal return 247 remain successful tool results')
    with patch.object(pi, '_kill_group', return_value=False):
        try: pi.bash_tool(dict(command='true'))
        except pi.CleanupUnproven: pass
        else: raise AssertionError('unproven cleanup must preserve unknown')
    code, reply = invoke(PLUGIN_ROOT / 'pi_tools.py', 'bash', dict(command='sleep 2; echo bad > timeout.sentinel', timeout_ms=80))
    assert code == 3 and reply['error']['code'] == 'timeout' and not (workspace / 'timeout.sentinel').exists(), reply

    # Ordinary files retain the 1 MiB ceiling; only valid managed UUID snapshots get 4 MiB.
    for module in (pi, rp):
        try: module.read_source('large.py')
        except ValueError as exc: assert str(exc) == 'file_too_large'
        else: raise AssertionError('ordinary oversized file admitted')
        try: module._payload('x' * (module.MAX_FILE_BYTES + 1))
        except ValueError as exc: assert str(exc) == 'file_too_large'
        else: raise AssertionError('ordinary oversized write admitted')
    injected = spill / ('e' * 32 + '.txt')
    injected.write_bytes(b'x' * (pi.MAX_MANAGED_SPILL_BYTES + 1))
    try: pi.read_source('.v24/spill/' + injected.name)
    except ValueError as exc: assert str(exc) == 'file_too_large'
    else: raise AssertionError('oversized managed spill admitted')
    injected.unlink()
    files = [p for p in spill.glob('*.txt') if p.is_file()]
    assert len(files) <= 50 and sum(p.stat().st_size for p in files) <= pi.MAX_SPILL_BYTES

    rows = kill_probe(PLUGIN_ROOT / 'pi_tools.py', workspace)
    print('[checked] no-stdout kill probe ' + json.dumps(rows, sort_keys=True))
    assert rows[0]['sentinel'] and rows[0]['group_absent'] and rows[0]['artifact_returncode'] == 0
    assert not rows[1]['sentinel'] and rows[1]['group_absent'] and rows[1]['artifact_returncode'] == -signal.SIGKILL

    # Main-shell exit cannot drop background supervision. Natural completion may beat the kill.
    row = shell_exit_probe(PLUGIN_ROOT / 'pi_tools.py', workspace, label='natural')
    assert row['main_shell_exited'] and not row['sentinel'] and row['group_absent'], row
    assert row['artifact_returncode'] in (0, -signal.SIGKILL), row
    if row['reply'] is not None: assert row['reply']['ok'], row
    print('[checked] main-shell-exit supervision ' + json.dumps(row, sort_keys=True))
    for reason in ('timeout', 'output_too_large'):
        print('[checked] abort group cleanup ' + json.dumps(abort_probe(PLUGIN_ROOT / 'pi_tools.py', workspace, reason), sort_keys=True))

    # Hold the completed-shell transition in a temporary copy; the production orphan check still runs.
    ended = "if result is not None: terminal(('EXIT ' + str(result & 255) + '\\n').encode('ascii'))"
    def delayed_terminal(script):
        assert ended in script
        return script.replace(ended, "if result is not None and os.path.exists('release-held-terminal'): terminal(('EXIT ' + str(result & 255) + '\\n').encode('ascii'))")
    held = supervisor_variant(workspace, 'held-terminal', delayed_terminal)
    for action in ('artifact_pid', 'artifact_group'):
        row = shell_exit_probe(held, workspace, action=action, label=action)
        assert row['main_shell_exited'] and row['artifact_running_after_shell'] and not row['sentinel'] and row['group_absent'], row
        assert row['artifact_returncode'] == -signal.SIGKILL, row
        print('[checked] held shell-exit ' + action + ' ' + json.dumps(row, sort_keys=True))
    row = shell_exit_probe(PLUGIN_ROOT / 'pi_tools.py', workspace, action='monitor', label='monitor-death')
    assert row['artifact_returncode'] == 1 and not row['sentinel'] and row['group_absent'], row
    print('[checked] monitor unexpected death fallback ' + json.dumps(row, sort_keys=True))

    # Fault the isolated child's own Popen and private status channel, never shell stdout.
    spawn_line = "try: child = subprocess.Popen(['/bin/sh', '-c', sys.argv[2]], close_fds=True)"
    def spawn_failure(script):
        assert spawn_line in script
        return script.replace(spawn_line, "try: raise OSError(11, '/private/injected-spawn-secret')")
    fault = supervisor_variant(workspace, 'spawn-failure', spawn_failure)
    code, reply = invoke(fault, 'bash', dict(command='echo forbidden > spawn-failure.sentinel'))
    assert code == 3 and reply == dict(ok=False, v=2, error=dict(code='io_error', message='io_error')), reply
    assert not (workspace / 'spawn-failure.sentinel').exists()
    assert 'Traceback' not in json.dumps(reply) and 'injected' not in json.dumps(reply)
    for name, payload in (('missing', "b''"), ('malformed', "b'garbage\\n'"),
                          ('duplicate', "b'EXIT 0\\nEXIT 0\\n'"), ('oversized', "b'x' * 65"),
                          ('exit-out-of-range', "b'EXIT 256\\n'")):
        fault = supervisor_variant(workspace, 'status-' + name,
                                   lambda script, payload=payload: script.replace('os.write(status, value)', 'os.write(status, ' + payload + ')'))
        code, reply = invoke(fault, 'bash', dict(command='exit 0'))
        assert code == 1 and not reply['ok'] and reply['error']['code'] == 'io_error', (name, code, reply)
    fault = supervisor_variant(workspace, 'status-mismatched-exit',
                               lambda script: script.replace('os.killpg(os.getpgrp(), signal.SIGKILL)', 'os._exit(0)'))
    code, reply = invoke(fault, 'bash', dict(command='exit 7'))
    assert code == 1 and not reply['ok'], reply
    source = (PLUGIN_ROOT / 'pi_tools.py').read_text()
    fault = workspace / 'fault-copies' / 'status-read-error.py'
    target = "try: chunk = os.read(key.fd, 65536 if key.data == 'output' else 65)"
    assert target in source
    fault.write_text(source.replace(target, "try:\n                    if key.data == 'status': raise OSError(5, '/private/status-read-fault')\n                    chunk = os.read(key.fd, 65536)"))
    code, reply = invoke(fault, 'bash', dict(command='exit 0'))
    assert code == 1 and not reply['ok'] and reply['error']['code'] == 'io_error', (code, reply)
    print('[checked] supervisor Popen OSError=known io_error; bad/missing/duplicate/oversized/out-of-range/mismatched/read-fault status=unknown')

    # An arbitrary exception .detail never supplies a public message, in either artifact.
    for name in ('pi_tools', 'rp_tools'):
        source = (PLUGIN_ROOT / (name + '.py')).read_text()
        injection = "\nclass InjectedDetail(ValueError):\n    detail = '/private/forbidden-detail'\ndef bad_handler(args):\n    raise InjectedDetail('io_error')\nHANDLERS['read'] = bad_handler\nHANDLERS['read_file'] = bad_handler\n"
        marker = "if __name__ == '__main__':"
        copied = workspace / 'fault-copies' / ('fixed-error-' + name + '.py')
        copied.write_text(source.replace(marker, injection + '\n' + marker))
        code, reply = invoke(copied, 'read' if name == 'pi_tools' else 'read_file', dict(path='pages.txt'))
        assert code == 3 and reply['error'] == dict(code='io_error', message='io_error'), reply

    # Platform evidence, not a claimed Linux fix on a filesystem that rejects the name.
    bad_name = os.fsencode(workspace) + b'/invalid-\xff'
    try: fd = os.open(bad_name, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    except OSError as exc: print(f'[probe] invalid UTF-8 filename unsupported by filesystem; errno={exc.errno}; Linux behavior unverified')
    else:
        os.close(fd)
        try:
            for module, listing in ((pi, pi.ls_tool), (rp, rp.get_file_tree_tool)):
                try: listing({})
                except ValueError as exc: assert str(exc) == 'not_utf8'
                else: raise AssertionError('expected conservative filename refusal')
            print('[probe] invalid UTF-8 filename conservatively refuses listing as not_utf8; no skip fix claimed')
        finally: os.unlink(bad_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kill-probe-artifact', type=Path)
    parser.add_argument('--shell-exit-probe-artifact', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='v24-m4-artifact-') as temporary:
        workspace = Path(temporary).resolve()
        spill = workspace / 'spill'
        spill.mkdir()
        env = dict(V24_WORKSPACE_ROOT=str(workspace), V24_SPILL_ROOT=str(spill),
                   V24_SKILLS_ROOT=str(Path(__file__).resolve().parent / 'skills'))
        with patch.dict(os.environ, env), patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            if args.kill_probe_artifact:
                print(json.dumps(kill_probe(args.kill_probe_artifact.resolve(), workspace), sort_keys=True))
                return 0
            if args.shell_exit_probe_artifact:
                print(json.dumps(shell_exit_probe(args.shell_exit_probe_artifact.resolve(), workspace), sort_keys=True))
                return 0
            run(workspace, spill)
    print('[passed] M4 artifact regressions; full_spill_gt1MiB=true; snapshot_reuse=true; skip_counts=true; no_stdout_kill_cleanup=true; shell_exit_supervision=true; supervisor_status=true; provider_calls=0')
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
