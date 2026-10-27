"""Physical-line budget for Cordis helper modules 40-49.

The predicate is file-based: temporary 40/41/42 trees of 5000 and 5001 lines
are passed to assert_helper_budget itself. A literal integer comparison is not
the proof.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory

HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql')
LIMIT = 5000


def assert_helper_budget(sql_dir):
    """Accept a helper tree whose physical lines sum to LIMIT. Reject above it."""
    sql_dir = Path(sql_dir)
    files = sorted(p for p in sql_dir.glob('*.sql')
                   if p.name[:2].isdigit() and 40 <= int(p.name[:2]) <= 49)
    counts = {p.name: len(p.read_text().splitlines()) for p in files}
    total = sum(counts.values())
    if total > LIMIT:
        raise AssertionError((total, counts))
    missing = set(HELPERS) - set(counts)
    if missing:
        raise AssertionError(sorted(missing))
    return total, counts


def _write_tree(root, total):
    # Three named modules so the required-file check is the same one used on the real tree.
    shares = (total - 2, 1, 1)
    for name, lines in zip(HELPERS, shares):
        (root / name).write_text('x\n' * lines)


def prove_helper_budget_boundary():
    """Invoke assert_helper_budget on trees of exactly 5000 and 5001 physical lines."""
    with TemporaryDirectory() as raw:
        root = Path(raw)
        _write_tree(root, LIMIT)
        total, counts = assert_helper_budget(root)
        assert total == LIMIT, (total, counts)
        assert sum(counts[name] for name in HELPERS) == LIMIT
    with TemporaryDirectory() as raw:
        root = Path(raw)
        _write_tree(root, LIMIT + 1)
        try:
            assert_helper_budget(root)
        except AssertionError as exc:
            assert exc.args[0][0] == LIMIT + 1, exc
        else:
            raise AssertionError('5001-line helper tree was admitted')
