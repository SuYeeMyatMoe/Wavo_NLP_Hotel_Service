"""Small process-local pool; transaction-local roles never survive a checkout."""

import atexit
import os
from threading import Lock

_lock = Lock()
_pool = None
_dsn = None


def pool():
    global _pool, _dsn
    dsn = os.environ["DATABASE_URL"]
    with _lock:
        if _pool is None or _dsn != dsn or _pool.closed:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                dsn,
                min_size=1,
                max_size=int(os.getenv("WAVO_DB_POOL_MAX", "4")),
                timeout=10,
                max_idle=120,
                check=ConnectionPool.check_connection,
                kwargs={"row_factory": dict_row, "connect_timeout": 10},
                name="wavo",
            )
            _dsn = dsn
        return _pool


def close():
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(close)
