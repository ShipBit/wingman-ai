try:
    from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp.uexcorp.model.category import Category
    from skills.uexcorp.uexcorp.database.filter import Filter
except ModuleNotFoundError:
    from uexcorp.uexcorp.data_access.data_access import DataAccess
    from uexcorp.uexcorp.model.category import Category


class CategoryDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="category",
            model=Category
        )
        self.fields = [
            "id",
            "type",
            "section",
            "name",
            "is_game_related",
            "is_mining",
            "date_added",
            "date_modified"
        ]

    def load(self, **params) -> list[Category]:
        return super().load(**params)

    def add_filter_by_combined_name(self, combined_name: str | list[str]) -> "CategoryDataAccess":
        # CONCAT might be supported in a future version of sqlite
        # self.filter.where("CONCAT(section, ' ', name)", combined_name)

        # For now, we will use a custom column thats filled on import
        self.filter.where("combined_name", combined_name)

    def add_filter_by_type(self, type: str | list[str]) -> "CategoryDataAccess":
        self.filter.where("type", type)
        return self

    def add_filter_by_section(self, section: str | list[str]) -> "CategoryDataAccess":
        self.filter.where("section", section)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "CategoryDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_is_game_related(self, is_game_related: bool) -> "CategoryDataAccess":
        self.filter.where("is_game_related", is_game_related)
        return self

    def add_filter_by_is_mining(self, is_mining: bool) -> "CategoryDataAccess":
        self.filter.where("is_mining", is_mining)
        return self
