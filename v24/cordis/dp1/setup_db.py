"""Disposable Cordis databases and exact random role families (no v24 imports)."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import subprocess
import sys
import time

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn, TRANSACTION_STATUS_INTRANS

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from v24.cordis.load import load_stage, SQL_LOAD_ORDER, self_check_manifest

ALIASES = ('owner', 'admin', 'service', 'operator')
TABLES = frozenset(('installs','scopes','fibers','episodes','contributions','pins','runs','effects','events','requests'))


def validate_local_dsn(dsn, socket):
    p = parse_dsn(dsn)
    if (not p.get('host','').startswith('/') or ',' in p['host']
            or Path(p['host']).resolve() != Path(socket).resolve()
            or ',' in p.get('port','')):
        raise ValueError('requires the active pgembed Unix socket')
    if any(k in p for k in ('hostaddr','service','servicefile')) or any(
        os.environ.get(k) for k in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE')
    ):
        raise ValueError('libpq hostaddr/service indirection forbidden')
    return p


def server_helper():
    from server import get_server
    server = None
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        server = get_server()
        info = server.get_postmaster_info()
        if info is None or info.socket_dir is None or info.port is None:
            raise RuntimeError('missing active pgembed endpoint')
        print(json.dumps(dict(uri=server.get_uri('postgres'), socket=str(info.socket_dir), port=info.port)), flush=True)
        sys.stdin.read()
    finally:
        if server is not None:
            server.cleanup()


class Server:
    def __enter__(self):
        self.process = subprocess.Popen(
            ['uv','run','python',str(Path(__file__).resolve()),'--server-helper'],
            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 60
            data = bytearray()
            while b'\n' not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self.process.stdout],[],[],remaining)[0]:
                    raise RuntimeError('pgembed endpoint timeout')
                chunk = os.read(self.process.stdout.fileno(),4096)
                if not chunk or len(data) + len(chunk) > 4096:
                    raise RuntimeError('invalid pgembed endpoint')
                data.extend(chunk)
            e = json.loads(data.split(b'\n',1)[0])
            self.params = validate_local_dsn(e['uri'],e['socket'])
            if 'port' in self.params and int(self.params['port']) != e['port']:
                raise RuntimeError('endpoint port mismatch')
            self.params['port'] = str(e['port'])
            self.params.pop('dbname',None)
            if not (Path(e['socket']) / f".s.PGSQL.{e['port']}").exists():
                raise RuntimeError('Unix socket is not active')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def connect(self, database='postgres', user=None):
        p = dict(self.params, dbname=database)
        if user is not None:
            p['user'] = user
        dsn = make_dsn(**p)
        validate_local_dsn(dsn,self.params['host'])
        return psycopg2.connect(dsn)

    def __exit__(self, typ, exc, tb):
        errors = []
        try:
            self.process.stdin.close()
            try:
                code = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid,signal.SIGKILL)
                    self.process.wait(timeout=5)
                raise RuntimeError('helper required forced termination')
            if code:
                raise RuntimeError(f'helper exited {code}')
            try:
                os.killpg(self.process.pid,0)
            except ProcessLookupError:
                pass
            else:
                os.killpg(self.process.pid,signal.SIGKILL)
                raise RuntimeError('helper left live process group')
        except BaseException as cleanup:
            errors.append(cleanup)
        finally:
            self.process.stdout.close()
        if errors:
            if exc is not None:
                exc.add_note(f'helper cleanup failed: {errors!r}')
            else:
                raise RuntimeError(f'helper cleanup failed: {errors!r}')


def role_state(conn, name):
    with conn.cursor() as c:
        c.execute('''SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,
                     rolbypassrls,rolcanlogin,rolinherit FROM pg_roles WHERE rolname=%s''',(name,))
        return c.fetchone()


class TestDB:
    def __init__(self, server, *, root=None, order=None):
        self.server = server
        suffix = f'{os.getpid()}_{secrets.token_hex(6)}'
        self.name = 'v24_cordis_dp1_' + suffix
        self.family = 'v24_cordis_' + suffix
        self.roles = {a:f'{self.name}_{a}' for a in ALIASES}
        self.groups = {a:f'{self.family}_{a}' for a in ALIASES}
        self.identities = []
        self.oid = None
        self.connections = []
        self.closed = False
        self.admin = server.connect()
        self.admin.autocommit = True
        try:
            with self.admin.cursor() as c:
                for login, names in ((False,self.groups),(True,self.roles)):
                    for alias,name in names.items():
                        assert len(name) <= 63
                        c.execute(sql.SQL('CREATE ROLE {} {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS {}').format(
                            sql.Identifier(name),sql.SQL('LOGIN' if login else 'NOLOGIN'),sql.SQL('INHERIT' if login else 'NOINHERIT')))
                        state = role_state(self.admin,name)
                        self.identities.append((name,state))
                        if login:
                            c.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(self.groups[alias]),sql.Identifier(name)))
                c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(self.name)))
                c.execute('SELECT oid FROM pg_database WHERE datname=%s',(self.name,))
                self.oid = c.fetchone()[0]
                c.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO {}').format(sql.Identifier(self.name),sql.Identifier(self.groups['owner'])))
            with contextlib.closing(self.connect('owner')) as conn:
                with conn.cursor() as c:
                    c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.groups['owner'])))
                self.loaded_files = load_stage(conn,root=root,order=order)
                assert conn.get_transaction_status() == TRANSACTION_STATUS_INTRANS
                conn.commit()
            self.assert_catalog()
        except BaseException as exc:
            try:
                self.cleanup()
            except BaseException as cleanup:
                exc.add_note(f'fixture cleanup failed: {cleanup!r}')
            raise

    def connect(self, alias=None):
        if self.closed:
            raise RuntimeError('fixture already closed')
        conn = self.server.connect(self.name,self.roles[alias] if alias else None)
        self.connections.append(conn)
        return conn

    def assert_catalog(self):
        expected = TABLES if '19_requests.sql' in self.loaded_files else frozenset()
        with contextlib.closing(self.connect()) as conn, conn.cursor() as c:
            c.execute("SELECT nspname,nspowner FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','public') AND nspname !~ '^pg_(toast|temp)'")
            assert c.fetchall() == [('v24_cordis',role_state(self.admin,self.groups['owner'])[0])]
            c.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace='v24_cordis'::regnamespace AND relkind IN ('r','p','v','m')")
            assert set(c.fetchall()) == {(n,'r') for n in expected}
            c.execute("SELECT extname FROM pg_extension WHERE extname <> 'plpgsql'")
            assert c.fetchall() == []
        return expected

    def cleanup(self):
        if self.closed:
            return
        errors = []
        for conn in self.connections:
            try:
                if not conn.closed:
                    conn.rollback(); conn.close()
            except BaseException as e:
                errors.append(e)
        try:
            if not re.fullmatch(r'v24_cordis_dp1_'+str(os.getpid())+r'_[0-9a-f]{12}',self.name):
                raise RuntimeError('fixture name changed')
            with self.admin.cursor() as c:
                c.execute('SELECT oid FROM pg_database WHERE datname=%s',(self.name,))
                row = c.fetchone()
                if row:
                    if self.oid is None or row[0] != self.oid:
                        raise RuntimeError('database OID changed; refusing DROP')
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.name)))
                for name,state in reversed(self.identities):
                    actual = role_state(self.admin,name)
                    if actual is None:
                        continue
                    if actual != state or any(actual[1:6]):
                        raise RuntimeError(f'role identity/attributes changed: {name}')
                    c.execute('SELECT roleid FROM pg_auth_members WHERE member=%s',(actual[0],))
                    memberships = {r[0] for r in c.fetchall()}
                    alias = next((a for a,n in self.roles.items() if n==name),None)
                    expected = {role_state(self.admin,self.groups[alias])[0]} if alias else set()
                    if memberships != expected:
                        raise RuntimeError(f'role memberships changed: {name}')
                    c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        except BaseException as e:
            errors.append(e)
        finally:
            self.admin.close(); self.closed=True
        if errors:
            raise RuntimeError(f'exact fixture cleanup failed: {errors!r}')

    def __enter__(self):
        return self

    def __exit__(self, typ, exc, tb):
        try:
            self.cleanup()
        except BaseException as cleanup:
            if exc is not None:
                exc.add_note(f'fixture cleanup failed: {cleanup!r}')
            else:
                raise


def self_check():
    self_check_manifest()
    with Server() as server:
        with contextlib.closing(server.connect()) as conn, conn.cursor() as c:
            c.execute("SELECT current_setting('server_version'),current_setting('server_version_num')")
            version = c.fetchone(); assert int(version[1])//10000==18
            print('[environment] PostgreSQL',version,'psycopg2',psycopg2.__version__)
        with TestDB(server) as db:
            name,oid,identities = db.name,db.oid,list(db.identities)
            db.assert_catalog()
        with contextlib.closing(server.connect()) as conn, conn.cursor() as c:
            c.execute('SELECT oid FROM pg_database WHERE oid=%s OR datname=%s',(oid,name)); assert c.fetchall()==[]
            for role,state in identities:
                assert role_state(conn,role) is None
    print('[passed] Cordis fixture: transaction/catalog/role family/OID cleanup')


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--server-helper',action='store_true'); p.add_argument('--self-check',action='store_true')
    args=p.parse_args()
    if args.server_helper:
        server_helper()
    elif args.self_check:
        self_check()
    else:
        p.error('choose --self-check')
