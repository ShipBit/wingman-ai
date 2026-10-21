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


def _table_json(revision=1, **names):
    return json.dumps({
        "format_version": 1,
        "revision": revision,
        "by_guid": {"aaaa-1111": "Chicken Burrito"},
        "by_class": names or {
            "food_burrito_01_beef_a": "Beef Burrito",
            "sasu_carryable_case": "Medical Case",
            "cds_armor_core_01": "ADP Core",
            "shld_behr_s03_7ca": "7CA 'Nargun'",
        },
    })


@pytest.fixture
def table(tmp_path, monkeypatch):
    path = tmp_path / "item_names.json"
    path.write_text(_table_json())
    monkeypatch.setattr(item_names, "TABLE", path)
    monkeypatch.setattr(item_names, "_current", None)
    yield path


def test_the_guid_comes_first_then_the_class_name(table):
    assert item_names.lookup("AAAA-1111", "anything") == "Chicken Burrito"
    assert item_names.lookup(None, "Food_burrito_01_beef_a") == "Beef Burrito"


def test_a_key_with_a_manufacturer_prefix_and_a_colour_variant(table):
    assert item_names.lookup(None, "Carryable_case") == "Medical Case"
    assert item_names.lookup(None, "cds_armor_core_01_01_12") == "ADP Core"
    assert item_names.lookup(None, "SHLD_BEHR_S03_7CA_SCItem") == "7CA 'Nargun'"


def test_an_unknown_item_gets_a_tidied_class_name_not_the_code(table):
    assert item_names.lookup(None, "ESPR_BallisticCannon_Barrel_S3") is None
    assert item_names.display_name(None, "ESPR_BallisticCannon_Barrel_S3") == "ESPR Ballistic Cannon Barrel S3"
    assert item_names.display_name(None, "") is None


# ── staying current: the table is downloaded like the rules ──────────────


def _source(tmp_path, answer):
    source = item_names.ItemNamesSource(str(tmp_path / "cache"))

    async def fetch():
        if isinstance(answer, Exception):
            raise answer
        return answer

    source._fetch = fetch
    return source


def test_a_newer_table_from_github_replaces_the_running_one(table, tmp_path):
    source = _source(tmp_path, (200, _table_json(2, shld_behr_s03_8ca="8CA 'Prowler'").encode(), '"e1"'))
    assert item_names.lookup(None, "SHLD_BEHR_S03_8CA_SCItem") is None
    assert asyncio.run(source.check()) is True
    assert item_names.lookup(None, "SHLD_BEHR_S03_8CA_SCItem") == "8CA 'Prowler'"
    # It is cached: the next start uses it rather than the older bundled table.
    item_names.ItemNamesSource(str(tmp_path / "cache"))
    assert item_names._active().revision == 2


def test_an_older_broken_or_missing_table_changes_nothing(table, tmp_path):
    for answer in (
        (200, _table_json(1, x="Old").encode(), None),  # Not newer than the bundled one.
        (200, b'{"format_version": 2}', None),
        (200, b"<html>not json", None),
        (404, b"", None),
        OSError("offline"),
    ):
        assert asyncio.run(_source(tmp_path, answer).check()) is False
        assert item_names.lookup(None, "SHLD_BEHR_S03_7CA_SCItem") == "7CA 'Nargun'"


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
