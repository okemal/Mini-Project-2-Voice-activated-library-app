"""Exercise the real DOM, API, AudioWorklet, WAV conversion and speech gateway."""

from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

pytestmark = pytest.mark.browser


@pytest.fixture
def live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture
def page(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        context = browser.new_context(
            permissions=["microphone"], viewport={"width": 1440, "height": 1000}
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server)
        expect(page.locator("#voice-record")).to_be_enabled()
        yield page
        assert not errors, errors
        context.close()
        browser.close()


def command(page, text):
    page.locator("#voice-transcript").fill(text)
    page.locator("#voice-submit").click()


def confirm(page):
    expect(page.locator("#voice-review")).to_be_visible()
    page.locator("#voice-confirm").click()
    expect(page.locator("#voice-review")).to_be_hidden()
    expect(page.locator("#voice-submit")).to_be_enabled()


def test_browser_all_operations_and_spoken_errors(page, speech):
    command(page, "Create book title Catcher author Salinger pages 220")
    expect(page.locator("#voice-review")).to_be_visible()
    expect(page.locator("#total-count")).to_have_text("03")
    confirm(page)
    expect(page.locator("#total-count")).to_have_text("04")
    expect(page.locator("#voice-response-text")).to_contain_text("with ID 4")
    command(page, "List available books")
    expect(page.locator("#voice-response-text")).to_contain_text("Found 3 items")
    expect(page.locator("#voice-results li")).to_have_count(3)
    command(page, "Get item four")
    expect(page.locator("#voice-response-text")).to_contain_text("220 pages")
    command(page, "Update item 4 pages 221")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("221 pages")
    command(page, "Replace item 4 title Rye author Salinger pages 222")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("222 pages")
    command(page, "Checkout item 4")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("has been checked out")
    command(page, "Checkout item 4")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("already checked out")
    assert "already checked out" in speech.spoken[-1]
    command(page, "Delete item 4")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("Cannot remove checked-out item")
    command(page, "Return item 4")
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("has been returned")
    command(page, "Delete item 4")
    confirm(page)
    expect(page.locator("#total-count")).to_have_text("03")
    command(page, "Get item 4")
    expect(page.locator("#voice-response-text")).to_contain_text("No item with ID 4")
    expect(page.locator("#voice-audio")).to_be_visible()
    expect(page.locator("#voice-submit")).to_be_enabled()
    assert "No item with ID 4" in speech.spoken[-1]


def test_real_recording_and_spoken_confirmation(page, speech):
    speech.transcript = "Check out item three."
    page.locator("#voice-record").click()
    expect(page.locator("#voice-record")).to_have_text("Stop & transcribe")
    page.wait_for_timeout(350)  # Capture enough PCM to satisfy the minimum audio duration.
    page.locator("#voice-record").click()
    expect(page.locator("#voice-review")).to_be_visible()
    expect(page.locator("#loan-count")).to_have_text("00")
    assert len(speech.recognitions) == 1
    speech.transcript = "Confirm."
    page.locator("#voice-record").click()
    expect(page.locator("#voice-record")).to_have_text("Stop & transcribe")
    page.wait_for_timeout(350)
    page.locator("#voice-record").click()
    expect(page.locator("#voice-response-text")).to_contain_text("has been checked out")
    expect(page.locator("#loan-count")).to_have_text("01")
    assert len(speech.recognitions) == 2
    expect(page.locator("#voice-submit")).to_be_enabled()


def test_edit_and_cancel_invalidate_review(page):
    command(page, "Delete item 3")
    expect(page.locator("#voice-review")).to_be_visible()
    page.locator("#voice-transcript").fill("Delete item 2")
    expect(page.locator("#voice-review")).to_be_hidden()
    command(page, "confirm")
    expect(page.locator("#voice-response-text")).to_contain_text("no command waiting")
    command(page, "Delete item 3")
    expect(page.locator("#voice-review")).to_be_visible()
    page.locator("#voice-cancel").click()
    expect(page.locator("#voice-response-text")).to_contain_text("cancelled")
    expect(page.locator("#total-count")).to_have_text("03")


def test_discard_never_uploads_audio(page, speech):
    page.locator("#voice-record").click()
    expect(page.locator("#voice-discard")).to_be_visible()
    page.wait_for_timeout(200)
    page.locator("#voice-discard").click()
    expect(page.locator("#voice-state")).to_have_text("Recording discarded.")
    assert speech.recognitions == []
    expect(page.locator("#voice-record")).to_have_text("Start speaking")


def test_microphone_denial_keeps_typed_commands_usable(page):
    page.evaluate(
        "() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); }; }"
    )
    page.locator("#voice-record").click()
    expect(page.locator("#voice-response-text")).to_contain_text("permission was denied")
    command(page, "list items")
    expect(page.locator("#voice-response-text")).to_contain_text("Found 3 items")


def test_synthesis_failure_does_not_repeat_a_write(page):
    page.route(
        "**/api/speech/synthesize",
        lambda route: route.fulfill(status=503, json={"error": "Speech unavailable"}),
    )
    command(page, "Create book title Once author A pages 10")
    expect(page.locator("#voice-review")).to_be_visible()
    confirm(page)
    expect(page.locator("#total-count")).to_have_text("04")
    expect(page.locator("#voice-response-text")).to_contain_text("Successfully created")
    expect(page.locator("#voice-audio-status")).to_contain_text("Spoken reply unavailable")
    command(page, "confirm")
    expect(page.locator("#voice-response-text")).to_contain_text("no command waiting")
    expect(page.locator("#total-count")).to_have_text("04")


def test_mobile_layout_has_no_horizontal_overflow(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator(".voice-examples summary").click()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#voice-record")).to_be_visible()
    command(page, "list items")
    expect(page.locator("#voice-response-text")).to_contain_text("Found 3 items")


def test_stale_review_fails_in_browser(page, client):
    command(page, "Delete item 3")
    expect(page.locator("#voice-review")).to_be_visible()
    assert client.patch("/api/items/3", json={"title": "Changed elsewhere"}).status_code == 200
    confirm(page)
    expect(page.locator("#voice-response-text")).to_contain_text("changed after review")
    assert client.get("/api/items/3").json["title"] == "Changed elsewhere"


def test_review_expires(page):
    page.clock.install()
    command(page, "Delete item 3")
    expect(page.locator("#voice-review")).to_be_visible()
    expect(page.locator("#voice-submit")).to_be_enabled()
    page.clock.fast_forward(120001)
    expect(page.locator("#voice-review")).to_be_hidden()
    expect(page.locator("#voice-response-text")).to_contain_text("review expired")
    expect(page.locator("#total-count")).to_have_text("03")
