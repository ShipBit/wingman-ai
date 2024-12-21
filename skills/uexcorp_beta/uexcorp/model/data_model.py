import json

from skills.uexcorp_beta.uexcorp.helper import Helper


class DataModel:

    required_keys = ["table"]

    def __init__(
        self,
        table: str,
    ):
        self.helper = Helper.get_instance()
        self.table = table
        self.data = {}

    def get_data_for_ai(self) -> dict:
        return self.get_data()

    def persist(self, skip_commit: bool = False) -> bool:
        if not self.data or not self.table:
            return False

        # Add common data to the model
        for key, value in self.helper.get_handler_import().get_common_data().items():
            if key in self.data:
                self.data[key] = value

        clean_data = {}
        for key, value in self.data.items():
            if isinstance(value, bool):
                value = int(value)
            elif isinstance(value, dict) or isinstance(value, list):
                value = json.dumps(value)
            clean_data[f"`{key}`"] = value

        self.helper.get_database().get_cursor().execute(
            f"INSERT OR REPLACE INTO {self.table} ({','.join(clean_data.keys())}) VALUES ({','.join(['?'] * len(clean_data))})",
            tuple(clean_data.values())
        )
        if not skip_commit:
            self.helper.get_database().get_connection().commit()
        return True

    def get_data(self) -> dict:
        return self.data

    def set_data(self, data: dict):
        for key, value in self.data.items():
            if key in data:
                self.data[key] = data[key]

    def get_database_table(self) -> str:
        return self.table

    def load_by_value(self, key: str, value: int|str|None = None) -> bool:
        if not self.table:
            return False

        if value is not None:
            self.data[key] = value

        self.helper.get_database().get_cursor().execute(
            f"SELECT * FROM `{self.table}` WHERE `{key}` = ?",
            (self.data[key],)
        )
        result = self.helper.get_database().get_cursor().fetchmany(1)

        if not result:
            return False

        data = {}
        for row in result:
            data.update(row)
            for key, value in data.items():
                if isinstance(value, str) and (value.startswith("{") or value.startswith("[")):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                elif value == '':
                    value = None
                self.data[key] = value
        return True