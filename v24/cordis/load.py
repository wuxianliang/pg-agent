"""Isolated Cordis canonical-prefix loader; the caller owns the transaction."""
from pathlib import Path
from tempfile import TemporaryDirectory

SQL_ROOT = Path(__file__).resolve().parent / 'sql'
CANONICAL_ORDER = (
    '00_schema.sql', '10_installs.sql', '11_scopes.sql', '12_fibers.sql',
    '13_episodes.sql', '14_contributions.sql', '15_pins.sql', '16_runs.sql',
    '17_effects.sql', '18_events.sql', '19_requests.sql', '20_relations.sql',
    '30_triggers.sql', '40_advance.sql', '41_lifecycle.sql', '42_teardown.sql',
    '50_permissions.sql',
)
SQL_LOAD_ORDER = CANONICAL_ORDER


def validate_manifest(root=None, order=None):
    root = SQL_ROOT if root is None else Path(root)
    order = SQL_LOAD_ORDER if order is None else tuple(order)
    if not order or order != CANONICAL_ORDER[:len(order)]:
        raise ValueError('Cordis manifest must be a nonempty canonical prefix')
    paths = tuple(root / name for name in order)
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError('missing, symlinked or nonregular active SQL')
    for p in root.glob('*.sql'):
        if p.name not in CANONICAL_ORDER or p.is_symlink() or not p.is_file():
            raise ValueError('unregistered, symlinked or nonregular SQL')
    return paths


def load_stage(conn, *, root=None, order=None):
    if conn.autocommit:
        raise ValueError('Cordis load requires a caller transaction')
    paths = validate_manifest(root, order)
    with conn.cursor() as cur:
        for p in paths:
            cur.execute(p.read_text())
    return tuple(p.name for p in paths)


def self_check_manifest():
    assert len(CANONICAL_ORDER) == 17
    validate_manifest()
    with TemporaryDirectory(prefix='cordis-loader-') as tmp:
        root = Path(tmp)
        active = root / CANONICAL_ORDER[0]
        active.write_text('SELECT 1;')
        def reject(order=None):
            try:
                validate_manifest(root, order or CANONICAL_ORDER[:1])
            except ValueError:
                return
            raise AssertionError('invalid manifest admitted')
        reject(CANONICAL_ORDER[1:2])
        target = root / 'target'
        target.write_text('SELECT 1;')
        active.unlink(); active.symlink_to(target); reject(); active.unlink()
        active.write_text('SELECT 1;')
        inactive = root / CANONICAL_ORDER[1]
        inactive.symlink_to(target); reject(); inactive.unlink()
        extra = root / '99_extra.sql'
        extra.write_text('SELECT 1;'); reject(); extra.unlink()
        active.unlink(); active.mkdir(); reject()


if __name__ == '__main__':
    self_check_manifest()
    print('[passed] Cordis canonical loader and five refusal probes')
