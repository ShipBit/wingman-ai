"""The skill's sqlite database: shared by several threads, replaced in one transaction, and
filtered with the SQL filter the tools build their queries from."""

import threading
from types import SimpleNamespace

import pytest

from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
from skills.uexcorp.uexcorp.database.database import Database
from skills.uexcorp.uexcorp.database.filter import Filter
from tests.skills.uexcorp.support import NullHandler


def test_many_threads_can_use_the_one_connection_at_once(tmp_path):
    """Concurrent execute/fetch/commit on one sqlite connection used to corrupt its heap and kill
    the whole process with a native SIGSEGV. With the per-instance lock it runs clean."""
    threads_count, iterations = 16, 40
    quiet = SimpleNamespace(get_handler_debug=NullHandler, get_handler_error=NullHandler)
    database = Database(str(tmp_path), version="test-1", helper=quiet)
    database.executescript("CREATE TABLE IF NOT EXISTS stress (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);")
    database.commit()
    errors: list[BaseException] = []
    barrier = threading.Barrier(threads_count)

    def worker(worker_id: int) -> None:
        barrier.wait()  # all threads at once, for the most overlap
        try:
            for i in range(iterations):
                database.execute("INSERT INTO stress (v) VALUES (?)", (f"worker {worker_id} row {i}",))
                database.commit()
                database.execute_fetchall("SELECT id, v FROM stress")
                database.execute_fetchmany("SELECT id, v FROM stress", (), 5)
        except BaseException as exc:  # noqa: BLE001 - surface everything
            errors.append(exc)

    workers = [threading.Thread(target=worker, args=(w,)) for w in range(threads_count)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()

    assert not errors, errors[:3]
    assert database.execute_fetchall("SELECT COUNT(*) FROM stress")[0][0] == threads_count * iterations
    database.destroy()


def test_a_table_replacement_that_fails_leaves_the_old_rows(helper, db):
    db.execute("INSERT INTO terminal (id, name) VALUES (1, 'Old')")
    db.commit()

    with pytest.raises(Exception):
        db.replace_table("terminal", ["id", "no_such_column"], [(2, 3)])

    assert [row["name"] for row in db.execute_fetchall("SELECT name FROM terminal")] == ["Old"]


@pytest.fixture
def terminals(db):
    """Terminals T1 to T4 with a nullable number each: 0, 5, NULL and -5."""
    for terminal_id, value in ((1, 0), (2, 5), (3, None), (4, -5)):
        db.execute("INSERT INTO terminal (id, name, mcs) VALUES (?, ?, ?)", (terminal_id, f"T{terminal_id}", value))


def ids(*wheres, groups=()) -> list[int]:
    data_access = TerminalDataAccess()
    for where in wheres:
        data_access.filter.where(*where)
    for group, is_or in groups:
        data_access.apply_filter(group, is_or)
    return sorted(terminal.get_id() for terminal in data_access.load())


def named(name: str) -> Filter:
    group = Filter()
    group.where("name", name)
    return group


def test_null_counts_as_zero_only_where_zero_matches(terminals):
    assert ids(("mcs", 0, ">")) == [2]
    assert ids(("mcs", 0, "<")) == [4]
    assert ids(("mcs", 0, "!=")) == [2, 4]
    assert ids(("mcs", 0)) == [1, 3]
    assert ids(("mcs", None)) == [3]
    assert ids(("mcs", None, "!=")) == [1, 2, 4]


def test_lists_work_with_equality_operators(terminals):
    assert ids(("name", ["T1", "T2"], "!=")) == [3, 4]
    assert ids(("name", ["T1", "T2"], "=")) == [1, 2]
    assert ids(("name", "T1", "NOT IN")) == [2, 3, 4]


def test_filter_groups_keep_their_precedence(terminals):
    # (mcs = 5 OR name = T1) AND name = T2, not mcs = 5 OR (name = T1 AND name = T2)
    assert ids(("mcs", 5), groups=((named("T1"), True), (named("T2"), False))) == [2]
    assert ids(("id", 1), ("mcs", 0), groups=((named("T3"), True),)) == [1, 3]
