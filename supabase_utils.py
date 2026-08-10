"""supabase_utils.py — Supabase client bootstrap for xai-colossus-energy.

Reads SUPABASE_URL and SUPABASE_KEY from environment variables.
If either is absent (e.g. CI with no real creds), returns a NullClient
that logs writes at INFO and never raises — so no module crashes on import.

Usage
-----
    from supabase_utils import get_supabase_client, write_completion_receipt

    sb = get_supabase_client()
    write_completion_receipt("ISSUE_5", {"status": "ok"})

``write_completion_memory`` remains as a backward-compatible alias, but the
canonical sink is now ``apex_ops_log`` rather than the retired
``connector_jobs`` queue.
"""

import json
import logging
import os

logger = logging.getLogger("supabase_utils")


class _NullSupabaseClient:
    """Drop-in no-op client used when SUPABASE_URL/KEY are not set."""

    class _NullTable:
        def insert(self, *a, **kw): return self
        def upsert(self, *a, **kw): return self
        def select(self, *a, **kw): return self
        def execute(self): return {"data": [], "error": None}

    def table(self, name: str) -> "_NullSupabaseClient._NullTable":
        logger.debug("[NullSupabase] table(%s) called — no-op", name)
        return self._NullTable()


def get_supabase_client():
    """Return a real Supabase client or a NullClient if creds are missing."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        logger.info(
            "SUPABASE_URL/KEY not set — using NullClient (writes are no-ops)"
        )
        return _NullSupabaseClient()
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except ImportError:
        logger.warning(
            "supabase-py not installed — using NullClient. "
            "Install with: pip install supabase"
        )
        return _NullSupabaseClient()


def write_completion_receipt(task_id: str, payload: dict) -> None:
    """Write a completion receipt to the canonical GlacierEQ ops log.

    The old ``connector_jobs`` target was a queue contract and never matched
    this repository's telemetry payload. ``apex_ops_log`` is the live local
    operations receipt surface.
    """
    sb = get_supabase_client()
    try:
        row = {
            "action": "xai_energy_balancer_completion",
            "status": str(payload.get("status", "completed")),
            "details": json.dumps(
                {
                    "task_id": task_id,
                    "repo": "xai-colossus-energy",
                    "payload": payload,
                    "contract": "glaciereq-apex-ops-log-v1",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        sb.table("apex_ops_log").insert(row).execute()
        logger.info("write_completion_receipt: task_id=%s written", task_id)
    except Exception as exc:
        logger.error("write_completion_receipt failed: %s", exc)


def write_completion_memory(task_id: str, payload: dict) -> None:
    """Backward-compatible alias for :func:`write_completion_receipt`."""
    write_completion_receipt(task_id, payload)
