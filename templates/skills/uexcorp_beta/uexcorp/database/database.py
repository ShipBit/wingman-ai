import sqlite3
from os import path, remove
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from skills.uexcorp_beta.uexcorp.helper import Helper
    except ImportError:
        from uexcorp_beta.uexcorp.helper import Helper

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
            self.cursor.executescript(file.read())

        # update version
        self.cursor.execute(
            "INSERT INTO skill (key, value) VALUES (?, ?)",
            ("version", self.version)
        )
        self.connection.commit()

    def table_exists(self, table: str) -> bool:
        self.cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
        return self.cursor.fetchone() is not None

    def table_clear(self, table: str) -> None:
        self.cursor.execute(f"DELETE FROM {table}")
        self.connection.commit()

    def get_connection(self) -> sqlite3.Connection:
        return self.connection

    def get_cursor(self) -> sqlite3.Cursor:
        return self.cursor