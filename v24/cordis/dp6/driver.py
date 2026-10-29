"""Cordis v2 DP6: single-host fair rediscovery / maintenance scanner.

The scanner is deliberately not a lifecycle engine.  It reads raw facts through a
least-privilege observer connection, pages every topic with its own lossable keyset
cursor, and calls the existing ``advance`` protocol for every decision and write:

* a fiber page drives the W1 ``ensure`` command;
* a ready command continuation drives the reserved ``advance`` continuation;
* a ``dispose_pending`` install drives a fresh non-reserved ``command_dispose``;
* external effects, expired claims, unknown effects and inverse-unknown debt are
  reported only.  W2 owns claim/receipt/crash recovery and external execution.

No handler is invoked by the W1 scanner.  A Fake handler may be injected by a gate
solely to prove that ``host_io``/unsupported/unknown items never reach it.

W4 adds the drain-based switch driver (``SwitchDriver``) and the pre-deployed HMR
trigger (``HmrTrigger``).  They never write lifecycle columns directly: the switch
submits the existing ``command_install``/``command_reconcile`` commands at frozen
request keys, and every drain step stays in the W1 scanner/``advance`` path.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

ZERO = uuid.UUID(int=0)
DEFAULT_PAGE_SIZE = 64


class CredentialMissing(Exception):
    """The trusted credential map has no real LOGIN for the required actor."""


class WrongActor(Exception):
    """The opened connection's session_user is not the required real LOGIN."""


class HandlerNoReceipt(Exception):
    """A trusted handler completed without a publishable receipt."""


class JournalConflict(Exception):
    """Two different receipts were recorded for one effect token."""


class RunStartSourceError(Exception):
    code = 'run_start_source_invalid'


class RunStartSourceCorrupt(RunStartSourceError):
    code = 'run_start_source_corrupt'


class RunStartSourceDuplicate(RunStartSourceError):
    code = 'run_start_source_duplicate'


class RunStartSourceConflict(RunStartSourceError):
    code = 'run_start_source_conflict'


class RunStartContractMismatch(RunStartSourceError):
    code = 'run_start_contract_mismatch'


