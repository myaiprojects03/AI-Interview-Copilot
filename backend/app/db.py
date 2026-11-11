"""Postgres connection pool tuned for Supabase's pooler, plus a retry for dropped connections.

Supabase's pooler closes connections that sit idle. asyncpg only notices when it next uses
one ("connection was closed in the middle of operation"). Two defences:
- idle connections are recycled after 15 s, so a dead one is rarely handed out;
- `retry_on_disconnect` reruns a store method once on a fresh connection if it still hits one.
  These errors happen when sending the query, before anything is committed, so a rerun is safe.
"""

import functools
import inspect
import logging

log = logging.getLogger(__name__)

IDLE_RECYCLE_S = 15.0


def _is_disconnect(exc: BaseException) -> bool:
    import asyncpg

    dropped = (
        asyncpg.exceptions.ConnectionDoesNotExistError
        | asyncpg.exceptions.InterfaceError
        | ConnectionResetError
        | ConnectionAbortedError
    )
    return isinstance(exc, dropped)


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 5, **kwargs):
    import asyncpg

    return await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        statement_cache_size=0,  # required behind poolers that don't keep prepared statements
        max_inactive_connection_lifetime=IDLE_RECYCLE_S,
        **kwargs,
    )


def retry_on_disconnect(cls):
    """Class decorator: every public async method gets one retry on a dropped connection."""
    for name, fn in list(vars(cls).items()):
        if name.startswith("_") or not inspect.iscoroutinefunction(fn):
            continue

        def wrap(fn):
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    if not _is_disconnect(exc):
                        raise
                    log.warning("database connection dropped in %s; retrying once", fn.__name__)
                    return await fn(*args, **kwargs)

            return wrapper

        setattr(cls, name, wrap(fn))
    return cls
