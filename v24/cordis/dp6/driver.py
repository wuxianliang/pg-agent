"""Cordis v2 DP6 W1: single-host fair rediscovery / maintenance scanner.

The scanner is deliberately not a lifecycle engine.  It reads raw facts through a
least-privilege observer connection, pages every topic with its own lossable keyset
cursor, and calls the existing ``advance`` protocol for every decision and write:

* a fiber page drives the W1 ``ensure`` command;
* a ready command continuation drives the reserved ``advance`` continuation;
* a ``dispose_pending`` install drives a fresh non-reserved ``command_dispose``;
* external effects, expired claims, unknown effects and inverse-unknown debt are
  reported only.  W2 owns claim/receipt/crash recovery and external execution.

No handler is invoked in W1.  A Fake handler may be injected by a gate solely to
prove that ``host_io``/unsupported/unknown items never reach it.
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
                  "SELECT id,kind,fiber_id,episode_id,run_id FROM v24_cordis.effects "
                  "WHERE status='unknown' AND id>%s ORDER BY id LIMIT %s"),
            Topic('inverse_unknown',
                  "SELECT id,fiber_id,episode_id,inverse FROM v24_cordis.contributions "
                  "WHERE released_at IS NULL AND inverse->>'op'='unknown' "
                  'AND id>%s ORDER BY id LIMIT %s'),
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

    def _unknown(self, row):
        return {'driver': 'unknown_effect_debt', 'effect_id': str(row[0]),
                'kind': row[1]}

    def _inverse_unknown(self, row):
        return {'driver': 'inverse_unknown_debt', 'contribution_id': str(row[0])}

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
