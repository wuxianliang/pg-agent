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
import hashlib
import uuid
from dataclasses import dataclass, field

from psycopg2.extras import Json

ZERO = uuid.UUID(int=0)
DEFAULT_PAGE_SIZE = 64


class CredentialMissing(Exception):
    """The trusted credential map has no real LOGIN for the required actor."""


class WrongActor(Exception):
    """The opened connection's session_user is not the required real LOGIN."""


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

    def count(self, topic, disposition=None):
        rows = [a for a in self.actions if a['topic'] == topic]
        if disposition is not None:
            rows = [a for a in rows if a['disposition'] == disposition]
        return len(rows)


class Maintainer:
    """One fair scanner pass per call; all decisions stay inside ``advance``."""

    def __init__(self, *, observer_connect, actor_connect, ensure_actor,
                 page_size=DEFAULT_PAGE_SIZE, handler=None):
        self._observer_connect = observer_connect
        self._actor_connect = actor_connect
        self.ensure_actor = ensure_actor
        self.page_size = page_size
        self.handler = handler  # never invoked in W1; W2 owns external execution
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
                  "SELECT id,kind,status,fiber_id,episode_id,run_id,request_actor,input "
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

    def _observer_page(self, topic):
        conn = self._observer_connect()
        try:
            rows = self._select(conn, topic.sql, (topic.cursor, self.page_size))
            conn.commit()
            return rows
        finally:
            conn.close()

    def _observer_one(self, statement, params=()):
        conn = self._observer_connect()
        try:
            rows = self._select(conn, statement, params)
            conn.commit()
            return rows
        finally:
            conn.close()

    def _actor(self, login):
        conn = self._actor_connect(login)
        try:
            got = self._select(conn, 'SELECT session_user')[0][0]
            if got != login:
                raise WrongActor((login, got))
            return conn
        except BaseException:
            conn.close()
            raise

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
            result = self._select(conn, 'SELECT v24_cordis.advance(%s,%s)',
                                  (effect, Json(outcome)))[0][0]
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        effect, kind, status = row[0], row[1], row[2]
        if kind == 'host_io':
            disposition = 'unsupported_host_io'
        elif kind == 'dispatch':
            disposition = 'dispatch_pending'
        elif status == 'claimed':
            disposition = 'claimed_external_pending'
        else:
            disposition = 'external_pending'
        # W1 never claims, settles or invokes a handler for an external effect.
        return {'driver': disposition, 'effect_id': str(effect), 'kind': kind}

    def _expired(self, row):
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
