from skills.uexcorp_beta.uexcorp.database.filter import Filter
from skills.uexcorp_beta.uexcorp.helper import Helper
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel


class DataAccess :
    def __init__(
        self,
        table: str,
        model = DataModel,
    ):
        self.helper = Helper.get_instance()
        self.model = model
        self.fields = []
        self.table = table
        if self.table is None:
            raise Exception("Table not set!")
        self.filter = Filter(self.table)
        self.database = self.helper.get_database()
        self.additional_cols = []

    def get_filter(self) -> Filter:
        return self.filter

    def limit(self, limit: int) -> "DataAccess":
        self.filter.limit(limit)
        return self

    def offset(self, offset: int) -> "DataAccess":
        self.filter.offset(offset)
        return self

    def order_by(self, field: str, direction: str = "ASC") -> "DataAccess":
        self.filter.order_by(field, direction)
        return self

    def add_col(self, col: str, alias: str = None) -> "DataAccess":
        self.additional_cols.append((col, alias))
        return self

    def __select(self) -> None:
        def resolve_additional_cols() -> str:
            cols = ""
            for col, alias in self.additional_cols:
                cols += f"{col} AS {alias}, " if alias else f"{col}, "
            return cols

        sql = f"""
            SELECT {resolve_additional_cols()} {self.table}.*
            FROM {self.table}
            {self.filter.resolve_joins()}
            {self.filter.resolve_where()}
            {self.filter.resolve_order_by()}
            {self.filter.resolve_limit()} {self.filter.resolve_offset()}
        """

        # for debugging print sql with resolved binds
        # resolved_sql = sql
        # for key, value in self.filter.get_bind().items():
        #     if isinstance(value, str):
        #         resolved_sql = resolved_sql.replace(f":{key}", f"'{value}'")
        #     else:
        #         resolved_sql = resolved_sql.replace(f":{key}", repr(value))
        # if self.table == "terminal" or self.table == "commodity_route":
        #     print(resolved_sql)

        self.database.get_cursor().execute(sql, self.filter.get_bind())
    def _fetch_one(self ) -> list[dict[str, any]]:
        self.__select()
        return self.database.get_cursor().fetchmany(1)

    def _fetch_all(self) -> list[dict[str, any]]:
        self.__select()
        return self.database.get_cursor().fetchall()

    def load_one(self) -> DataModel | None:
        data = self._fetch_one()
        for row in data:
            item_data = {"table": self.table}
            item_data.update(row)
            init_data = {}
            if self.model.required_keys:
                for key in self.model.required_keys:
                    if key in item_data:
                        init_data[key] = item_data[key]
            item = self.model(**init_data)
            item.set_data(item_data)
            return item
        return None

    def load(self) -> list[DataModel]:
        data = self._fetch_all()
        items = []
        for row in data:
            item_data = {"table": self.table}
            item_data.update(row)
            init_data = {}
            if self.model.required_keys:
                for key in self.model.required_keys:
                    if key in item_data:
                        init_data[key] = item_data[key]
            item = self.model(**init_data)
            item.set_data(item_data)
            items.append(item)
        return items

    def persist(self) -> None:
        if not self.fields:
            self.helper.get_handler_error().write("DataAccess.persist", self.fields, "No fields to persist!")
            raise Exception("No fields to persist!")

    def load_by_property(self, property: str, value: any) -> DataModel | None:
        data_access = DataAccess(self.table, self.model)
        data_access.filter.where(property, value)
        return data_access.load_one()

