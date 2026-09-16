"""Create the isolated v8 G13 compat database, load through the compat
stage and seed the FIXED-NAME compat surface.

Seeds (fixed names, stable across runs -- the P0C host-agnostic fixtures
cite them):

* one workspace + one slice ``g13-compat-slice``;
* five grants for the compat driver subject ``dsh-compat`` covering the
  capabilities the seal/dispatch/completion and append paths gate
  (authorize_effect / effect_submit / tool_resolve / event_append /
  stream_ingest). Under the Wave1 always-pass stub these rows are
  harmless-but-present; once the G12 gates turn real, the compat cases
  that walk the seal/dispatch paths pass BY THESE SEEDS (plan file
  ownership note) -- no per-case grant fixture needed after the merge;
* the pinned-host adapter manifest row: dispatch_interception NULL+note
  (the section 5.2 pre-verification of the pinned DSH package is blocked,
  see v8/compat/pinned_host_manifest.json) and a conservative
  driver_switch_capability='unsupported' declaration (deviation ledger:
  without the pinned package the supported claim cannot be made).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_compat"
STAGE = "compat"

WS = "00000013-0013-4013-8013-000000000013"
SLICE = "00000013-0013-4013-8013-000000000101"
COMPAT_DRIVER = "dsh-compat"
GRANTS = [
    ("g13-grant-authorize-effect", "authorize_effect"),
    ("g13-grant-effect-submit", "effect_submit"),
    ("g13-grant-tool-resolve", "tool_resolve"),
    ("g13-grant-event-append", "event_append"),
    ("g13-grant-stream-ingest", "stream_ingest"),
]


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    grant_sql = "\n".join(
        f"""INSERT INTO grants(grant_id, workspace_id, slice_id, subject_kind,
                   subject_id, capability, not_before, expires_at)
VALUES ('{gid}', '{WS}'::uuid, '{SLICE}'::uuid, 'driver',
        '{COMPAT_DRIVER}', '{cap}', now(), now() + interval '30 days');"""
        for gid, cap in GRANTS)
    seed = f"""
INSERT INTO slices(slice_id, workspace_id, name, kind, spec)
VALUES ('{SLICE}'::uuid, '{WS}'::uuid, 'g13-compat-slice', 'tool_set',
        '{{"scope": "compat-p0c"}}'::jsonb);
{grant_sql}
SELECT v_compat_manifest_register(
    'dsh-compat-adapter@1', '{COMPAT_DRIVER}', NULL,
    'pinned DSH package identity unconfirmed: dispatch_interception '
    'awaits the section 5.2 pre-verification (blocked, see '
    'v8/compat/pinned_host_manifest.json)',
    'unsupported', '[]'::jsonb, '[]'::jsonb);
"""
    run_psql(s, DB, seed)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
