import sqlite3
import time
import os
from typing import TYPE_CHECKING

from sympy import false

if TYPE_CHECKING:
    try:
        from skills.uexcorp.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from uexcorp.uexcorp.helper import Helper

class Database:

    def __init__(
            self,
            data_path: str,
            version: str,
            helper: "Helper"
    ) -> None:
        self.helper = helper
        self.db_path = data_path
        self.db_info_file = os.path.join(self.db_path, 'db_info.txt')
        self.db_name_base = 'uexcorp.db'
        self.db_name_complete = self.db_name_base
        self.version = version
        self.cursor = None
        self.connection = None
        self.__inuse = False
        self.__set_db_name_current()
        self.__queue_wait_time_max = 30 # in seconds
        self.__init_connection()
        self.__init_database()

    def __set_db_name_current(self) -> None:
        """Set the current database name."""
        # check for db info file and read content
        if not os.path.exists(self.db_info_file):
            self.__set_db_name_new()
        else:
            with open(self.db_info_file, 'r', encoding='UTF-8') as file:
                content = file.read().strip()
                if content:
                    self.db_name_complete = content
                    self.helper.get_handler_debug().write(f"Database name set to {self.db_name_complete} from file.")
                else:
                    self.__set_db_name_new()

    def __set_db_name_new(self) -> None:
        timestamp = time.time() # needs sub seconds for uniqueness
        self.db_name_complete = f"{timestamp}_{self.db_name_base}"
        with open(self.db_info_file, 'w', encoding='UTF-8') as file:
            file.write(self.db_name_complete)
        self.helper.get_handler_debug().write(f"Database name set to {self.db_name_complete} and written to file.")

    def __init_database(self) -> None:
        if not self.table_exists("skill"):
            self.recreate_database()
            return

        self.cursor.execute("SELECT value FROM skill WHERE key = 'version'")
        if not self.cursor.fetchone()[0] == self.version:
            self.helper.get_handler_debug().write("Skill version mismatch, recreating database..")
            self.recreate_database()

    def __init_connection(self) -> None:
        complete_path = os.path.join(self.db_path, self.db_name_complete)
        self.connection = sqlite3.connect(complete_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

    def recreate_database(self) -> None:
        self.connection.close()

        # For error prevention on multiple instances, we will always create a completely new database.
        # So we will delete all old ones that are no longer needed.
        # But as they might still be used by another process, we wrap it in a try-except block.
        # No elegant solution, but it works.
        db_files = [f for f in os.listdir(self.db_path) if f.endswith('.db')]
        for db_file in db_files:
            try:
                os.remove(os.path.join(self.db_path, db_file))
            except Exception:
                self.helper.get_handler_debug().write(
                    f"Failed to remove database file '{os.path.join(self.db_path, db_file)}'."
                )

        self.__set_db_name_new()
        self.__init_connection()

        with open(os.path.join(os.path.dirname(__file__), "init.sql"), 'r', encoding="UTF-8") as file:
            self.executescript(file.read())

        # update version
        self.execute(
            "INSERT INTO skill (key, value) VALUES (?, ?)",
            ("version", self.version)
        )
        self.connection.commit()

    def table_exists(self, table: str) -> bool:
        self.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
        return self.cursor.fetchone() is not None

    def table_clear(self, table: str) -> None:
        self.execute(f"DELETE FROM {table}")
        self.connection.commit()

    def get_connection(self) -> sqlite3.Connection:
        return self.connection

    def get_cursor(self) -> sqlite3.Cursor:
        return self.cursor

    def execute(self, sql: str, parameters: tuple|dict|list = ()) -> bool:
        self.__wait_for_database_capacity()

        self.__inuse = True
        if not self.get_cursor():
            self.helper.get_handler_debug().write(
                f"Skipped SQL: {sql} with parameters: {parameters}. No active cursor found. Probably old instance."
            )
            return False
        else:
            self.get_cursor().execute(sql, parameters)
        self.__inuse = False
        return True

    def executescript(self, sql: str) -> bool:
        self.__wait_for_database_capacity()

        self.__inuse = True
        self.get_cursor().executescript(sql)
        self.__inuse = False
        return True

    def __wait_for_database_capacity(self) -> None:
        if self.__inuse:
            self.helper.get_handler_debug().write("Database is currently in use, waiting for it to be free...")

            for _ in range(int(self.__queue_wait_time_max / 0.1)):
                if not self.__inuse:
                    self.helper.get_handler_debug().write("Database is now free, proceeding with the action.")
                    break
                time.sleep(0.1)

            if self.__inuse:
                self.helper.get_handler_debug().write(
                    f"Database is still in use after waiting {self.__queue_wait_time_max}s, forcing inuse state of false."
                )
                self.__inuse = False

    def destroy(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.cursor = None
