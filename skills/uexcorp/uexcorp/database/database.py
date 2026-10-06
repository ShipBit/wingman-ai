import sqlite3
import threading
import time
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper


class Database:

    def __init__(self, data_path: str, version: str, helper: "Helper") -> None:
        self.helper = helper
        self.db_path = data_path
        self.db_info_file = os.path.join(self.db_path, "db_info.txt")
        self.db_name_base = "uexcorp.db"
        self.db_name_complete = self.db_name_base
        self.version = version
        self.cursor = None
        self.connection = None
        # The connection is opened with check_same_thread=False and is reached
        # from multiple threads (tool execution, imports). A single sqlite3
        # connection/cursor is NOT safe for concurrent use -- two threads inside
        # execute()/fetch()/commit() at once corrupt SQLite's heap and crash the
        # whole process with a native SIGSEGV. This reentrant lock serializes ALL
        # connection access; it replaces the previous self.__inuse flag, which
        # was a non-atomic best-effort guard that could not actually prevent the
        # race. Reentrant so atomic helpers (execute_fetchall etc.) can call the
        # locked execute() while already holding it.
        self._lock = threading.RLock()
        self.__set_db_name_current()
        self.__init_connection()
        self.__init_database()

    def __set_db_name_current(self) -> None:
        """Set the current database name."""
        # check for db info file and read content
        if not os.path.exists(self.db_info_file):
            self.__set_db_name_new()
        else:
            with open(self.db_info_file, "r", encoding="UTF-8") as file:
                content = file.read().strip()
                if content:
                    self.db_name_complete = content
                    self.helper.get_handler_debug().write(
                        f"Database name set to {self.db_name_complete} from file."
                    )
                else:
                    self.__set_db_name_new()

    def __set_db_name_new(self) -> None:
        timestamp = time.time()  # needs sub seconds for uniqueness
        self.db_name_complete = f"{timestamp}_{self.db_name_base}"
        with open(self.db_info_file, "w", encoding="UTF-8") as file:
            file.write(self.db_name_complete)
        self.helper.get_handler_debug().write(
            f"Database name set to {self.db_name_complete} and written to file."
        )

    def __init_database(self) -> None:
        if not self.table_exists("skill"):
            self.recreate_database()
            return

        rows = self.execute_fetchmany(
            "SELECT value FROM skill WHERE key = 'version'", (), 1
        )
        if not rows or not rows[0][0] == self.version:
            self.helper.get_handler_debug().write(
                "Skill version mismatch, recreating database.."
            )
            self.recreate_database()

    def __init_connection(self) -> None:
        complete_path = os.path.join(self.db_path, self.db_name_complete)
        self.connection = sqlite3.connect(complete_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

    def recreate_database(self) -> None:
        with self._lock:
            self.connection.close()

            # For error prevention on multiple instances, we will always create a completely new database.
            # So we will delete all old ones that are no longer needed.
            # But as they might still be used by another process, we wrap it in a try-except block.
            # No elegant solution, but it works.
            db_files = [f for f in os.listdir(self.db_path) if f.endswith(".db")]
            for db_file in db_files:
                try:
                    os.remove(os.path.join(self.db_path, db_file))
                except Exception:
                    self.helper.get_handler_debug().write(
                        f"Failed to remove database file '{os.path.join(self.db_path, db_file)}'."
                    )

            self.__set_db_name_new()
            self.__init_connection()

            with open(
                os.path.join(os.path.dirname(__file__), "init.sql"), "r", encoding="UTF-8"
            ) as file:
                self.executescript(file.read())

            # update version
            self.execute(
                "INSERT INTO skill (key, value) VALUES (?, ?)", ("version", self.version)
            )
            self.connection.commit()

    def table_exists(self, table: str) -> bool:
        rows = self.execute_fetchmany(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'",
            (),
            1,
        )
        return len(rows) > 0

    def table_clear(self, table: str) -> None:
        with self._lock:
            self.execute(f"DELETE FROM {table}")
            self.connection.commit()

    def get_connection(self) -> sqlite3.Connection:
        return self.connection

    def get_cursor(self) -> sqlite3.Cursor:
        return self.cursor

    def execute(self, sql: str, parameters: tuple | dict | list = ()) -> bool:
        with self._lock:
            if not self.cursor:
                self.helper.get_handler_debug().write(
                    f"Skipped SQL: {sql} with parameters: {parameters}. No active cursor found. Probably old instance."
                )
                return False
            try:
                self.cursor.execute(sql, parameters)
            except Exception as e:
                self.helper.get_handler_error().write(
                    "database.execute", [sql, parameters], e
                )
                raise e
            return True

    def executescript(self, sql: str) -> bool:
        with self._lock:
            try:
                self.cursor.executescript(sql)
            except Exception as e:
                self.helper.get_handler_error().write(
                    "database.executescript", [sql], e
                )
                raise e
            return True

    def commit(self) -> None:
        """Commit the current transaction (serialized against all DB access)."""
        with self._lock:
            if self.connection:
                self.connection.commit()

    def execute_fetchall(
        self, sql: str, parameters: tuple | dict | list = ()
    ) -> list:
        """Run a query and fetch all rows atomically.

        The connection exposes a single shared cursor, so the execute and the
        fetch MUST happen under one lock acquisition -- otherwise another
        thread's execute() could move the cursor between them (wrong rows, or a
        crash). Reentrant lock lets us reuse the locked execute().
        """
        with self._lock:
            if not self.execute(sql, parameters):
                return []
            return self.cursor.fetchall()

    def execute_fetchmany(
        self, sql: str, parameters: tuple | dict | list = (), size: int = 1
    ) -> list:
        """Run a query and fetch up to `size` rows atomically. See execute_fetchall."""
        with self._lock:
            if not self.execute(sql, parameters):
                return []
            return self.cursor.fetchmany(size)

    def destroy(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self.connection:
                self.connection.close()
                self.connection = None
                self.cursor = None
