"""Read one durable page from the reader, without host or monitor imports."""

if __package__:
    from .erp_reader_client import ReaderFeed
else:
    from erp_reader_client import ReaderFeed


def capture_once(engine, database):
    feed = ReaderFeed(database)
    first = feed.read_page(after=0, limit=1)
    state = engine.view("feed")["data"]
    if state.get("source_id") and state["source_id"] != first["source_id"]:
        raise ValueError(
            "Reader database changed. Select the original source before resuming."
        )
    page = feed.read_page(after=int(state.get("cursor") or 0), limit=200)
    engine.ingest_page(page)
    return page
