"""Physical-line measurement for Cordis helper modules 40-49.

The 2026-10-28 user authorization waives the three line-count ceilings
(helper total, 43_loop.sql per-file, domain DDL) with no replacement number.
This module still measures the real tree and still rejects a missing required
helper file; it no longer rejects a tree for being large. The proof is a
measurement proof plus the required-file negative, not a numeric boundary.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory

HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql', '43_loop.sql', '44_events.sql')


def measured_helpers(sql_dir):
    """Return (total, per-file counts) for every active 40-49 helper file."""
    sql_dir = Path(sql_dir)
    files = sorted(p for p in sql_dir.glob('*.sql')
                   if p.name[:2].isdigit() and 40 <= int(p.name[:2]) <= 49)
    counts = {p.name: len(p.read_text().splitlines()) for p in files}
    return sum(counts.values()), counts


def assert_helper_budget(sql_dir):
    """Measure the helper tree and require every canonical helper file to exist.

    No upper bound is applied: physical lines are report-only under the
    2026-10-28 authorization. The missing-file rejection is retained.
    """
    total, counts = measured_helpers(sql_dir)
    missing = set(HELPERS) - set(counts)
    if missing:
        raise AssertionError(sorted(missing))
    return total, counts


def _write_tree(root, total):
    # Five named modules so the required-file check is the same one used on the real tree.
    shares = (total - 4, 1, 1, 1, 1)
    for name, lines in zip(HELPERS, shares):
        (root / name).write_text('x\n' * lines)


def prove_helper_budget_measurement():
    """Prove exact measurement and the surviving missing-required-file negative."""
    with TemporaryDirectory() as raw:
        root = Path(raw)
        _write_tree(root, 123)
        total, counts = assert_helper_budget(root)
        assert total == 123, (total, counts)
        assert total == sum(counts.values()), counts
        assert set(counts) == set(HELPERS), counts
    with TemporaryDirectory() as raw:
        root = Path(raw)
        _write_tree(root, 123)
        (root / '44_events.sql').unlink()
        try:
            assert_helper_budget(root)
        except AssertionError as exc:
            assert exc.args[0] == ['44_events.sql'], exc
        else:
            raise AssertionError('missing required helper 44_events.sql was admitted')
