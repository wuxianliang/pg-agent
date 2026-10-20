"""Independent, transactional SQL loader. No historical loader is imported."""
from pathlib import Path

SQL_ROOT = Path(__file__).resolve().parent / "sql"
# Real registered prefix. W4 will append final permissions.
PHASE0_SQL_LOAD_ORDER = (
    "00_extensions.sql", "10_schema.sql", "20_ledger.sql",
    "30_ce.sql", "40_permissions.sql",
)
CORE_SQL_LOAD_ORDER = PHASE0_SQL_LOAD_ORDER


def validate_manifest() -> tuple[Path, ...]:
    """Fail on gaps, extra SQL, symlinks, or an unregistered implementation."""
    if not CORE_SQL_LOAD_ORDER or tuple(CORE_SQL_LOAD_ORDER) != PHASE0_SQL_LOAD_ORDER[:len(CORE_SQL_LOAD_ORDER)]:
        raise ValueError("core manifest must be a nonempty ordered Phase 0 prefix")
    paths = tuple(SQL_ROOT / name for name in CORE_SQL_LOAD_ORDER)
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError("missing or symlinked core SQL file")
    if {path.name for path in SQL_ROOT.glob("*.sql")} != set(CORE_SQL_LOAD_ORDER):
        raise ValueError("unregistered core SQL file")
    return paths


def load_core(conn) -> tuple[str, ...]:
    """Execute the registered prefix in the caller's transaction; never commit.

    The owner must connect to an empty fixture database. The context manager in
    setup_db commits the entire load or rolls it back; autocommit is rejected.
    """
    if conn.autocommit:
        raise ValueError("load_core requires a transaction, not autocommit")
    paths = validate_manifest()
    with conn.cursor() as cur:
        for path in paths:
            cur.execute(path.read_text(encoding="utf-8"))
    return tuple(path.name for path in paths)
