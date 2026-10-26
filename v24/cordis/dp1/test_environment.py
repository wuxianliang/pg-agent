"""CDP1-E: execute with uv run python v24/cordis/dp1/test_environment.py."""
import contextlib
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from psycopg2.extensions import TRANSACTION_STATUS_INTRANS
from v24.cordis.load import CANONICAL_ORDER, SQL_ROOT, self_check_manifest, load_stage
from v24.cordis.dp1.setup_db import Server, TestDB, validate_local_dsn


def main():
    assert CANONICAL_ORDER == ('00_schema.sql','10_installs.sql','11_scopes.sql','12_fibers.sql',
        '13_episodes.sql','14_contributions.sql','15_pins.sql','16_runs.sql','17_effects.sql',
        '18_events.sql','19_requests.sql','20_relations.sql','30_triggers.sql','40_advance.sql','41_lifecycle.sql','50_permissions.sql')
    self_check_manifest()
    print('[CDP1-E1] exact manifest and five refusal families')
    socket='/tmp/cordis-dsn-probe'
    assert validate_local_dsn('host='+socket,socket)['host']==socket
    for dsn in ('host=127.0.0.1','host=/tmp/other','host='+socket+',/tmp/other',
                'host='+socket+' hostaddr=127.0.0.1','host='+socket+' service=bad',
                'host='+socket+' port=5432,5433'):
        try:
            validate_local_dsn(dsn,socket)
        except ValueError:
            pass
        else:
            raise AssertionError(dsn)
    for key in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE'):
        old=os.environ.get(key)
        try:
            os.environ[key]='probe'
            try:
                validate_local_dsn('host='+socket,socket)
            except ValueError:
                pass
            else:
                raise AssertionError(key)
        finally:
            if old is None: os.environ.pop(key,None)
            else: os.environ[key]=old
    print('[CDP1-E2] socket-only and libpq environment refusals')
    with Server() as server:
        with TestDB(server) as db:
            db.assert_catalog()
        with TemporaryDirectory(prefix='cordis-empty-') as tmp:
            root=Path(tmp); (root/CANONICAL_ORDER[0]).write_text((SQL_ROOT/CANONICAL_ORDER[0]).read_text())
            with TestDB(server,root=root,order=CANONICAL_ORDER[:1]) as db:
                conn=db.connect('owner')
                with conn.cursor() as c:
                    c.execute('DROP SCHEMA v24_cordis')
                    from psycopg2 import sql
                    c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
                load_stage(conn,root=root,order=CANONICAL_ORDER[:1])
                assert conn.get_transaction_status()==TRANSACTION_STATUS_INTRANS
                conn.rollback()
                db.assert_catalog()
                conn.autocommit=True
                try:
                    load_stage(conn,root=root,order=CANONICAL_ORDER[:1])
                except ValueError:
                    pass
                else:
                    raise AssertionError('autocommit load admitted')
                with conn.cursor() as c:
                    c.execute("SELECT oid FROM pg_proc WHERE oid IN ('pg_catalog.sha256(bytea)'::regprocedure,'pg_catalog.gen_random_uuid()'::regprocedure)")
                    assert len(c.fetchall())==2
                    c.execute("SELECT count(*) FROM pg_depend WHERE classid='pg_proc'::regclass AND objid IN ('pg_catalog.sha256(bytea)'::regprocedure,'pg_catalog.gen_random_uuid()'::regprocedure) AND deptype='e'")
                    assert c.fetchone()[0]==0
        print('[CDP1-E3] current and empty prefix catalogs; caller transaction and core functions')
    print('[passed] CDP1-E')


if __name__=='__main__':
    main()
