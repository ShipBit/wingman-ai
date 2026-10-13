"""Items the game logs by class name get the name the player sees in the shop."""

import asyncio
import json

import pytest

from services.sc_gamelog import item_names
from tests.star_citizen.gamelog import FIRST, LOGIN, until, write_game_log

BUY = (
    "<2026-09-28T10:01:00.000Z> [Notice] <CEntityComponentShoppingProvider::SendStandardItemBuyRequest> "
    "Sending SShopBuyRequest - playerId[1001] shopId[2002] shopName[SCShop_BurritoBar] kioskId[0] "
    "client_price[17.000000] itemClassGUID[aaaa-1111] itemName[Food_burrito_01_a] quantity[1] "
    "currencyType[UEC] [Team_CoreGameplayFeatures][Shops][UI]\n"
)
DONE = (
    "<2026-09-28T10:01:01.000Z> [Notice] <CEntityComponentShoppingProvider::RmShopFlowResponse> "
    "Received ShopFlowResponse - playerId[1001] shopId[2002] shopName[SCShop_BurritoBar] kioskId[0] "
    "kioskState[BuyRequestProcessing] result[Success] type[Buying] [Team_CoreGameplayFeatures][Shops][UI]\n"
)


@pytest.fixture
def table(tmp_path, monkeypatch):
    path = tmp_path / "item_names.json"
    path.write_text(json.dumps({
        "by_guid": {"aaaa-1111": "Chicken Burrito"},
        "by_class": {
            "food_burrito_01_beef_a": "Beef Burrito",
            "sasu_carryable_case": "Medical Case",
            "cds_armor_core_01": "ADP Core",
        },
    }))
    monkeypatch.setattr(item_names, "TABLE", path)
    item_names._table.cache_clear()
    yield
    item_names._table.cache_clear()


def test_the_guid_comes_first_then_the_class_name(table):
    assert item_names.lookup("AAAA-1111", "anything") == "Chicken Burrito"
    assert item_names.lookup(None, "Food_burrito_01_beef_a") == "Beef Burrito"


def test_a_key_with_a_manufacturer_prefix_and_a_colour_variant(table):
    assert item_names.lookup(None, "Carryable_case") == "Medical Case"
    assert item_names.lookup(None, "cds_armor_core_01_01_12") == "ADP Core"


def test_an_unknown_item_gets_a_tidied_class_name_not_the_code(table):
    assert item_names.lookup(None, "ESPR_BallisticCannon_Barrel_S3") is None
    assert item_names.display_name(None, "ESPR_BallisticCannon_Barrel_S3") == "ESPR Ballistic Cannon Barrel S3"
    assert item_names.display_name(None, "") is None


def test_without_a_table_the_names_are_tidied(tmp_path, monkeypatch):
    monkeypatch.setattr(item_names, "TABLE", tmp_path / "missing.json")
    item_names._table.cache_clear()
    assert item_names.display_name("aaaa-1111", "food_burrito_01_a") == "Food Burrito 01 A"
    item_names._table.cache_clear()


def test_a_confirmed_purchase_carries_the_name(reader, tmp_path, table):
    write_game_log(tmp_path, FIRST, LOGIN, BUY, DONE)

    async def run():
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.recent(10, {"shop_buy"}))
        await asyncio.sleep(0.2)
        events = reader.recent(10, {"shop_buy"})
        await reader.stop()
        return events

    events = asyncio.run(run())
    assert {e.status for e in events} == {"requested", "confirmed"}
    assert all(e.data["item_display_name"] == "Chicken Burrito" for e in events)
    assert all(e.data["item_name"] == "Food_burrito_01_a" for e in events)  # The ledger key stays.
