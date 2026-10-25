"""Independent, transactional SQL loader for v24 stages."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
SQL_ROOT = ROOT / "sql"
CANONICAL_ORDER = (
    "00_schema.sql",
    "10_schema.sql",
    "20_triggers.sql",
    "30_advance.sql",
    "40_interpreters.sql",
    "45_capability.sql",
    "46_cleanup.sql",
    "47_verbs.sql",
    "48_loop.sql",
    "49_recovery.sql",
    "49_host_reads.sql",
    "50_permissions.sql",
)
# W4 activates the command interpreter and delta applier.
SQL_LOAD_ORDER = (
    "00_schema.sql",
    "10_schema.sql",
    "20_triggers.sql",
    "30_advance.sql",
    "40_interpreters.sql",
    "45_capability.sql",
    "46_cleanup.sql",
    "47_verbs.sql",
    "48_loop.sql",
    "49_recovery.sql",
    "49_host_reads.sql",
    "50_permissions.sql",
)


def _validate_manifest(
    sql_root: Path,
    canonical_order: tuple[str, ...],
    declared_order: tuple[str, ...],
) -> tuple[Path, ...]:
    """Validate a declared prefix against files present in one SQL directory."""
    if (
        not declared_order
        or len(declared_order) > len(canonical_order)
        or tuple(declared_order) != canonical_order[:len(declared_order)]
    ):
        raise ValueError("v24 manifest must be a nonempty canonical ordered prefix")

    paths = tuple(sql_root / name for name in declared_order)
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError("missing or symlinked v24 SQL file")

    present = tuple(sql_root.glob("*.sql"))
    if any(not path.is_file() or path.is_symlink() for path in present):
        raise ValueError("non-regular or symlinked v24 SQL file")
    unexpected = {path.name for path in present} - set(canonical_order)
    if unexpected:
        raise ValueError(f"unregistered v24 SQL file(s): {sorted(unexpected)}")
    return paths


def validate_manifest() -> tuple[Path, ...]:
    """Return active SQL paths after rejecting gaps, symlinks, and extras."""
    return _validate_manifest(SQL_ROOT, CANONICAL_ORDER, SQL_LOAD_ORDER)


def load_stage(conn) -> tuple[str, ...]:
    """Execute the registered prefix in the caller's transaction; never commit."""
    if conn.autocommit:
        raise ValueError("load_stage requires a transaction, not autocommit")
    paths = validate_manifest()
    with conn.cursor() as cur:
        for path in paths:
            cur.execute(path.read_text(encoding="utf-8"))
    return tuple(path.name for path in paths)


def self_check_manifest() -> None:
    """Assert the current manifest and each required rejection path."""
    paths = validate_manifest()
    assert tuple(path.name for path in paths) == SQL_LOAD_ORDER

    with TemporaryDirectory(prefix="v24-loader-check-") as temporary:
        root = Path(temporary) / "sql"
        root.mkdir()
        active_file = root / CANONICAL_ORDER[0]
        active_file.write_text("SELECT 1;\n", encoding="utf-8")

        try:
            _validate_manifest(root, CANONICAL_ORDER, ("10_schema.sql",))
        except ValueError:
            pass
        else:
            raise AssertionError("loader accepted a non-prefix manifest")

        target = Path(temporary) / "target.sql"
        target.write_text("SELECT 1;\n", encoding="utf-8")
        active_file.unlink()
        active_file.symlink_to(target)
        try:
            _validate_manifest(root, CANONICAL_ORDER, (CANONICAL_ORDER[0],))
        except ValueError:
            pass
        else:
            raise AssertionError("loader accepted a symlinked SQL path")

        active_file.unlink()
        active_file.write_text("SELECT 1;\n", encoding="utf-8")
        (root / "90_unregistered.sql").write_text("SELECT 1;\n", encoding="utf-8")
        try:
            _validate_manifest(root, CANONICAL_ORDER, (CANONICAL_ORDER[0],))
        except ValueError:
            pass
        else:
            raise AssertionError("loader accepted an unregistered SQL file")

        (root / "90_unregistered.sql").unlink()
        inactive_file = root / CANONICAL_ORDER[1]
        inactive_file.symlink_to(target)
        try:
            _validate_manifest(root, CANONICAL_ORDER, (CANONICAL_ORDER[0],))
        except ValueError:
            pass
        else:
            raise AssertionError("loader accepted an inactive symlinked SQL path")
        inactive_file.unlink()
        active_file.unlink()
        active_file.mkdir()
        try:
            _validate_manifest(root, CANONICAL_ORDER, (CANONICAL_ORDER[0],))
        except ValueError:
            pass
        else:
            raise AssertionError("loader accepted a directory as SQL")


if __name__ == "__main__":
    try:
        self_check_manifest()
    except Exception as exc:
        print(f"[failed] v24 loader self-check: {type(exc).__name__}: {exc}")
        raise
    print("[passed] v24 loader self-check")
