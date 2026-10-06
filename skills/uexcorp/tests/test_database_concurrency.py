"""Concurrency stress test for skills.uexcorp.uexcorp.database.Database.

No pytest. Run from the project root:

    venv/bin/python -m skills.uexcorp.tests.test_database_concurrency

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
Database opens its sqlite3 connection with check_same_thread=False and exposes a
single shared cursor. It is reached from multiple threads (tool execution,
imports). Concurrent execute()/fetch()/commit() on one connection corrupts
SQLite's internal heap and kills the whole process with a native SIGSEGV -- the
same class of crash that took down Wingman Core via the persistent-memory
service. The old self.__inuse boolean guard was non-atomic and could not prevent
it. This test hammers the connection from many threads through the public API
(execute / execute_fetchall / execute_fetchmany / commit); with the per-instance
RLock it runs clean and the row count stays exact.
"""

import os
import tempfile
import threading


class _NullHandler:
    def write(self, *args, **kwargs):
        return None


class _FakeHelper:
    """Minimal helper: Database only needs debug/error handlers with .write()."""

    def get_handler_debug(self):
        return _NullHandler()

    def get_handler_error(self):
        return _NullHandler()


def check_concurrent_access() -> None:
    # Imported lazily so a syntax/import error surfaces inside the test run.
    from skills.uexcorp.uexcorp.database.database import Database

    threads_count = 16
    iterations = 40

    tmp_dir = tempfile.mkdtemp(prefix="uexcorp_db_test_")
    db = Database(tmp_dir, version="test-1", helper=_FakeHelper())

    # A dedicated table so we don't depend on the real uex schema specifics.
    db.executescript(
        "CREATE TABLE IF NOT EXISTS stress (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);"
    )
    db.commit()

    errors: list[BaseException] = []
    barrier = threading.Barrier(threads_count)

    def worker(worker_id: int) -> None:
        # Release all threads at once to maximise overlap on the shared cursor.
        barrier.wait()
        try:
            for i in range(iterations):
                db.execute(
                    "INSERT INTO stress (v) VALUES (?)",
                    (f"worker {worker_id} row {i}",),
                )
                db.commit()
                db.execute_fetchall("SELECT id, v FROM stress")
                db.execute_fetchmany("SELECT id, v FROM stress", (), 5)
        except BaseException as exc:  # noqa: BLE001 - surface everything
            errors.append(exc)

    workers = [threading.Thread(target=worker, args=(w,)) for w in range(threads_count)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert not errors, f"Concurrent access raised: {errors[:3]}"

    rows = db.execute_fetchall("SELECT COUNT(*) FROM stress")
    count = rows[0][0]
    expected = threads_count * iterations
    assert count == expected, f"Expected {expected} rows, got {count}"

    db.destroy()
    try:
        for name in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, name))
        os.rmdir(tmp_dir)
    except OSError:
        pass


def main() -> None:
    check_concurrent_access()
    print("ALL OK")


if __name__ == "__main__":
    main()
