from datetime import datetime
from skills.uexcorp.uexcorp.model.data_model import DataModel

class ImportData(DataModel):

    required_keys = ["table"]

    def __init__(
            self,
            table: str, # text
            date_imported: int | None = None,  # int(11)
            dataset_count: int | None = None,  # int(11)
            time_taken: int | None = None,  # int(11)
            date_expires: int | None = None,  # int(11), relay bundles: when the relay has newer data
            etag: str | None = None,  # relay bundles: version of the stored data
            load: bool = False,
    ):
        super().__init__("imports")
        self.data = {
            "table": table,
            "date_imported": date_imported,
            "dataset_count": dataset_count,
            "time_taken": time_taken,
            "date_expires": date_expires,
            "etag": etag,
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

    def is_expired(self) -> bool:
        """Relay bundles: True if never fetched or the relay has newer data by now."""
        return not self.data["date_expires"] or self.data["date_expires"] <= self.helper.get_timestamp()

    def get_date_expires(self) -> int | None:
        return self.data["date_expires"]

    def set_date_expires(self, date_expires: int | None):
        self.data["date_expires"] = date_expires

    def get_etag(self) -> str | None:
        return self.data["etag"]

    def set_etag(self, etag: str | None):
        self.data["etag"] = etag

    def __str__(self):
        return str(self.data["table"])
