from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.category import Category


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

    def load(self) -> list[Category]:
        return super().load()

    def add_filter_by_type(self, type: str) -> "CategoryDataAccess":
        self.filter.where("type", type)
        return self

    def add_filter_by_section(self, section: str) -> "CategoryDataAccess":
        self.filter.where("section", section)
        return self

    def add_filter_by_name(self, name: str) -> "CategoryDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_is_game_related(self, is_game_related: bool) -> "CategoryDataAccess":
        self.filter.where("is_game_related", is_game_related)
        return self

    def add_filter_by_is_mining(self, is_mining: bool) -> "CategoryDataAccess":
        self.filter.where("is_mining", is_mining)
        return self
