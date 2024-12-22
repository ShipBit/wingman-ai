try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.company import Company
except ImportError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.company import Company


class CompanyDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="company",
            model=Company
        )
        self.fields = [
            "id",
            "id_faction",
            "name",
            "nickname",
            "wiki",
            "industry",
            "is_item_manufacturer",
            "is_vehicle_manufacturer",
            "date_added",
            "date_modified"
        ]

    def load(self, **params) -> list[Company]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Company | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_faction(self, id_faction: int | list[int], **kwargs) -> "CompanyDataAccess":
        self.filter.where("id_faction", id_faction, **kwargs)
        return self

    def add_filter_by_name(self, name: str | list[str], **kwargs) -> "CompanyDataAccess":
        self.filter.where("name", name, **kwargs)
        return self

    def add_filter_by_nickname(self, nickname: str | list[str], **kwargs) -> "CompanyDataAccess":
        self.filter.where("nickname", nickname, **kwargs)
        return self

    def add_filter_by_wiki(self, wiki: str | list[str], **kwargs) -> "CompanyDataAccess":
        self.filter.where("wiki", wiki, **kwargs)
        return self

    def add_filter_by_industry(self, industry: str | list[str], **kwargs) -> "CompanyDataAccess":
        self.filter.where("industry", industry, **kwargs)
        return self

    def add_filter_by_is_item_manufacturer(self, is_item_manufacturer: bool, **kwargs) -> "CompanyDataAccess":
        self.filter.where("is_item_manufacturer", is_item_manufacturer, **kwargs)
        return self

    def add_filter_by_is_vehicle_manufacturer(self, is_vehicle_manufacturer: bool, **kwargs) -> "CompanyDataAccess":
        self.filter.where("is_vehicle_manufacturer", is_vehicle_manufacturer, **kwargs)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **kwargs) -> "CompanyDataAccess":
        self.filter.where("date_added", date_added, **kwargs)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **kwargs) -> "CompanyDataAccess":
        self.filter.where("date_modified", date_modified, **kwargs)
        return self