def canonical_bytes(value):
    """Local journal/source canonical form; never sent to the database."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode()


def sha256_hex(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, payload):
    """Write one complete JSON document and fsync file plus directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(payload, handle, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    with open(path, 'rb') as handle:
        return json.loads(handle.read().decode('utf-8'))


def _uuid_text(value):
    return str(uuid.UUID(str(value)))


def principal_id(login: str) -> uuid.UUID:
    return uuid.UUID(hashlib.md5(login.encode()).hexdigest())


def effect_id_for(login: str, key: str, kind: str) -> uuid.UUID:
    raw = f'{principal_id(login)}:{kind}:{key}'.encode()
    return uuid.UUID(hashlib.sha256(raw).hexdigest()[:32])


def successor_key(parent, ordinal=0) -> str:
    return f'cordis/reconcile/{parent}/{ordinal}'


def successor_effect_id(login: str, parent, ordinal=0) -> uuid.UUID:
    return effect_id_for(login, successor_key(parent, ordinal), 'command_reconcile')


@dataclass
class Topic:
    name: str
    sql: str
    cursor: uuid.UUID = ZERO
    handled: int = 0
    pages: int = 0


@dataclass
class Report:
    round: int = 0
    actions: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    topics: dict = field(default_factory=dict)
    journal: list = field(default_factory=list)

    def count(self, topic, disposition=None):
        rows = [a for a in self.actions if a['topic'] == topic]
        if disposition is not None:
            rows = [a for a in rows if a['disposition'] == disposition]
        return len(rows)


class ReceiptJournal:
    """Trusted host durable receipt journal, outside every DB transaction.

    A complete receipt (effect id, actor, original token and full outcome) is
    written to an fsynced file before settlement is attempted.  An entry is
    removed only after ``advance`` confirms ``committed`` or ``replay``.  The
    journal is evidence for the host, never a domain writer or lifecycle table.
    """

    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _path(self, effect_id, token):
        return self.root / (f'{effect_id}.{int(token["attempt"])}.{int(token["fence"])}.json')

    def record(self, effect_id, actor, token, outcome, guard=None):
        body = {'v': 1, 'effect_id': str(effect_id), 'actor': actor,
                'token': token, 'outcome': outcome}
        body['digest'] = sha256_hex(body)
        path = self._path(effect_id, token)
        if path.exists():
            existing = read_json(path)
            if existing.get('digest') != body['digest']:
                raise JournalConflict(str(path))
            return path
        if guard is not None:
            guard()
        atomic_write(path, body)
        return path

    def load(self):
        entries = []
        for path in sorted(self.root.glob('*.json')):
            try:
                body = read_json(path)
            except (OSError, ValueError):
                entries.append({'path': path, 'corrupt': True, 'effect_id': None,
                                'reason': 'unreadable'})
                continue
            if not isinstance(body, dict):
                entries.append({'path': path, 'corrupt': True, 'effect_id': None,
                                'reason': 'not_object'})
                continue
            effect_id = body.get('effect_id')
            try:
                effect_id = _uuid_text(effect_id)
                token = body['token']
                outcome = body['outcome']
                if (body.get('v') != 1 or not isinstance(body.get('actor'), str)
                        or set(token) != {'attempt', 'fence', 'owner'}
                        or not isinstance(token['attempt'], int)
                        or not isinstance(token['fence'], int)
                        or isinstance(token['attempt'], bool)
                        or isinstance(token['fence'], bool)
                        or not isinstance(token['owner'], str)
                        or not isinstance(outcome, dict)
                        or not {'v', 'class', 'claim', 'body'} <= set(outcome)
                        or set(outcome) - {'v', 'class', 'claim', 'body', 'receipt_key'}
                        or outcome.get('v') != 1
                        or outcome.get('class') not in
                        ('success', 'failure', 'unknown')
                        or not isinstance(outcome.get('body'), dict)
                        or outcome.get('claim') != token):
                    raise ValueError('shape')
                digest = body.pop('digest', None)
                if digest != sha256_hex(body):
                    raise ValueError('digest')
                body['digest'] = digest
            except (KeyError, TypeError, ValueError):
                entries.append({'path': path, 'corrupt': True,
                                'effect_id': effect_id if isinstance(effect_id, str) else None,
                                'reason': 'digest'})
                continue
            body['path'] = path
            body['corrupt'] = False
            entries.append(body)
        # Duplicate live receipts for one token are ambiguous: keep both and
        # let the caller block instead of choosing bytes.
        seen = {}
        for entry in entries:
            if entry.get('corrupt'):
                continue
            key = (entry['effect_id'], entry['token']['attempt'], entry['token']['fence'])
            if key in seen and seen[key]['digest'] != entry['digest']:
                entry['corrupt'] = True
                entry['reason'] = 'duplicate'
                seen[key]['corrupt'] = True
                seen[key]['reason'] = 'duplicate'
            seen[key] = entry
        return entries

    def confirm(self, path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        fsync_dir(self.root)

    def quarantine(self, path, suffix='.dead'):
        path = Path(path)
        target = path.with_name(path.name + suffix)
        os.replace(path, target)
        fsync_dir(self.root)
        return target


class RunStartSource:
    """Trusted pre-deployed run_start request source with a frozen binding.

    A request is either already bound for one effect, or supplied once through
    the inbox contract.  The binding fixes ``effect_id + contract_version +
    handler_digest``, the original request object and the original initial
    step count under an integrity digest before any consumption.  Missing
    input waits; corrupt, duplicate, conflicting or mismatched bindings block.
    """

    def __init__(self, directory):
        self.root = Path(directory)
        self.bindings = self.root / 'bindings'
        self.inbox = self.root / 'inbox'
        self.bindings.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    @staticmethod
    def _contract(contract):
        if (not isinstance(contract, dict)
                or set(contract) != {'contract_version', 'handler_digest'}
                or not isinstance(contract['contract_version'], str)
                or not contract['contract_version']
                or not isinstance(contract['handler_digest'], str)
                or len(contract['handler_digest']) != 64):
            raise RunStartContractMismatch('effect contract')
        return dict(contract)

    @staticmethod
    def _validate(payload, effect_id, contract, *, digest_required):
        if not isinstance(payload, dict):
            raise RunStartSourceCorrupt('not object')
        allowed = {'v', 'effect_id', 'contract_version', 'handler_digest', 'request', 'steps'}
        if digest_required:
            allowed.add('digest')
        if set(payload) != allowed:
            raise RunStartSourceCorrupt('shape')
        try:
            got_effect = _uuid_text(payload.get('effect_id'))
        except (TypeError, ValueError, AttributeError):
            raise RunStartSourceCorrupt('effect')
        if payload.get('v') != 1 or got_effect != effect_id:
            raise RunStartSourceCorrupt('effect')
        if (payload.get('contract_version') != contract['contract_version']
                or payload.get('handler_digest') != contract['handler_digest']):
            raise RunStartContractMismatch('binding contract')
        request = payload.get('request')
        steps = payload.get('steps')
        if not isinstance(request, dict):
            raise RunStartSourceCorrupt('request')
        if (not isinstance(steps, int) or isinstance(steps, bool)
                or not 1 <= steps <= 64):
            raise RunStartSourceCorrupt('steps')
        body = {'v': 1, 'effect_id': effect_id,
                'contract_version': contract['contract_version'],
                'handler_digest': contract['handler_digest'],
                'request': request, 'steps': steps}
        digest = sha256_hex(body)
        if digest_required and payload.get('digest') != digest:
            raise RunStartSourceCorrupt('digest')
        body['digest'] = digest
        return body

    def _write_binding(self, binding, effect_id):
        path = self.bindings / (effect_id + '.json')
        if path.exists():
            existing = self._validate(read_json(path), effect_id,
                                      {'contract_version': binding['contract_version'],
                                       'handler_digest': binding['handler_digest']},
                                      digest_required=True)
            if existing['digest'] != binding['digest']:
                raise RunStartSourceConflict('binding differs')
            return existing
        atomic_write(path, binding)
        return binding

    def provision(self, effect_id, contract, request, steps):
        """Trusted enqueue API used by the host/test to fix one binding."""
        effect_id = _uuid_text(effect_id)
        contract = self._contract(contract)
        body = {'v': 1, 'effect_id': effect_id,
                'contract_version': contract['contract_version'],
                'handler_digest': contract['handler_digest'],
                'request': request, 'steps': steps}
        binding = self._validate(body, effect_id, contract, digest_required=False)
        return self._write_binding(binding, effect_id)

    def provision_inbox(self, effect_id, contract, request, steps, name=None):
        effect_id = _uuid_text(effect_id)
        contract = self._contract(contract)
        body = {'v': 1, 'effect_id': effect_id,
                'contract_version': contract['contract_version'],
                'handler_digest': contract['handler_digest'],
                'request': request, 'steps': steps}
        binding = self._validate(body, effect_id, contract, digest_required=False)
        target = self.inbox / (name or (effect_id + '.json'))
        atomic_write(target, body)
        return target

    def resolve(self, effect_id, contract):
        effect_id = _uuid_text(effect_id)
        contract = self._contract(contract)
        found = []
        for path in sorted(self.bindings.glob('*.json')):
            try:
                body = read_json(path)
            except (OSError, ValueError):
                if path.name.startswith(effect_id):
                    raise RunStartSourceCorrupt('unreadable binding')
                continue
            if not isinstance(body, dict):
                if path.name.startswith(effect_id):
                    raise RunStartSourceCorrupt('binding shape')
                continue
            try:
                found_id = _uuid_text(body.get('effect_id'))
            except (TypeError, ValueError):
                continue
            if found_id == effect_id:
                found.append((path, body))
        if len(found) > 1:
            raise RunStartSourceDuplicate('multiple bindings')
        if found:
            return self._validate(found[0][1], effect_id, contract, digest_required=True)
        pending = []
        for path in sorted(self.inbox.glob('*.json')):
            try:
                body = read_json(path)
            except (OSError, ValueError):
                if path.name.startswith(effect_id):
                    raise RunStartSourceCorrupt('unreadable inbox')
                continue
            if not isinstance(body, dict):
                if path.name.startswith(effect_id):
                    raise RunStartSourceCorrupt('inbox shape')
                continue
            try:
                body_id = _uuid_text(body.get('effect_id'))
            except (TypeError, ValueError):
                continue
            if body_id == effect_id:
                pending.append((path, body))
        if len(pending) > 1:
            raise RunStartSourceDuplicate('multiple inbox entries')
        if not pending:
            return None
        binding = self._validate(pending[0][1], effect_id, contract, digest_required=False)
        binding = self._write_binding(binding, effect_id)
        try:
            os.unlink(pending[0][0])
            fsync_dir(self.inbox)
        except FileNotFoundError:
            pass
        return binding


class Executor:
    """W2 external-call boundary: claim, trusted handler, journal, receipt.

    Every database call is its own short READ COMMITTED transaction.  The claim
    connection is committed, verified IDLE and closed before the handler runs;
    the receipt is journaled and fsynced with no connection open; settlement is
    a new transaction.  A handler is never invoked twice for one trusted
    receipt, and no lease/IO failure is upgraded to a terminal outcome.
    """

    def __init__(self, *, actor_connect, observer_connect, handler, journal,
                 run_requests=None, lease_ms=30000, fault=None):
        self.actor_connect = actor_connect
        self.observer_connect = observer_connect
        self.handler = handler
        self.journal = journal
        self.run_requests = run_requests
        self.lease_ms = int(lease_ms)
        self.fault = fault
        self.open_connections = set()
        self._seen = set()
        self.stats = {'claims': 0, 'handlers': 0, 'settles': 0,
                      'journal_writes': 0, 'journal_replays': 0,
                      'confirmed': 0, 'quarantined': 0}

    def begin_pass(self):
        self._seen = set()

    def fault_hook(self, phase, **info):
        if self.fault is not None:
            self.fault(phase, **info)

    def assert_idle(self):
        if self.open_connections:
            raise AssertionError('handler/journal reached with an open DB connection')
        return 0

    @staticmethod
    def _select(conn, statement, params=()):
        if not statement.lstrip().upper().startswith('SELECT'):
            raise AssertionError('executor may only execute SELECT: ' + statement)
        with conn.cursor() as cur:
            cur.execute(statement, params) if params else cur.execute(statement)
            return cur.fetchall() if cur.description else None

    def _observer_rows(self, statement, params=()):
        conn = self.observer_connect()
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            rows = self._select(conn, statement, params)
            conn.commit()
            return rows
        finally:
            conn.close()

    @staticmethod
    def _check_login(conn, login):
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            cur.execute('SELECT session_user')
            got = cur.fetchone()[0]
        if got != login:
            raise WrongActor((login, got))

    def _call(self, login, effect, outcome, phase):
        conn = self.actor_connect(login)
        self.open_connections.add(conn)
        try:
            self._check_login(conn, login)
            self.fault_hook(phase + '_before_call', effect_id=str(effect))
            result = self._select(conn, 'SELECT v24_cordis.advance(%s,%s)',
                                  (effect, Json(outcome)))[0][0]
            self.fault_hook(phase + '_before_commit', effect_id=str(effect))
            conn.commit()
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                raise AssertionError('advance left the connection outside IDLE')
            self.open_connections.discard(conn)
            conn.close()
            self.fault_hook(phase + '_after_commit', effect_id=str(effect))
            return result
        except BaseException:
            self.open_connections.discard(conn)
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            raise

    def _claim(self, actor, effect):
        return self._call(actor, effect,
                          {'v': 1, 'class': 'claim', 'claim': None,
                           'body': {'lease_ms': self.lease_ms}}, 'claim')

    def _dispatch(self, effect, input_):
        listeners = input_.get('listeners') if isinstance(input_, dict) else None
        if not isinstance(listeners, list):
            return {'driver': 'dispatch_input_invalid', 'effect_id': str(effect)}
        children = self._observer_rows(
            "SELECT ordinal,status FROM v24_cordis.effects "
            "WHERE parent_id=%s AND kind='listener_call' ORDER BY ordinal", (effect,))
        states = [row[1] for row in children]
        base = {'effect_id': str(effect), 'children': len(children),
                'listeners': len(listeners)}
        if any(state == 'unknown' for state in states):
            return {'driver': 'dispatch_unknown_debt', **base}
        if any(state in ('ready', 'claimed') for state in states):
            return {'driver': 'dispatch_child_pending', **base}
        if len(children) < len(listeners):
            return {'driver': 'dispatch_missing_child_invariant', **base}
        return {'driver': 'dispatch_unsettled_invariant', **base}

    def _receipt(self, kind, answer, binding):
        if answer is None:
            if kind == 'run_start':
                raise HandlerNoReceipt(kind)
            return 'unknown', {'kind': kind}
        if not isinstance(answer, dict):
            raise HandlerNoReceipt('handler shape')
        cls = answer.get('class')
        body = answer.get('body')
        if cls not in ('success', 'failure', 'unknown'):
            raise HandlerNoReceipt('handler class')
        if kind == 'run_start':
            if cls == 'unknown':
                raise HandlerNoReceipt('run_start unknown')
            if cls == 'success':
                # The trusted source, never the adapter, fixes the original
                # request and initial step count.
                body = {'v': 1, 'request': binding['request'],
                        'steps': binding['steps']}
            elif not isinstance(body, dict):
                raise HandlerNoReceipt('handler body')
        elif cls == 'unknown':
            body = {'kind': kind}
        elif not isinstance(body, dict):
            raise HandlerNoReceipt('handler body')
        return cls, body

    def _settle(self, actor, effect, kind, token, cls, body):
        basis = {'effect_id': str(effect), 'attempt': token['attempt'],
                 'fence': token['fence'], 'class': cls, 'body': body}
        outcome = {'v': 1, 'class': cls, 'claim': token, 'body': body,
                   'receipt_key': sha256_hex(basis)}
        path = None
        try:
            self.fault_hook('journal_before_write', effect_id=str(effect))
            path = self.journal.record(effect, actor, token, outcome,
                                       guard=self.assert_idle)
            self.stats['journal_writes'] += 1
            self.fault_hook('journal_after_write', effect_id=str(effect))
        except (OSError, JournalConflict) as exc:
            return {'driver': 'journal_unavailable', 'effect_id': str(effect),
                    'reason': f'{type(exc).__name__}: {exc}', 'path': str(path)}
        try:
            result = self._call(actor, effect, outcome, 'settle')
        except (CredentialMissing, WrongActor) as exc:
            return {'driver': 'blocked_actor_credential', 'effect_id': str(effect),
                    'reason': str(exc), 'path': str(path)}
        except Exception as exc:
            return {'driver': 'settle_unconfirmed', 'effect_id': str(effect),
                    'reason': f'{type(exc).__name__}: {exc}', 'path': str(path)}
        self.stats['settles'] += 1
        if isinstance(result, dict) and result.get('disposition') in ('committed', 'replay'):
            self.journal.confirm(path)
            self.stats['confirmed'] += 1
            return result
        if isinstance(result, dict) and 'error' in result:
            code = result['error'].get('code')
            if code in ('stale_claim', 'receipt_conflict'):
                self.journal.quarantine(path)
                self.stats['quarantined'] += 1
                return {'driver': 'receipt_not_publishable', 'effect_id': str(effect),
                        'code': code, 'detail': result['error'].get('detail')}
            return {'driver': 'receipt_retained', 'effect_id': str(effect),
                    'code': code, 'detail': result['error'].get('detail')}
        return {'driver': 'receipt_retained', 'effect_id': str(effect),
                'reason': 'non-terminal settlement', 'result': result}

    def handle(self, row):
        (effect, kind, status, _fiber, _episode, _run, actor, input_,
         _attempt, _fence, _owner, lease_until) = row
        effect = uuid.UUID(str(effect))
        key = str(effect)
        if key in self._seen:
            return {'driver': 'already_handled', 'effect_id': key}
        self._seen.add(key)
        if kind == 'host_io':
            return {'driver': 'unsupported_host_io', 'effect_id': key, 'kind': kind}
        if kind == 'dispatch':
            return self._dispatch(effect, input_)
        if kind == 'listener_call':
            exec_ = (input_ or {}).get('descriptor', {}).get('exec', {})
            if exec_.get('type') != 'host':
                return {'driver': 'listener_not_host', 'effect_id': key}
        now = datetime.datetime.now(datetime.timezone.utc)
        if lease_until is not None and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=datetime.timezone.utc)
        if status == 'claimed' and lease_until is not None and lease_until > now:
            return {'driver': 'claimed_external_pending', 'effect_id': key,
                    'kind': kind, 'lease_until': lease_until.isoformat()}
        binding = None
        if kind == 'run_start':
            if self.run_requests is None:
                return {'driver': 'run_start_source_unconfigured', 'effect_id': key}
            try:
                binding = self.run_requests.resolve(effect, (input_ or {}).get('contract'))
            except RunStartSourceError as exc:
                return {'driver': exc.code, 'effect_id': key, 'reason': str(exc)}
            if binding is None:
                return {'driver': ('run_start_source_missing_claimed' if status == 'claimed'
                                   else 'run_start_request_pending'),
                        'effect_id': key, 'kind': kind}
            self.fault_hook('source_after_bind', effect_id=key)
        try:
            claim = self._claim(actor, effect)
        except (CredentialMissing, WrongActor) as exc:
            return {'driver': 'blocked_actor_credential', 'effect_id': key,
                    'reason': str(exc)}
        except Exception as exc:
            return {'driver': 'claim_error', 'effect_id': key,
                    'reason': f'{type(exc).__name__}: {exc}'}
        if isinstance(claim, dict) and 'error' in claim:
            return claim
        if isinstance(claim, dict) and claim.get('disposition') == 'deferred':
            return claim
        if not (isinstance(claim, dict) and claim.get('disposition') == 'claimed'):
            return {'driver': 'claim_unexpected', 'effect_id': key, 'result': claim}
        self.stats['claims'] += 1
        token = claim['claim']
        frozen = claim.get('input', input_)
        if kind == 'run_start':
            try:
                binding = self.run_requests.resolve(effect, (frozen or {}).get('contract'))
            except RunStartSourceError as exc:
                return {'driver': exc.code, 'effect_id': key, 'reason': str(exc),
                        'phase': 'after_claim'}
            if binding is None:
                return {'driver': 'run_start_source_missing_after_claim',
                        'effect_id': key}
        payload = {'kind': kind, 'effect_id': key, 'attempt': token['attempt'],
                   'fence': token['fence'], 'owner': token['owner'],
                   'input': frozen, 'execution': claim.get('execution'),
                   'run_start': ({'request': binding['request'], 'steps': binding['steps']}
                                 if binding is not None else None),
                   'open_connections': len(self.open_connections)}
        self.fault_hook('handler_before', effect_id=key)
        try:
            answer = self.handler(payload)
        except Exception as exc:
            return {'driver': 'handler_error', 'effect_id': key,
                    'reason': f'{type(exc).__name__}: {exc}'}
        self.fault_hook('handler_after', effect_id=key)
        self.stats['handlers'] += 1
        try:
            cls, body = self._receipt(kind, answer, binding)
        except HandlerNoReceipt as exc:
            return {'driver': 'handler_no_receipt', 'effect_id': key,
                    'reason': str(exc)}
        return self._settle(actor, effect, kind, token, cls, body)

    def reconcile_journal(self):
        results = []
        for entry in self.journal.load():
            if entry.get('corrupt'):
                results.append({'driver': 'journal_corrupt',
                                'path': str(entry.get('path')),
                                'effect_id': entry.get('effect_id'),
                                'reason': entry.get('reason')})
                if entry.get('effect_id'):
                    self._seen.add(entry['effect_id'])
                continue
            effect = uuid.UUID(entry['effect_id'])
            self._seen.add(str(effect))
            try:
                result = self._call(entry['actor'], effect, entry['outcome'], 'replay')
            except (CredentialMissing, WrongActor) as exc:
                results.append({'driver': 'blocked_actor_credential',
                                'effect_id': str(effect), 'reason': str(exc)})
                continue
            except Exception as exc:
                results.append({'driver': 'journal_replay_unconfirmed',
                                'effect_id': str(effect),
                                'reason': f'{type(exc).__name__}: {exc}'})
                continue
            self.stats['journal_replays'] += 1
            if isinstance(result, dict) and result.get('disposition') in ('committed', 'replay'):
                self.journal.confirm(entry['path'])
                self.stats['confirmed'] += 1
                results.append({'driver': 'receipt_replayed', 'effect_id': str(effect),
                                'disposition': result.get('disposition')})
            elif isinstance(result, dict) and 'error' in result \
                    and result['error'].get('code') in ('stale_claim', 'receipt_conflict'):
                self.journal.quarantine(entry['path'])
                self.stats['quarantined'] += 1
                results.append({'driver': 'receipt_not_publishable',
                                'effect_id': str(effect),
                                'code': result['error'].get('code')})
            else:
                results.append({'driver': 'receipt_retained', 'effect_id': str(effect),
                                'result': result})
        return results


class Maintainer:
    """One fair scanner pass per call; all decisions stay inside ``advance``.

    ``executor`` is the W2 external-call boundary.  Without it the maintainer is
    the W1 observer-only scanner: external effects are diagnosed, never executed.
    """

    def __init__(self, *, observer_connect, actor_connect, ensure_actor,
                 page_size=DEFAULT_PAGE_SIZE, handler=None, executor=None,
                 fault=None):
        self._observer_connect = observer_connect
        self._actor_connect = actor_connect
        self.ensure_actor = ensure_actor
        self.page_size = page_size
        self.handler = handler  # never invoked in W1; W2 owns external execution
        self.executor = executor
        self.fault = fault
        self.round = 0
        self.topics = (
            Topic('fibers',
                  'SELECT id,control_seq FROM v24_cordis.fibers '
                  'WHERE disposed_at IS NULL AND id>%s ORDER BY id LIMIT %s'),
            Topic('commands',
                  "SELECT id,parent_id,ordinal,fiber_id,input,request_actor "
                  "FROM v24_cordis.effects WHERE kind='command_reconcile' AND status='ready' "
                  'AND id>%s ORDER BY id LIMIT %s'),
            Topic('disposes',
                  "SELECT id,state FROM v24_cordis.installs WHERE state='dispose_pending' "
                  'AND id>%s ORDER BY id LIMIT %s'),
            Topic('external',
                  "SELECT id,kind,status,fiber_id,episode_id,run_id,request_actor,input,"
                  "attempt,fence,claim_owner,lease_until "
                  "FROM v24_cordis.effects WHERE status IN ('ready','claimed') "
                  "AND kind IN ('run_start','model_call','tool_call','listener_call','host_io','dispatch') "
                  'AND id>%s ORDER BY id LIMIT %s'),
            Topic('expired',
                  "SELECT id,kind,request_actor,claim_owner,attempt,fence,lease_until,input "
                  "FROM v24_cordis.effects WHERE status='claimed' AND lease_until<clock_timestamp() "
                  'AND id>%s ORDER BY id LIMIT %s'),
            Topic('unknown',
                  "SELECT x.id,x.kind,x.fiber_id,x.episode_id,x.run_id,f.disposed_at,"
                  "f.current_episode_id,f.dispose_requested_at,i.state,r.ended_at "
                  "FROM v24_cordis.effects x "
                  "LEFT JOIN v24_cordis.fibers f ON f.id=x.fiber_id "
                  "LEFT JOIN v24_cordis.installs i ON i.id=f.install_id "
                  "LEFT JOIN v24_cordis.runs r ON r.id=x.run_id "
                  "WHERE x.status='unknown' AND x.id>%s ORDER BY x.id LIMIT %s"),
            Topic('inverse_unknown',
                  "SELECT c.id,c.fiber_id,c.episode_id,c.inverse,f.disposed_at,"
                  "f.current_episode_id,f.dispose_requested_at,i.state "
                  "FROM v24_cordis.contributions c "
                  "LEFT JOIN v24_cordis.fibers f ON f.id=c.fiber_id "
                  "LEFT JOIN v24_cordis.installs i ON i.id=f.install_id "
                  "WHERE c.released_at IS NULL AND c.inverse->>'op'='unknown' "
                  'AND c.id>%s ORDER BY c.id LIMIT %s'),
        )

    # ---- connection and statement discipline -----------------------------

    @staticmethod
    def _select(conn, statement, params=()):
        # The driver is allowed to issue only SELECTs.  DML exists only inside
        # v24_cordis.advance.
        if not statement.lstrip().upper().startswith('SELECT'):
            raise AssertionError('maintenance driver may only execute SELECT: ' + statement)
        with conn.cursor() as cur:
            cur.execute(statement, params) if params else cur.execute(statement)
            return cur.fetchall() if cur.description else None

    @staticmethod
    def _read_committed(conn):
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')

    def _observer_page(self, topic):
        conn = self._observer_connect()
        try:
            self._read_committed(conn)
            rows = self._select(conn, topic.sql, (topic.cursor, self.page_size))
            conn.commit()
            return rows
        finally:
            conn.close()

    def _observer_one(self, statement, params=()):
        conn = self._observer_connect()
        try:
            self._read_committed(conn)
            rows = self._select(conn, statement, params)
            conn.commit()
            return rows
        finally:
            conn.close()

    def _actor(self, login):
        conn = self._actor_connect(login)
        try:
            self._read_committed(conn)
            got = self._select(conn, 'SELECT session_user')[0][0]
            if got != login:
                raise WrongActor((login, got))
            return conn
        except BaseException:
            conn.close()
            raise

    def _fault_hook(self, phase, **info):
        if self.fault is not None:
            self.fault(phase, **info)

    def _canonical(self, conn, payload):
        return self._select(conn, 'SELECT %s::jsonb::text', (Json(payload),))[0][0]

    def _advance(self, login, effect, payload, key, kind):
        conn = self._actor(login)
        try:
            text = self._canonical(conn, payload)
            body = {
                'op': 'admit_and_apply',
                'kind': kind,
                'request_key': key,
                'canonical_bytes': base64.b64encode(text.encode()).decode(),
                'payload': payload,
            }
            outcome = {'v': 1, 'class': 'command', 'claim': None, 'body': body}
            self._fault_hook('command_before_call', effect_id=str(effect))
            result = self._select(conn, 'SELECT v24_cordis.advance(%s,%s)',
                                  (effect, Json(outcome)))[0][0]
            self._fault_hook('command_before_commit', effect_id=str(effect))
            conn.commit()
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                raise AssertionError('advance left the connection outside IDLE')
            conn.close()
            self._fault_hook('command_after_commit', effect_id=str(effect))
            return result
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---- item handlers ----------------------------------------------------

    def ensure(self, fiber, expected, key=None):
        """One ensure probe.  Public so tests can inject a stale/duplicate row."""
        key = key or f'cordis/dp6/ensure/{fiber}/{uuid.uuid4()}'
        payload = {'fiber_id': str(fiber), 'action': 'ensure',
                   'expected_control_seq': int(expected)}
        effect = effect_id_for(self.ensure_actor, key, 'command_reconcile')
        return self._advance(self.ensure_actor, effect, payload, key, 'command_reconcile')

    def _fiber(self, row):
        return self.ensure(row[0], row[1])

    def _command(self, row):
        effect, parent, ordinal, fiber, payload, actor = row
        if parent is None or ordinal is None:
            return {'driver': 'malformed_continuation', 'reason': 'parent'}
        if not isinstance(payload, dict) or set(payload) != {
                'fiber_id', 'action', 'expected_control_seq'}:
            return {'driver': 'malformed_continuation', 'reason': 'payload'}
        if payload.get('action') != 'advance' or payload.get('fiber_id') != str(fiber):
            return {'driver': 'malformed_continuation', 'reason': 'binding'}
        return self._advance(actor, effect, payload, successor_key(parent, ordinal),
                             'command_reconcile')

    def _dispose(self, install):
        inflight = self._observer_one(
            "SELECT id FROM v24_cordis.effects WHERE kind='command_dispose' "
            "AND status IN ('ready','claimed') AND input->>'install_id'=%s LIMIT 1",
            (str(install),))
        if inflight:
            return {'driver': 'dispose_command_inflight'}
        key = f'cordis/dp6/dispose/{install}/{uuid.uuid4()}'
        payload = {'install_id': str(install)}
        effect = effect_id_for(self.ensure_actor, key, 'command_dispose')
        return self._advance(self.ensure_actor, effect, payload, key, 'command_dispose')

    def _external(self, row):
        if self.executor is not None:
            return self.executor.handle(row)
        effect, kind, status = row[0], row[1], row[2]
        if kind == 'host_io':
            disposition = 'unsupported_host_io'
        elif kind == 'dispatch':
            disposition = 'dispatch_pending'
        elif status == 'claimed':
            disposition = 'claimed_external_pending'
        else:
            disposition = 'external_pending'
        # Without an executor the W1 scanner never claims, settles or invokes a
        # handler for an external effect.
        return {'driver': disposition, 'effect_id': str(effect), 'kind': kind}

    def _expired(self, row):
        if self.executor is not None:
            effect = row[0]
            return self.executor.handle((effect, row[1], 'claimed', None, None, None,
                                         row[2], row[7], row[4], row[5], row[3], row[6]))
        return {'driver': 'expired_claim_pending', 'effect_id': str(row[0]),
                'kind': row[1], 'claim_owner': row[2]}

    @staticmethod
    def _debt_blocks(current_episode, dispose_requested, install_state, run, run_ended):
        """Raw-fact observation only: which obligations this terminal debt touches.

        This is a diagnostic label, never a scheduling decision and never a probe of
        a private planner.  A debt with an empty list is still reported.
        """
        blocks = []
        if install_state == 'dispose_pending':
            blocks.append('install_dispose')
        if dispose_requested is not None:
            blocks.append('fiber_dispose')
        if current_episode is not None:
            blocks.append('fiber_drain')
        if run is not None and run_ended is None:
            blocks.append('run_settlement')
        return blocks

    def _unknown(self, row):
        (effect, kind, fiber, episode, run, disposed, current, dispose_requested,
         install_state, run_ended) = row
        return {'driver': 'unknown_effect_debt', 'effect_id': str(effect), 'kind': kind,
                'fiber_id': _uuid_text(fiber) if fiber else None,
                'episode_id': _uuid_text(episode) if episode else None,
                'run_id': _uuid_text(run) if run else None,
                'fiber_disposed': disposed is not None,
                'install_state': install_state,
                'blocks': self._debt_blocks(current, dispose_requested,
                                            install_state, run, run_ended)}

    def _inverse_unknown(self, row):
        (contribution, fiber, episode, inverse, disposed, current, dispose_requested,
         install_state) = row
        debt = inverse.get('debt') if isinstance(inverse, dict) else None
        return {'driver': 'inverse_unknown_debt', 'contribution_id': str(contribution),
                'fiber_id': _uuid_text(fiber) if fiber else None,
                'episode_id': _uuid_text(episode) if episode else None,
                'inverse_op': 'unknown',
                # Stable identity for manual reconciliation; the resource/compensation
                # descriptor itself is trusted-host data and is never copied here.
                'debt_digest': sha256_hex(debt) if debt is not None else None,
                'fiber_disposed': disposed is not None,
                'install_state': install_state,
                'blocks': self._debt_blocks(current, dispose_requested,
                                            install_state, None, None)}

    def _handle(self, topic, row):
        if topic == 'disposes':
            return self._dispose(row[0])
        return {
            'fibers': self._fiber,
            'commands': self._command,
            'external': self._external,
            'expired': self._expired,
            'unknown': self._unknown,
            'inverse_unknown': self._inverse_unknown,
        }[topic](row)

    @staticmethod
    def _disposition(outcome):
        if not isinstance(outcome, dict):
            return 'driver', None
        if 'error' in outcome:
            detail = outcome['error'].get('detail') or {}
            return outcome['error'].get('code'), detail.get('reason')
        if outcome.get('driver'):
            return outcome['driver'], outcome.get('reason')
        return outcome.get('disposition', 'committed'), None

    # ---- fair pass --------------------------------------------------------

    def run_once(self):
        self.round += 1
        report = Report(round=self.round)
        if self.executor is not None:
            self.executor.begin_pass()
            report.journal = self.executor.reconcile_journal()
            for entry in report.journal:
                if entry.get('driver') not in ('receipt_replayed',):
                    report.diagnostics.append(entry)
        # Rotate the starting topic so a long page in one topic cannot always
        # run first; every topic still gets exactly one page per pass.
        offset = (self.round - 1) % len(self.topics)
        order = self.topics[offset:] + self.topics[:offset]
        for topic in order:
            try:
                rows = self._observer_page(topic)
            except Exception as exc:  # observer failure is page-local and reported
                report.diagnostics.append({'topic': topic.name, 'driver': 'observer_error',
                                           'error': f'{type(exc).__name__}: {exc}'})
                continue
            topic.pages += 1
            for row in rows:
                try:
                    outcome = self._handle(topic.name, row)
                    code, reason = self._disposition(outcome)
                    if isinstance(outcome, dict) and outcome.get('driver'):
                        report.diagnostics.append({'topic': topic.name, 'key': row[0],
                                                   **outcome})
                    report.actions.append({'topic': topic.name, 'key': row[0],
                                           'disposition': code, 'reason': reason,
                                           'outcome': outcome})
                except CredentialMissing as exc:
                    report.diagnostics.append({'topic': topic.name, 'key': row[0],
                                               'driver': 'blocked_actor_credential',
                                               'actor': str(exc)})
                    report.actions.append({'topic': topic.name, 'key': row[0],
                                           'disposition': 'blocked_actor_credential',
                                           'reason': str(exc), 'outcome': None})
                except WrongActor as exc:
                    report.diagnostics.append({'topic': topic.name, 'key': row[0],
                                               'driver': 'blocked_actor_credential',
                                               'reason': f'session_user mismatch {exc}'})
                    report.actions.append({'topic': topic.name, 'key': row[0],
                                           'disposition': 'blocked_actor_credential',
                                           'reason': 'session_user mismatch', 'outcome': None})
                except Exception as exc:
                    # 0A000 invariant faults, protocol errors on one row and
                    # connection errors stop only this item, never the sweep.
                    sqlstate = getattr(exc, 'pgcode', None)
                    report.diagnostics.append({
                        'topic': topic.name, 'key': row[0],
                        'driver': 'invariant_fault' if sqlstate == '0A000' else 'item_error',
                        'sqlstate': sqlstate, 'error': str(exc).strip()})
                    report.actions.append({'topic': topic.name, 'key': row[0],
                                           'disposition': 'invariant_fault' if sqlstate == '0A000'
                                           else 'item_error',
                                           'reason': str(exc).strip(), 'outcome': None})
                topic.handled += 1
            topic.cursor = rows[-1][0] if len(rows) == self.page_size else ZERO
            report.topics[topic.name] = {'rows': len(rows), 'cursor': str(topic.cursor)}
        return report

    def run(self, rounds=1):
        return [self.run_once() for _ in range(rounds)]


# ------------------------------------------------------- W4 drain-based switch

SWITCH_KEY_PREFIX = 'cordis/dp6/switch/v1'
SWITCH_KINDS = ('U', 'R')
SWITCH_DECLARATION_KEYS = frozenset((
    'install_id', 'fiber_id', 'scope', 'owner', 'identity', 'version', 'manifest',
    'artifact_digest', 'contracts', 'policy_ref', 'overlay'))
HMR_DESCRIPTOR_KEYS = frozenset((
    'identity', 'version', 'artifact_digest', 'operation_uuid', 'source_fiber_id',
    'install_id', 'target_fiber_id', 'manifest', 'contracts', 'policy_ref', 'overlay'))
TERMINAL_PHASES = ('complete', 'failed', 'blocked')


class SwitchStateError(Exception):
    """A switch cannot be admitted, resumed or advanced without guessing."""

    def __init__(self, code, reason, detail=None):
        super().__init__(f'{code}/{reason}')
        self.code = code
        self.reason = reason
        self.detail = detail or {}


def _uid(value):
    return str(uuid.UUID(str(value)))


@dataclass(frozen=True)
class SwitchPlan:
    """Frozen switch identity: operation, actor, source/target and fixed payload.

    The plan is derived only from the trusted caller's intent before the first
    commit.  Afterwards the committed ``requests`` rows are the authority; the
    driver reconstructs source/target/seq from the request key and re-verifies the
    declaration bytes instead of inventing a new step.
    """

    kind: str
    operation: str
    actor: str
    source_fiber: str
    target_fiber: str
    source_seq: int
    source_install: str
    target_install: str
    expected_digest: str
    payload: dict = field(compare=False)
    provides: tuple = ()
    target_version: str = ''

    def _base(self):
        return (f'{SWITCH_KEY_PREFIX}/{self.kind}/{self.operation}/'
                f'{self.source_fiber}/{self.target_fiber}')

    def start_key(self):
        return f'{self._base()}/{self.source_seq}/start'

    def off_key(self):
        return f'{self._base()}/off/{self.source_seq}'

    def on_key(self):
        return f'{self._base()}/on/0'

    def off_payload(self):
        return {'fiber_id': self.source_fiber, 'action': 'off',
                'expected_control_seq': int(self.source_seq)}

    def on_payload(self):
        return {'fiber_id': self.target_fiber, 'action': 'on',
                'expected_control_seq': 0}

    def as_dict(self):
        return {'kind': self.kind, 'operation': self.operation, 'actor': self.actor,
                'source_fiber': self.source_fiber, 'target_fiber': self.target_fiber,
                'source_seq': self.source_seq, 'source_install': self.source_install,
                'target_install': self.target_install,
                'expected_digest': self.expected_digest, 'payload': self.payload,
                'provides': list(self.provides), 'target_version': self.target_version}

    @classmethod
    def from_dict(cls, value):
        return cls(kind=value['kind'], operation=value['operation'], actor=value['actor'],
                   source_fiber=value['source_fiber'],
                   target_fiber=value['target_fiber'],
                   source_seq=int(value['source_seq']),
                   source_install=value['source_install'],
                   target_install=value['target_install'],
                   expected_digest=value['expected_digest'],
                   payload=value['payload'],
                   provides=tuple(value.get('provides') or ()),
                   target_version=value.get('target_version') or '')


class SwitchDriver:
    """Submit and resume one drain-based upgrade or rollback.

    Every write is an existing ``command_install``/``command_reconcile`` through
    ``advance`` under the frozen request key.  Drain progress is produced only by
    the W1 ``Maintainer``.  No phase table or in-memory cursor is trusted across a
    restart: ``status`` reads the committed requests/fibers/installs/episodes.
    """

    def __init__(self, *, observer_connect, actor_connect, maintainer=None):
        self._observer_connect = observer_connect
        self._actor_connect = actor_connect
        self.maintainer = maintainer
        self.plan = None

    # ---- read discipline --------------------------------------------------

    @staticmethod
    def _select(conn, statement, params=()):
        if not statement.lstrip().upper().startswith('SELECT'):
            raise AssertionError('switch driver may only execute SELECT: ' + statement)
        with conn.cursor() as cur:
            cur.execute(statement, params) if params else cur.execute(statement)
            return cur.fetchall() if cur.description else None

    def _rows(self, statement, params=()):
        conn = self._observer_connect()
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            rows = self._select(conn, statement, params)
            conn.commit()
            return rows
        finally:
            conn.close()

    def _one(self, statement, params=()):
        rows = self._rows(statement, params)
        return rows[0] if rows else None

    def _fiber(self, fiber):
        row = self._one(
            'SELECT id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,'
            'current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at '
            'FROM v24_cordis.fibers WHERE id=%s', (fiber,))
        if row is None:
            return None
        return dict(id=_uid(row[0]), install_id=_uid(row[1]),
                    owner_id=_uid(row[2]) if row[2] else None,
                    owner_episode_id=_uid(row[3]) if row[3] else None,
                    scope_id=_uid(row[4]), want_on=row[5], control_seq=int(row[6]),
                    current_episode_id=_uid(row[7]) if row[7] else None,
                    failure=row[8], retire_started_at=row[9],
                    dispose_requested_at=row[10], disposed_at=row[11])

    def _install(self, install):
        row = self._one(
            'SELECT id,scope_id,owner_fiber_id,owner_episode_id,identity,version,'
            'artifact_digest,state FROM v24_cordis.installs WHERE id=%s', (install,))
        if row is None:
            return None
        return dict(id=_uid(row[0]), scope_id=_uid(row[1]),
                    owner_fiber_id=_uid(row[2]) if row[2] else None,
                    owner_episode_id=_uid(row[3]) if row[3] else None,
                    identity=row[4], version=row[5], artifact_digest=row[6], state=row[7])

    def _episode(self, episode):
        if episode is None:
            return None
        row = self._one('SELECT id,fiber_id,epoch,state,closed_at FROM v24_cordis.episodes '
                        'WHERE id=%s', (episode,))
        if row is None:
            return None
        return dict(id=_uid(row[0]), fiber_id=_uid(row[1]), epoch=int(row[2]),
                    state=row[3], closed_at=row[4])

    def _slot_open(self, fiber):
        return self._one("SELECT id FROM v24_cordis.effects WHERE fiber_id=%s "
                         "AND kind='command_reconcile' AND status IN ('ready','claimed') "
                         'LIMIT 1', (fiber,)) is not None

    def _service_keys(self, fiber):
        """Service addresses a fiber has contributed (history is retained)."""
        rows = self._rows('SELECT DISTINCT key FROM v24_cordis.contributions '
                          "WHERE fiber_id=%s AND kind='service' AND key IS NOT NULL "
                          'ORDER BY key', (fiber,))
        return tuple(row[0] for row in rows)

    def _request(self, key, actor):
        row = self._one(
            'SELECT rq.request_key,rq.request_bytes,rq.response,e.request_actor,e.id '
            'FROM v24_cordis.requests rq LEFT JOIN v24_cordis.effects e ON e.id=rq.effect_id '
            'WHERE rq.principal_id=%s AND rq.request_key=%s',
            (principal_id(actor), key))
        if row is None:
            return None
        return {'key': row[0], 'bytes': bytes(row[1]), 'response': row[2],
                'actor': row[3], 'effect_id': _uid(row[4]) if row[4] else None}

    def _canonical(self, payload):
        return self._select_for_literal(payload)

    def _select_for_literal(self, payload):
        conn = self._observer_connect()
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            rows = self._select(conn, 'SELECT %s::jsonb::text', (Json(payload),))
            conn.commit()
            return rows[0][0]
        finally:
            conn.close()

    def _matches(self, request, payload, actor):
        return (request is not None and request['actor'] == actor
                and request['bytes'] == self._canonical(payload).encode())

    # ---- writer discipline ------------------------------------------------

    def _actor(self, login):
        conn = self._actor_connect(login)
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            got = self._select(conn, 'SELECT session_user')[0][0]
            if got != login:
                raise WrongActor((login, got))
            return conn
        except BaseException:
            conn.close()
            raise

    def _advance(self, login, key, payload, kind):
        effect = effect_id_for(login, key, kind)
        conn = self._actor(login)
        try:
            text = self._select(conn, 'SELECT %s::jsonb::text', (Json(payload),))[0][0]
            body = {'op': 'admit_and_apply', 'kind': kind, 'request_key': key,
                    'canonical_bytes': base64.b64encode(text.encode()).decode(),
                    'payload': payload}
            outcome = {'v': 1, 'class': 'command', 'claim': None, 'body': body}
            result = self._select(conn, 'SELECT v24_cordis.advance(%s,%s)',
                                  (effect, Json(outcome)))[0][0]
            conn.commit()
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                raise AssertionError('advance left the connection outside IDLE')
            return result
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---- planning ---------------------------------------------------------

    def plan_upgrade(self, *, operation, actor, source_fiber, install_id, target_fiber,
                     declaration, expected_digest=None, provides=None):
        operation = _uid(operation)
        source_fiber = _uid(source_fiber)
        target_fiber = _uid(target_fiber)
        install_id = _uid(install_id)
        if source_fiber == target_fiber:
            raise SwitchStateError('invalid_args', 'switch_self_target')
        if not isinstance(declaration, dict) or set(declaration) != SWITCH_DECLARATION_KEYS:
            raise SwitchStateError('invalid_args', 'switch_declaration')
        if _uid(declaration['install_id']) != install_id:
            raise SwitchStateError('invalid_args', 'switch_declaration_target')
        if _uid(declaration['fiber_id']) != target_fiber:
            raise SwitchStateError('invalid_args', 'switch_declaration_fiber')
        src = self._fiber(source_fiber)
        if src is None:
            raise SwitchStateError('not_found_or_denied', 'switch_source_fiber')
        sinst = self._install(src['install_id'])
        ep = self._episode(src['current_episode_id'])
        if (sinst is None or sinst['state'] != 'installed' or not src['want_on']
                or src['dispose_requested_at'] is not None or src['disposed_at'] is not None
                or src['retire_started_at'] is not None or ep is None
                or ep['state'] != 'active' or ep['closed_at'] is not None):
            raise SwitchStateError('stale_generation', 'switch_source_not_live')
        scope = declaration['scope'] if isinstance(declaration['scope'], dict) else {}
        owner = declaration['owner'] if isinstance(declaration['owner'], dict) else {}
        if scope.get('mode') != 'existing' or scope.get('id') != sinst['scope_id']:
            raise SwitchStateError('invalid_args', 'switch_declaration_scope')
        if (owner.get('fiber_id') != sinst['owner_fiber_id']
                or owner.get('episode_id') != sinst['owner_episode_id']):
            raise SwitchStateError('invalid_args', 'switch_declaration_owner')
        if declaration['identity'] != sinst['identity']:
            raise SwitchStateError('invalid_args', 'switch_declaration_identity')
        if declaration['version'] == sinst['version']:
            raise SwitchStateError('install_identity_conflict', 'switch_version')
        digest = declaration['artifact_digest']
        if expected_digest is not None and digest != expected_digest:
            raise SwitchStateError('install_identity_conflict', 'switch_digest')
        if provides is None:
            manifest = declaration['manifest'] if isinstance(declaration['manifest'], dict) else {}
            provides = [item.get('key') for item in manifest.get('provides') or []
                        if isinstance(item, dict) and isinstance(item.get('key'), str)]
        plan = SwitchPlan(kind='U', operation=operation, actor=actor,
                          source_fiber=source_fiber, target_fiber=target_fiber,
                          source_seq=src['control_seq'], source_install=sinst['id'],
                          target_install=install_id, expected_digest=digest,
                          payload=declaration, provides=tuple(provides),
                          target_version=declaration['version'])
        # Operation/slot identity is checked before target absence so another actor
        # reusing the operation UUID is reported as an actor conflict, not a new start.
        self._check_slot(plan, sinst)
        if self._fiber(target_fiber) is not None:
            raise SwitchStateError('invalid_args', 'switch_target_fiber_exists')
        if self._install(install_id) is not None:
            raise SwitchStateError('invalid_args', 'switch_target_install_exists')
        self.plan = plan
        return plan

    def plan_rollback(self, *, operation, actor, source_fiber, target_install,
                      target_fiber, expected_digest, provides=None):
        operation = _uid(operation)
        source_fiber = _uid(source_fiber)
        target_fiber = _uid(target_fiber)
        target_install = _uid(target_install)
        if source_fiber == target_fiber:
            raise SwitchStateError('invalid_args', 'switch_self_target')
        src = self._fiber(source_fiber)
        if src is None:
            raise SwitchStateError('not_found_or_denied', 'switch_source_fiber')
        sinst = self._install(src['install_id'])
        tinst = self._install(target_install)
        if sinst is None or tinst is None:
            raise SwitchStateError('not_found_or_denied', 'switch_install')
        if tinst['state'] != 'installed':
            raise SwitchStateError('install_not_ready', 'switch_rollback_state')
        if sinst['id'] == tinst['id']:
            raise SwitchStateError('invalid_args', 'switch_rollback_same_install')
        if (tinst['scope_id'], tinst['identity']) != (sinst['scope_id'], sinst['identity']):
            raise SwitchStateError('invalid_args', 'switch_rollback_slot')
        if ((tinst['owner_fiber_id'], tinst['owner_episode_id'])
                != (sinst['owner_fiber_id'], sinst['owner_episode_id'])):
            raise SwitchStateError('invalid_args', 'switch_rollback_owner')
        if tinst['version'] == sinst['version']:
            raise SwitchStateError('invalid_args', 'switch_rollback_version')
        if tinst['artifact_digest'] != expected_digest:
            raise SwitchStateError('install_identity_conflict', 'switch_rollback_digest')
        if src['dispose_requested_at'] is not None or src['disposed_at'] is not None:
            raise SwitchStateError('stale_generation', 'switch_source_terminal')
        if self._fiber(target_fiber) is not None:
            raise SwitchStateError('invalid_args', 'switch_target_fiber_exists')
        payload = {'mode': 'reuse', 'install_id': target_install,
                   'fiber_id': target_fiber, 'expected_digest': expected_digest}
        if provides is None:
            provides = self._service_keys(source_fiber)
        plan = SwitchPlan(kind='R', operation=operation, actor=actor,
                          source_fiber=source_fiber, target_fiber=target_fiber,
                          source_seq=src['control_seq'], source_install=sinst['id'],
                          target_install=target_install, expected_digest=expected_digest,
                          payload=payload,
                          provides=tuple(provides or ()), target_version=tinst['version'])
        self._check_slot(plan, sinst)
        self.plan = plan
        return plan

    def _check_slot(self, plan, our_install):
        rows = self._rows('SELECT request_key FROM v24_cordis.requests '
                          'WHERE request_key LIKE %s AND request_key LIKE %s',
                          (SWITCH_KEY_PREFIX + '/%', '%/start'))
        for (key,) in rows:
            parts = key.split('/')
            if len(parts) != 10:
                continue
            kind, operation, source, target = parts[4], parts[5], parts[6], parts[7]
            if (kind == plan.kind and operation == plan.operation
                    and source == plan.source_fiber and target == plan.target_fiber):
                if key != plan.start_key():
                    raise SwitchStateError('stale_generation', 'switch_operation_conflict',
                                           {'operation': operation})
                existing = self._request(key, plan.actor)
                if existing is None or existing['actor'] != plan.actor:
                    raise SwitchStateError('effect_id_conflict', 'switch_actor',
                                           {'operation': operation})
                continue
            other_source = self._fiber(source)
            other_install = self._install(other_source['install_id']) if other_source else None
            if other_install is None:
                continue
            if ((other_install['scope_id'], other_install['identity'])
                    != (our_install['scope_id'], our_install['identity'])):
                continue
            if (plan.kind == 'R' and target == plan.source_fiber
                    and other_install['id'] == plan.target_install):
                continue
            if self._terminal_target(target):
                continue
            raise SwitchStateError('stale_generation', 'switch_slot_busy',
                                   {'operation': operation})
        return None

    def _terminal_target(self, fiber):
        target = self._fiber(fiber)
        if target is None:
            return False
        failure = self._failure_at(target)
        if failure is not None:
            return True
        episode = self._episode(target['current_episode_id'])
        return (episode is not None and episode['state'] == 'active'
                and episode['closed_at'] is None and target['want_on']
                and not self._slot_open(target['id']))

    @staticmethod
    def _failure_at(fiber):
        failure = fiber.get('failure')
        if not isinstance(failure, dict):
            return None
        if failure.get('control_seq') != fiber['control_seq']:
            return None
        return {'code': failure.get('code'), 'reason': failure.get('reason'),
                'phase': failure.get('phase'), 'key': failure.get('key')}

    # ---- committed-fact status -------------------------------------------

    def _drain(self, fiber):
        row = self._one(
            'SELECT f.want_on,f.current_episode_id IS NOT NULL,f.retire_started_at,'
            '(SELECT count(*) FROM v24_cordis.episodes e WHERE e.fiber_id=f.id AND e.closed_at IS NULL),'
            '(SELECT count(*) FROM v24_cordis.contributions c WHERE c.fiber_id=f.id AND c.released_at IS NULL),'
            '(SELECT count(*) FROM v24_cordis.pins p WHERE p.released_at IS NULL AND '
            ' (p.consumer_fiber_id=f.id OR p.contribution_id IN '
            '  (SELECT id FROM v24_cordis.contributions WHERE fiber_id=f.id))),'
            '(SELECT count(*) FROM v24_cordis.runs r WHERE r.owner_fiber_id=f.id AND r.ended_at IS NULL),'
            '(SELECT count(*) FROM v24_cordis.effects x WHERE x.status IN (\'ready\',\'claimed\',\'unknown\') AND '
            ' (x.fiber_id=f.id OR x.episode_id IN (SELECT id FROM v24_cordis.episodes WHERE fiber_id=f.id) OR '
            '  x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=f.id))) '
            'FROM v24_cordis.fibers f WHERE f.id=%s', (fiber,))
        if row is None:
            return {'drained': False, 'reasons': ['missing']}
        reasons = []
        if row[0]:
            reasons.append('want_on')
        if row[1]:
            reasons.append('episode')
        if row[2] is not None:
            reasons.append('retire')
        if row[3]:
            reasons.append('open_episode')
        if row[4]:
            reasons.append('contribution')
        if row[5]:
            reasons.append('pin')
        if row[6]:
            reasons.append('run')
        if row[7]:
            reasons.append('effect')
        return {'drained': not reasons, 'reasons': reasons,
                'want_on': row[0], 'episodes': row[3], 'contributions': row[4],
                'pins': row[5], 'runs': row[6], 'effects': row[7]}

    def _address_owned(self, plan, target):
        if not plan.provides:
            return True, []
        rows = self._rows("SELECT key,episode_id FROM v24_cordis.contributions "
                          "WHERE fiber_id=%s AND kind='service' AND released_at IS NULL",
                          (target['id'],))
        live = {row[0] for row in rows if _uid(row[1]) == target['current_episode_id']}
        missing = [key for key in plan.provides if key not in live]
        return not missing, sorted(missing)

    def status(self, plan=None):
        plan = plan or self.plan
        if plan is None:
            raise SwitchStateError('invalid_args', 'switch_plan')
        base = {'kind': plan.kind, 'operation': plan.operation,
                'source_fiber': plan.source_fiber, 'target_fiber': plan.target_fiber,
                'source_seq': plan.source_seq}
        start = self._request(plan.start_key(), plan.actor)
        if start is None:
            return dict(base, phase='start_pending')
        if not self._matches(start, plan.payload, plan.actor):
            return dict(base, phase='blocked', reason='switch_operation_payload')
        src = self._fiber(plan.source_fiber)
        target = self._fiber(plan.target_fiber)
        sinst = self._install(plan.source_install)
        tinst = self._install(plan.target_install)
        if None in (src, target, sinst, tinst):
            return dict(base, phase='blocked', reason='switch_invariant')
        if target['install_id'] != tinst['id'] or src['install_id'] != sinst['id']:
            return dict(base, phase='blocked', reason='switch_invariant')
        if ((tinst['scope_id'], tinst['identity'], tinst['owner_fiber_id'],
             tinst['owner_episode_id']) != (sinst['scope_id'], sinst['identity'],
                                            sinst['owner_fiber_id'], sinst['owner_episode_id'])
                or tinst['id'] == sinst['id']):
            return dict(base, phase='blocked', reason='switch_identity')
        if tinst['artifact_digest'] != plan.expected_digest:
            return dict(base, phase='blocked', reason='switch_digest')
        off = self._request(plan.off_key(), plan.actor)
        if off is None:
            if src['disposed_at'] is not None or src['dispose_requested_at'] is not None:
                return dict(base, phase='blocked', reason='switch_source_terminal')
            if src['control_seq'] != plan.source_seq:
                return dict(base, phase='blocked', reason='stale_control_seq',
                            control_seq=src['control_seq'])
            if not src['want_on']:
                return dict(base, phase='blocked', reason='switch_source_not_live')
            return dict(base, phase='off_pending', control_seq=src['control_seq'])
        if not self._matches(off, plan.off_payload(), plan.actor):
            return dict(base, phase='blocked', reason='switch_operation_payload')
        drain = self._drain(src['id'])
        if not drain['drained']:
            return dict(base, phase='draining', drain=drain)
        on = self._request(plan.on_key(), plan.actor)
        if on is None:
            if (target['control_seq'] != 0 or target['want_on']
                    or target['current_episode_id'] is not None
                    or target['dispose_requested_at'] is not None
                    or target['disposed_at'] is not None):
                return dict(base, phase='blocked', reason='switch_target_moved')
            return dict(base, phase='on_pending')
        if not self._matches(on, plan.on_payload(), plan.actor):
            return dict(base, phase='blocked', reason='switch_operation_payload')
        failure = self._failure_at(target)
        if failure is not None:
            return dict(base, phase='failed', failure=failure)
        episode = self._episode(target['current_episode_id'])
        if (episode is None or episode['state'] != 'active'
                or episode['closed_at'] is not None or not target['want_on']):
            return dict(base, phase='activating', drain=drain)
        if self._slot_open(target['id']):
            return dict(base, phase='activating', drain=drain,
                        reason='pending_reconcile')
        verified, missing = self._address_owned(plan, target)
        if not verified:
            return dict(base, phase='blocked', reason='switch_address_missing',
                        missing=missing)
        return dict(base, phase='complete', episode_id=episode['id'],
                    address=plan.provides)

    # ---- actions ----------------------------------------------------------

    def start(self, plan=None):
        plan = plan or self.plan
        if plan is None:
            raise SwitchStateError('invalid_args', 'switch_plan')
        self.plan = plan
        existing = self._request(plan.start_key(), plan.actor)
        if existing is not None:
            if not self._matches(existing, plan.payload, plan.actor):
                raise SwitchStateError('request_conflict', 'switch_operation_payload')
            state = self.status(plan)
            return {'action': 'start_replay', 'phase': state['phase'], 'state': state}
        result = self._advance(plan.actor, plan.start_key(), plan.payload, 'command_install')
        self._raise_protocol(result, 'start')
        state = self.status(plan)
        return {'action': 'start', 'phase': state['phase'], 'result': result, 'state': state}

    def _submit(self, plan, phase):
        key = plan.off_key() if phase == 'off' else plan.on_key()
        payload = plan.off_payload() if phase == 'off' else plan.on_payload()
        existing = self._request(key, plan.actor)
        if existing is not None:
            if not self._matches(existing, payload, plan.actor):
                raise SwitchStateError('request_conflict', 'switch_operation_payload')
            state = self.status(plan)
            return {'action': phase + '_replay', 'phase': state['phase'], 'state': state}
        result = self._advance(plan.actor, key, payload, 'command_reconcile')
        self._raise_protocol(result, phase)
        state = self.status(plan)
        return {'action': phase, 'phase': state['phase'], 'result': result, 'state': state}

    @staticmethod
    def _raise_protocol(result, step):
        if not isinstance(result, dict):
            raise SwitchStateError('invalid_outcome', 'switch_' + step)
        if 'error' in result:
            error = result['error'] or {}
            detail = error.get('detail') or {}
            raise SwitchStateError(error.get('code', 'invalid_outcome'),
                                   detail.get('reason', 'switch_' + step), detail)

    def step(self, plan=None):
        plan = plan or self.plan
        if plan is None:
            raise SwitchStateError('invalid_args', 'switch_plan')
        state = self.status(plan)
        phase = state['phase']
        if phase == 'start_pending':
            return self.start(plan)
        if phase == 'off_pending':
            return self._submit(plan, 'off')
        if phase == 'on_pending':
            return self._submit(plan, 'on')
        if phase in ('draining', 'activating'):
            report = self.maintainer.run_once() if self.maintainer is not None else None
            return {'action': 'drive', 'phase': phase,
                    'report': report, 'state': self.status(plan)}
        return {'action': 'none', 'phase': phase, 'state': state}

    def drive(self, plan=None, limit=64):
        plan = plan or self.plan
        actions = []
        for _ in range(limit):
            outcome = self.step(plan)
            actions.append(outcome)
            if outcome['action'] == 'none':
                return {'phase': outcome['phase'], 'state': outcome['state'],
                        'actions': actions}
        raise SwitchStateError('budget_exceeded', 'switch_drive_limit',
                               {'limit': limit})

    def resume(self, kind, operation, actor):
        if kind not in SWITCH_KINDS:
            raise SwitchStateError('invalid_args', 'switch_kind')
        operation = _uid(operation)
        prefix = f'{SWITCH_KEY_PREFIX}/{kind}/{operation}/'
        rows = self._rows('SELECT request_key FROM v24_cordis.requests '
                          'WHERE request_key LIKE %s AND request_key LIKE %s',
                          (prefix + '%', '%/start'))
        if not rows:
            return None
        if len(rows) > 1:
            raise SwitchStateError('stale_generation', 'switch_operation_conflict')
        key = rows[0][0]
        parts = key.split('/')
        if len(parts) != 10:
            raise SwitchStateError('stale_generation', 'switch_operation_conflict')
        source_fiber, target_fiber, source_seq = parts[6], parts[7], int(parts[8])
        request = self._request(key, actor)
        if request is None or request['actor'] != actor:
            raise SwitchStateError('effect_id_conflict', 'switch_actor')
        try:
            payload = json.loads(request['bytes'].decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise SwitchStateError('invalid_args', 'switch_operation_payload')
        source = self._fiber(source_fiber)
        if source is None:
            raise SwitchStateError('not_found_or_denied', 'switch_source_fiber')
        if kind == 'U':
            target_install = _uid(payload['install_id'])
            tinst = self._install(target_install)
            if tinst is None:
                raise SwitchStateError('not_found_or_denied', 'switch_target_install')
            plan = SwitchPlan(kind='U', operation=operation, actor=actor,
                              source_fiber=source_fiber, target_fiber=target_fiber,
                              source_seq=source_seq, source_install=source['install_id'],
                              target_install=target_install,
                              expected_digest=payload['artifact_digest'],
                              payload=payload,
                              provides=tuple(item.get('key') for item in
                                             (payload.get('manifest') or {}).get('provides') or []
                                             if isinstance(item, dict)),
                              target_version=payload['version'])
        else:
            target_install = _uid(payload['install_id'])
            tinst = self._install(target_install)
            if tinst is None:
                raise SwitchStateError('not_found_or_denied', 'switch_target_install')
            plan = SwitchPlan(kind='R', operation=operation, actor=actor,
                              source_fiber=source_fiber, target_fiber=target_fiber,
                              source_seq=source_seq, source_install=source['install_id'],
                              target_install=target_install,
                              expected_digest=payload['expected_digest'],
                              payload=payload,
                              provides=self._service_keys(source_fiber),
                              target_version=tinst['version'])
        self.plan = plan
        return plan


class HmrTrigger:
    """Pre-deployed descriptor watcher: it only submits the same switch request.

    No code is downloaded, imported or hot-swapped.  One JSON descriptor per
    managed identity names the already-deployed digest plus the fixed operation /
    target UUIDs; a tick compares the running source install's version+digest and
    calls ``SwitchDriver.start`` with the identical request when they differ.
    """

    def __init__(self, driver, directory, actor):
        self.driver = driver
        self.directory = Path(directory)
        self.actor = actor

    def descriptors(self):
        found = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                value = read_json(path)
            except (OSError, ValueError) as exc:
                raise SwitchStateError('invalid_args', 'hmr_descriptor_corrupt',
                                       {'path': path.name, 'error': str(exc)})
            if not isinstance(value, dict) or set(value) != HMR_DESCRIPTOR_KEYS:
                raise SwitchStateError('invalid_args', 'hmr_descriptor_shape',
                                       {'path': path.name})
            found.append(value)
        return found

    def tick(self):
        results = []
        try:
            descriptors = self.descriptors()
        except SwitchStateError as exc:
            return [{'driver': 'hmr_descriptor_invalid', 'code': exc.code,
                     'reason': exc.reason, 'detail': exc.detail}]
        for descriptor in descriptors:
            source_fiber = _uid(descriptor['source_fiber_id'])
            source = self.driver._fiber(source_fiber)
            if source is None:
                results.append({'driver': 'hmr_source_missing',
                                'source_fiber_id': source_fiber})
                continue
            source_install = self.driver._install(source['install_id'])
            if source_install is None:
                results.append({'driver': 'hmr_source_missing',
                                'source_fiber_id': source_fiber})
                continue
            if source_install['identity'] != descriptor['identity']:
                results.append({'driver': 'hmr_identity_mismatch',
                                'source_fiber_id': source_fiber})
                continue
            if (source_install['version'] == descriptor['version']
                    and source_install['artifact_digest'] == descriptor['artifact_digest']):
                results.append({'driver': 'hmr_current',
                                'identity': descriptor['identity'],
                                'version': descriptor['version']})
                continue
            try:
                committed = self.driver.resume('U', descriptor['operation_uuid'], self.actor)
            except (SwitchStateError, CredentialMissing, WrongActor) as exc:
                results.append({'driver': 'hmr_blocked',
                                'identity': descriptor.get('identity'),
                                'reason': getattr(exc, 'reason', str(exc)),
                                'code': getattr(exc, 'code', None)})
                continue
            if committed is not None:
                # A repeated tick reuses the committed operation bytes; a different
                # descriptor under the same identity is a conflict, never a new intent.
                if (committed.target_fiber != _uid(descriptor['target_fiber_id'])
                        or committed.target_install != _uid(descriptor['install_id'])
                        or committed.payload.get('version') != descriptor['version']
                        or committed.payload.get('artifact_digest') != descriptor['artifact_digest']):
                    results.append({'driver': 'hmr_blocked',
                                    'identity': descriptor.get('identity'),
                                    'reason': 'switch_operation_conflict',
                                    'code': 'stale_generation'})
                    continue
                try:
                    outcome = self.driver.start(committed)
                except (SwitchStateError, CredentialMissing, WrongActor) as exc:
                    results.append({'driver': 'hmr_blocked',
                                    'identity': descriptor.get('identity'),
                                    'reason': getattr(exc, 'reason', str(exc)),
                                    'code': getattr(exc, 'code', None)})
                    continue
                results.append({'driver': 'hmr_inflight',
                                'identity': descriptor['identity'],
                                'operation': committed.operation,
                                'action': outcome['action']})
                continue
            try:
                plan = self.driver.plan_upgrade(
                    operation=descriptor['operation_uuid'],
                    actor=self.actor,
                    source_fiber=source_fiber,
                    install_id=descriptor['install_id'],
                    target_fiber=descriptor['target_fiber_id'],
                    declaration={
                        'install_id': descriptor['install_id'],
                        'fiber_id': descriptor['target_fiber_id'],
                        'scope': {'mode': 'existing', 'id': source_install['scope_id']},
                        'owner': {'fiber_id': source_install['owner_fiber_id'],
                                  'episode_id': source_install['owner_episode_id']},
                        'identity': descriptor['identity'],
                        'version': descriptor['version'],
                        'manifest': descriptor['manifest'],
                        'artifact_digest': descriptor['artifact_digest'],
                        'contracts': descriptor['contracts'],
                        'policy_ref': descriptor['policy_ref'],
                        'overlay': descriptor['overlay']},
                    expected_digest=descriptor['artifact_digest'])
                outcome = self.driver.start(plan)
                results.append({'driver': 'hmr_started',
                                'identity': descriptor['identity'],
                                'operation': plan.operation,
                                'action': outcome['action']})
            except (SwitchStateError, CredentialMissing, WrongActor) as exc:
                results.append({'driver': 'hmr_blocked',
                                'identity': descriptor.get('identity'),
                                'reason': getattr(exc, 'reason', str(exc)),
                                'code': getattr(exc, 'code', None)})
        return results
