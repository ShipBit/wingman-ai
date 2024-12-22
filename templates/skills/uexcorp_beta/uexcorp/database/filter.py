import uuid


class Filter:
    def __init__(self, table: str | None = None):
        self.__base_table: str | None = table
        self.__where = []
        self.__grouped_where = []
        self.__joins = []
        self.__limit = None
        self.__offset = None
        self.__binds = {}
        self.__order_by = {}

    def clear(self):
        self.__init__(self.get_table())

    def apply_filter(self, filter: "Filter", is_or: bool = False):
        self.__joins += filter.get_joins()
        if filter.get_limit() is not None:
            self.__limit = filter.get_limit()
        if filter.get_offset() is not None:
            self.__offset = filter.get_offset()
        self.__binds.update(filter.get_bind())
        if filter.get_where():
            self.__grouped_where.append({
                "where": filter.get_where(),
                "is_or": is_or
            })
        self.__order_by.update(filter.get_order_by())

    def order_by(self, field: str, direction: str = "ASC"):
        self.__order_by[field] = direction

    def get_order_by(self) -> dict[str, str]:
        return self.__order_by

    def resolve_order_by(self) -> str:
        if len(self.__order_by) == 0:
            return ""
        order_by = "ORDER BY "
        for field, direction in self.__order_by.items():
            order_by += f"{field} {direction},"
        return order_by[:-1]

    def add_bind(self, key: str, value):
        self.__binds[key] = value

    def get_bind(self) -> dict[str, any]:
        return self.__binds

    def limit(self, limit: int):
        self.__limit = limit

    def get_limit(self) -> int | None:
        return self.__limit

    def resolve_limit(self) -> str:
        return f"LIMIT {self.__limit}" if self.__limit is not None else "LIMIT -1"

    def offset(self, offset: int):
        self.__offset = offset

    def get_offset(self) -> int | None:
        return self.__offset

    def resolve_offset(self) -> str:
        return f"OFFSET {self.__offset}" if self.__offset is not None else ""

    def where(self, field: str, value, operation: str | None = None, is_or: bool = False, value_is_field: bool = False):
        self.__where.append((field, value, operation, is_or, value_is_field))

    def get_where(self) -> list[tuple[str, any, str | None, bool, bool]]:
        return self.__where

    def resolve_where(self) -> str:
        if len(self.__where) == 0 and len(self.__grouped_where) == 0:
            return ""

        def resolve_where_loop(where: list[tuple[str, any, str | None, bool, bool]]) -> str:
            where_str = ""
            for i, (field, value, operation, is_or, value_is_field) in enumerate(where):
                if "." not in field:
                    field = f"{self.__base_table}.{field}"

                if value_is_field and "." not in value:
                    value = f"{self.__base_table}.{value}"

                if i > 0:
                    where_str += " OR " if is_or else " AND "

                param_name = f"param_{uuid.uuid4().hex}"
                if isinstance(value, bool):
                    self.add_bind(param_name, 1 if value else 0)
                    value = f"{field} {operation if operation is not None else '='} :{param_name}"
                elif isinstance(value, list):
                    placeholders = []
                    for item in value:
                        item_param_name = f"param_{uuid.uuid4().hex}"
                        self.add_bind(item_param_name, item)
                        placeholders.append(f":{item_param_name}")
                    value = f"{field} {operation if operation is not None else 'IN'} ({','.join(placeholders)})"
                elif isinstance(value, int):
                    self.add_bind(param_name, value)
                    if value == 0:
                        value = f"({field} {operation if operation is not None else '='} :{param_name} OR {field} IS NULL)"
                    else:
                        value = f"{field} {operation if operation is not None else '='} :{param_name}"
                else:
                    if value_is_field:
                        value = f"{field} {operation if operation is not None else '='} {value}"
                    else:
                        self.add_bind(param_name, value)
                        value = f"{field} {operation if operation is not None else '='} :{param_name}"

                where_str += value

            return where_str

        combined_where = "WHERE "
        if len(self.__where) > 0:
            combined_where += resolve_where_loop(self.__where)
        if len(self.__grouped_where) > 0:
            if len(self.__where) > 0:
                combined_where += " AND (" if not self.__grouped_where[0]["is_or"] else " OR ("
            else:
                combined_where += "("
            for i, grouped_where in enumerate(self.__grouped_where):
                if i > 0:
                    combined_where += " AND (" if not grouped_where["is_or"] else " OR ("
                combined_where += resolve_where_loop(grouped_where["where"])
                combined_where += ")"
        return combined_where

    def join(self, target_table, target_field, source_table, source_field):
        self.__joins.append((target_table, target_field, source_table, source_field))

    def get_joins(self) -> list[tuple[str, str, str, str]]:
        return self.__joins

    def resolve_joins(self) -> str:
        if len(self.__joins) == 0:
            return ""
        joins = ""
        for target_table, target_field, source_table, source_field in self.__joins:
            joins += f"JOIN {target_table} ON {source_table}.{source_field} = {target_table}.{target_field} "
        return joins

    def get_table(self) -> str | None:
        return self.__base_table

    def set_table(self, table: str):
        self.__base_table = table
