# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""supabase_utils.py — Supabase client bootstrap for xai-colossus-energy.

Reads SUPABASE_URL and SUPABASE_KEY from environment variables.
If either is absent (e.g. CI with no real creds), returns a NullClient
that logs writes at INFO and never raises — so no module crashes on import.

Usage
-----
    from supabase_utils import get_supabase_client, write_completion_memory

    sb = get_supabase_client()          # None in CI, real client in prod
    write_completion_memory("ISSUE_5", {"status": "ok"})  # always safe
"""

import logging
import os
import time
import uuid

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


def write_completion_memory(task_id: str, payload: dict) -> None:
    """Write a task completion record to the connector_jobs table.

    Always safe: logs at INFO and returns if Supabase is unavailable.
    """
    sb = get_supabase_client()
    row = {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "connector": "xai_energy_balancer",
        "repo": "xai-colossus-energy",
        "status": "COMPLETED",
        "ts": time.time(),
        "metadata": payload,
    }
    try:
        sb.table("connector_jobs").insert(row).execute()
        logger.info("write_completion_memory: task_id=%s written", task_id)
    except Exception as exc:
        logger.error("write_completion_memory failed: %s", exc)
