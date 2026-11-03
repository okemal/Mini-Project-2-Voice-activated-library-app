from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import wav_bytes


def test_all_eight_operations_and_errors(client):
    initial = client.get("/api/items").json
    assert len(initial) == 3
    new = client.post(
        "/api/items",
        json={"type": "book", "title": "Catcher", "author": "Salinger", "page_count": 220},
    )
    assert new.status_code == 201
    identifier = new.json["id"]
    path = f"/api/items/{identifier}"
    assert client.get(path).json == new.json
    updated = client.patch(path, json={"page_count": 221})
    assert updated.status_code == 200 and updated.json["page_count"] == 221
    assert (
        client.put(path, json={"title": "Rye", "author": "Salinger", "page_count": 222}).status_code
        == 200
    )
    assert client.put(path, json={"title": "Incomplete"}).status_code == 400
    assert client.get(path).json["title"] == "Rye"
    checkout = client.post(path + "/checkout")
    assert checkout.status_code == 200 and checkout.json["item"]["is_available"] is False
    assert client.post(path + "/checkout").status_code == 409
    assert client.delete(path).status_code == 409
    assert [item["id"] for item in client.get("/api/items?available=false&type=book").json] == [
        identifier
    ]
    assert client.post(path + "/return").json["is_available"] is True
    assert client.post(path + "/return").status_code == 409
    deleted = client.delete(path)
    assert deleted.status_code == 204 and deleted.data == b""
    assert client.get(path).status_code == 404
    assert client.delete(path).status_code == 404
    next_item = client.post(
        "/api/items", json={"type": "dvd", "title": "Film", "author": "Director", "duration": 125}
    ).json
    assert next_item["id"] > identifier


def test_dvd_care_reminder(client):
    result = client.post("/api/items/2/checkout").json
    assert "Handle with care" in result["message"]


def test_head_is_read_only_even_with_a_creation_body(app, client):
    before = client.get("/api/items").json
    response = app.test_client().head(
        "/api/items",
        json={
            "type": "book",
            "title": "Must not be created",
            "author": "A",
            "page_count": 1,
        },
    )
    assert response.status_code == 200 and response.data == b""
    assert client.get("/api/items").json == before


@pytest.mark.parametrize(
    "fields",
    [
        {"page_count": True},
        {"page_count": 0},
        {"title": ""},
        {"title": "Changed", "page_count": -1},
        {"id": 7},
        {"is_available": False},
        {"type": "dvd"},
        {"item_id": 3},
        {"duration": 10},
    ],
)
def test_invalid_patch_is_atomic(client, fields):
    before = client.get("/api/items/1").json
    response = client.patch("/api/items/1", json=fields)
    assert response.status_code == 400 and set(response.json) == {"error"}
    assert client.get("/api/items/1").json == before


@pytest.mark.parametrize(
    "path", ["/api/items?available=perhaps", "/api/items?type=magazine", "/api/items/not-an-id"]
)
def test_invalid_filters_or_id(client, path):
    response = client.get(path)
    assert response.status_code == 400 and set(response.json) == {"error"}


@pytest.mark.parametrize("body", [None, [], "hello", 3, {"type": "book"}])
def test_invalid_creation_body(client, body):
    response = client.post("/api/items", json=body)
    assert response.status_code == 400
    assert len(client.get("/api/items").json) == 3


def test_parse_is_read_only_and_stale_review_cannot_write(client):
    before = client.get("/api/items").json
    plan = client.post("/api/voice/parse", json={"text": "Delete item 1"}).json["command"]
    assert plan["target"]["title"] == before[0]["title"]
    assert client.get("/api/items").json == before
    assert client.patch("/api/items/1", json={"title": "Changed"}).status_code == 200
    result = client.delete(plan["path"], headers={"If-Match": plan["etag"]})
    assert result.status_code == 412
    assert len(client.get("/api/items").json) == 3
    fresh = client.post("/api/voice/parse", json={"text": "Delete item 1"}).json["command"]
    assert client.delete(fresh["path"], headers={"If-Match": fresh["etag"]}).status_code == 204


def test_only_one_simultaneous_checkout_succeeds(app):
    def checkout(_):
        with app.test_client() as client:
            return client.post(
                "/api/items/1/checkout", headers={"X-Library-Request": "1"}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(checkout, range(2))) == [200, 409]


def test_review_of_a_missing_id_cannot_delete_a_future_record(client):
    plan = client.post("/api/voice/parse", json={"text": "Delete item 4"}).json["command"]
    assert plan["target"] is None
    created = client.post(
        "/api/items",
        json={
            "type": "book",
            "title": "New record",
            "author": "A",
            "page_count": 10,
        },
    )
    assert created.json["id"] == 4
    assert client.delete(plan["path"], headers={"If-Match": plan["etag"]}).status_code == 412
    assert client.get("/api/items/4").json == created.json


def test_speech_gateway(client, speech):
    status = client.get("/api/speech/status")
    assert status.json == {"configured": True, "language": "en-US", "max_recording_seconds": 30}
    recognized = client.post("/api/speech/recognize", data=wav_bytes(), content_type="audio/wav")
    assert recognized.json == {"text": speech.transcript}
    spoken = client.post("/api/speech/synthesize", json={"text": "Completed."})
    assert spoken.status_code == 200 and spoken.mimetype == "audio/wav"
    assert spoken.data.startswith(b"RIFF") and speech.spoken == ["Completed."]
    assert spoken.headers["Cache-Control"] == "no-store"
    assert (
        client.post("/api/speech/recognize", data=b"bad", content_type="text/plain").status_code
        == 415
    )
    assert (
        client.post("/api/speech/recognize", data=b"bad", content_type="audio/wav").status_code
        == 400
    )
    assert (
        client.post(
            "/api/speech/recognize", data=b"0" * 1_000_000, content_type="audio/wav"
        ).status_code
        == 413
    )


def test_local_browser_boundaries(app, client):
    assert app.test_client().post("/api/items/1/checkout").status_code == 403
    assert (
        client.post("/api/items/1/checkout", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/items", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/items", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/.env").status_code == 404
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in response.headers
