import sqlite3
import time
from os import path, remove
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from skills.uexcorp.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from uexcorp.uexcorp.helper import Helper

class Database:

    DATABASE = "uexcorp.db"

    def __init__(
            self,
            data_path: str,
            version: str,
            helper: "Helper"
    ) -> None:
        self.helper = helper
        self.db_path = path.join(data_path, self.DATABASE)
        self.version = version
        self.cursor = None
        self.__inuse = False
        self.__queue_wait_time_max = 5  # seconds
        self.__init_connection()
        self.__init_database()

    def __init_database(self) -> None:
        if not self.table_exists("skill"):
            self.recreate_database()
            return

        self.cursor.execute("SELECT value FROM skill WHERE key = 'version'")
        if not self.cursor.fetchone()[0] == self.version:
            self.helper.get_handler_debug().write("Skill version mismatch, recreating database..")
            self.recreate_database()

    def __init_connection(self) -> None:
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

    def recreate_database(self) -> None:
        self.connection.close()
        remove(self.db_path)
        self.__init_connection()

        with open(path.join(path.dirname(__file__), "init.sql"), 'r', encoding="UTF-8") as file:
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
                self.helper.get_handler_debug().write(f"Database is still in use after waiting {self.__inuse}s, resetting inuse state (probably false).")
                self.__inuse = False
