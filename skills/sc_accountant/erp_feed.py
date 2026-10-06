"""Books what Core's Star Citizen log reader recorded, one page at a time."""

from skills.sc_accountant.erp_reader_client import ReaderFeed


def capture_once(engine, database):
    feed = ReaderFeed(database)
    first = feed.read_page(after=0, limit=1)
    state = engine.view("feed")["data"]
    if not state.get("core_reader"):
        # New books start at the beginning. Books from the SC Log Reader skill
        # move over once and continue after what Core already holds.
        cursor = first["health"]["snapshot_high_water"] if state.get("source_id") else 0
        engine.bind_core_reader(first["source_id"], cursor)
        state = engine.view("feed")["data"]
    elif state["source_id"] != first["source_id"]:
        raise ValueError(
            "The Star Citizen log database was replaced. Keep the history and "
            "reconcile before capturing again."
        )
    page = feed.read_page(after=int(state.get("cursor") or 0), limit=200)
    engine.ingest_page(page)
    return page
