"""The relay client: a failed request must raise instead of returning empty data, or a table would
be recorded as imported with 0 rows and not fetched again for up to 14 days. Unchanged bundles
are not downloaded again and an unload stops a running download."""

import pytest

from skills.uexcorp.uexcorp.api.uex import RelayResponse, Uex, UexApiError, UexClientError
from tests.skills.uexcorp.support import RELAY_URL, Response, Session


def use_responses(client, responses_by_url) -> Session:
    client.session = Session(responses_by_url)
    return client.session


def test_a_bundle_comes_with_its_etag_and_max_age(relay_client):
    use_responses(relay_client, {f"{RELAY_URL}/short": [Response(
        payload={"commodities_prices_all": [{"id": 1}]},
        headers={"ETag": '"abc"', "Cache-Control": "public, max-age=5559"},
    )]})

    response = relay_client.fetch_bundle(Uex.BUNDLE_SHORT)

    assert response == RelayResponse({"commodities_prices_all": [{"id": 1}]}, '"abc"', 5559)


def test_a_stored_etag_is_sent_and_a_304_means_unchanged(relay_client):
    session = use_responses(relay_client, {f"{RELAY_URL}/long": [Response(304, headers={"Cache-Control": "max-age=60"})]})

    response = relay_client.fetch_bundle(Uex.BUNDLE_LONG, etag='"abc"')

    assert response == RelayResponse(None, '"abc"', 60)
    assert session.calls[0][1]["headers"]["If-None-Match"] == '"abc"'


def test_a_server_error_is_retried_then_raises(relay_client):
    relay_client.MAX_RETRIES = 1
    session = use_responses(relay_client, {f"{RELAY_URL}/long": [Response(500)]})

    with pytest.raises(UexApiError):
        relay_client.fetch_bundle(Uex.BUNDLE_LONG)

    assert len(session.calls) == 2


def test_a_server_error_followed_by_an_answer_succeeds(relay_client):
    use_responses(relay_client, {f"{RELAY_URL}/long": [Response(503), Response(payload={"terminals": []})]})

    assert relay_client.fetch_bundle(Uex.BUNDLE_LONG).data == {"terminals": []}


def test_a_request_the_relay_rejects_is_not_retried(relay_client):
    session = use_responses(relay_client, {f"{RELAY_URL}/long": [Response(404)]})

    with pytest.raises(UexClientError):
        relay_client.fetch_bundle(Uex.BUNDLE_LONG)

    assert len(session.calls) == 1  # asking again gives the same answer


def test_a_rate_limit_pauses_for_the_time_the_relay_names_and_retries(relay_client):
    session = use_responses(relay_client, {f"{RELAY_URL}/short": [Response(429, headers={"Retry-After": "7"}), Response(payload={})]})

    assert relay_client.fetch_bundle(Uex.BUNDLE_SHORT).data == {}

    assert relay_client._Uex__stop.waited == [7]
    assert len(session.calls) == 2


@pytest.mark.parametrize("body", [b'{"terminals": [', b"[1, 2]"], ids=["invalid json", "not an object"])
def test_a_broken_bundle_raises(relay_client, body):
    relay_client.MAX_RETRIES = 0
    use_responses(relay_client, {f"{RELAY_URL}/long": [Response(body=body)]})

    with pytest.raises(UexApiError):
        relay_client.fetch_bundle(Uex.BUNDLE_LONG)


def test_a_version_answer_without_the_live_version_raises(relay_client):
    use_responses(relay_client, {f"{RELAY_URL}/version": [Response(payload={"status": "error"})]})

    with pytest.raises(UexApiError):
        relay_client.fetch_version()


def test_every_response_is_closed_whatever_the_outcome(relay_client):
    relay_client.MAX_RETRIES = 0
    responses = {
        "ok": Response(payload={}),
        "unchanged": Response(304),
        "error": Response(500),
        "rejected": Response(404),
        "bad_json": Response(body=b"nope"),
    }
    use_responses(relay_client, {f"{RELAY_URL}/{name}": [response] for name, response in responses.items()})

    for name in responses:
        try:
            relay_client.fetch_bundle(name)
        except UexApiError:
            pass

    assert {name: r.closed for name, r in responses.items()} == dict.fromkeys(responses, True)


def test_an_unload_stops_a_running_download(relay_client):
    response = Response(payload={"items": list(range(1000))}, chunks=10)
    response.on_chunk = relay_client.cancel  # unload while the bundle is downloading
    use_responses(relay_client, {f"{RELAY_URL}/long": [response]})

    with pytest.raises(UexApiError):
        relay_client.fetch_bundle(Uex.BUNDLE_LONG)

    assert response.closed


def test_an_unload_stops_a_retry_wait(relay_client):
    session = use_responses(relay_client, {f"{RELAY_URL}/long": [Response(429, headers={"Retry-After": "30"})]})
    relay_client._Uex__stop.on_wait = relay_client.cancel  # unload while waiting

    with pytest.raises(UexApiError):
        relay_client.fetch_bundle(Uex.BUNDLE_LONG)

    assert len(session.calls) == 1
