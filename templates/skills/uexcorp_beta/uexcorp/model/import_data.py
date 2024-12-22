from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class ImportData(DataModel):

    required_keys = ["table"]

    def __init__(
            self,
            table: str, # text
            date_imported: int | None = None,  # int(11)
            dataset_count: int | None = None,  # int(11)
            time_taken: int | None = None,  # int(11)
            load: bool = False,
    ):
        super().__init__("imports")
        self.data = {
            "table": table,
            "date_imported": date_imported,
            "dataset_count": dataset_count,
            "time_taken": time_taken,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["table"]:
                raise Exception("table is required to load data")
            self.load_by_value("table", self.data["table"])

    def needs_import(self, persistence: int) -> bool:
        if not self.data["table"]:
            return False

        if not self.data["date_imported"]:
            return True

        return (self.data["date_imported"] + persistence) < self.helper.get_timestamp()

    def persist(self, skip_commit: bool = False) -> bool:
        if super().persist(skip_commit):
            if not self.data["last_import_run_id"]:
                return True

            self.helper.get_database().get_cursor().execute(
                f"DELETE FROM {self.get_table()} WHERE last_import_run_id != {str(int(self.data["last_import_run_id"] or 0))}"
            )
            if not skip_commit:
                self.helper.get_database().get_connection().commit()
            return True
        return False

    def get_table(self) -> str:
        return self.data["table"]

    def get_date_imported(self) -> int | None:
        return self.data["date_imported"]

    def get_date_imported_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_imported"])

    def set_date_imported(self, date_imported: int):
        self.data["date_imported"] = date_imported

    def get_dataset_count(self) -> int | None:
        return self.data["dataset_count"]

    def set_dataset_count(self, dataset_count: int):
        self.data["dataset_count"] = dataset_count

    def get_time_taken(self) -> int | None:
        return self.data["time_taken"]

    def set_time_taken(self, time_taken: int):
        self.data["time_taken"] = time_taken

    def __str__(self):
        return str(self.data["table"])
