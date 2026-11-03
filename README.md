# Voice-activated library app

An Azure-powered voice desk for the Week 4 Flask library app. Speak to create,
list, retrieve, replace, update, delete, check out, and return books and DVDs.
The librarian reads the actual success or error response aloud. The original
collection dashboard and JSON API remain available.

## Run locally

Use Python 3.12 or newer. From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open <http://127.0.0.1:5000> in a current browser supporting AudioWorklet (Chrome,
Edge or Firefox). Allow microphone access when prompted. The application binds
to loopback and runs with debug mode off.

Configuration is loaded from `.env` in the repository root. Copy `.env.example`
to `.env` and fill it in locally. Set `AZURE_SPEECH_REGION` and
either `AZURE_SPEECH_KEY` or the supplied `AZURE_API_KEY_1` key name. Exported
environment variables take precedence over the corresponding `.env` values.
Restart after configuration changes. **Never commit `.env` or put keys in JavaScript.**

Each server process starts with three sample records (IDs 1–3). **The collection
is in memory: changes reset on restart.** Run one process for this teaching app.
`python main.py` runs the original domain-model demonstration.

## Use the voice desk

1. Click **Start speaking**, say one command, then click **Stop & transcribe**.
   Recording stops automatically at 30 seconds. **Discard recording** releases
   the microphone without uploading the clip.
2. Azure transcribes the clip. Edit the transcript if recognition is wrong.
   You can also type a command and click **Review command**.
3. Reads run immediately. Every voice write shows a review with the current
   record. Say **confirm** in a new recording or click **Confirm change**.
   Say **cancel** or click **Cancel** to discard it. For typed commands, use the
   confirmation button: editing the transcript invalidates the previous review.
4. The actual library endpoint runs once. Its result is displayed and spoken
   using Azure synthesis. Pause/replay with the player or disable **Spoken replies**.
   If autoplay is blocked, press play.

Reviews expire after two minutes. If an item changes after review, its write is
rejected with HTTP 412 and must be reviewed again. A speech failure after a
successful write leaves the written success visible and never retries the write.

## Example commands

- Create a book: `Create item, type book, title The Catcher in the Rye, author J. D. Salinger, pages 220`
- Create a DVD: `Create DVD, title Inception, director Christopher Nolan, duration 148`
- List: `List items`, `Show all books`, `List available DVDs`, `List checked out books`
- Retrieve: `Get item three`
- Replace every editable field (PUT): `Replace item 3, title The Hobbit, author J. R. R. Tolkien, pages 320`
- Update selected fields (PATCH): `Update item 3, pages 310`
- Delete: `Delete item 3`
- Check out: `Check out item 3` (also `checkout` or `borrow`)
- Return: `Return item 3`

IDs and measurements accept digits or English numbers such as `three` or
`two hundred twenty`. Target records by ID; titles are not guessed or fuzzily
matched. Include field names (`type`, `title`, `author`/`director`,
`pages`/`page count`, `duration`/`minutes`). Titles or author names containing
field words should be double-quoted in the editable transcript, for example
`Create book, title "The Author Returns", author "Alice Green", pages 120`.
Commas are optional; field names can be followed by `is` (for example `title is Dune`).
Quote a title beginning with the word `is` so it is kept as part of the title.
Unsupported or incomplete commands fail without a write.
This is a constrained English command interface, not a general conversation agent.

## API

All responses are JSON except successful DELETE (empty 204) and synthesis
(PCM WAV). Errors have the shape `{"error":"message"}`.

- `POST /api/items`: create; 201, or 400 for invalid fields.
- `GET /api/items`: list; accepts `?type=book|dvd|mediaitem` and
  `?available=true|false` (also `1|0`); invalid filters return 400.
- `GET /api/items/<id>`: retrieve; 200 or 404.
- `PUT /api/items/<id>`: replace all editable fields; 200, 400, or 404.
- `PATCH /api/items/<id>`: partial update; 200, 400, or 404.
- `DELETE /api/items/<id>`: delete an available item; 204, 404, or 409.
- `POST /api/items/<id>/checkout`: check out; 200, 404, or 409.
- `POST /api/items/<id>/return`: return; 200, 404, or 409.

Creation requires exactly `type`, `title`, `author`, and `page_count` (book) or
`duration` (DVD). PUT requires all editable fields, omitting `type`. PATCH accepts
any subset. Measurements must be positive integers, excluding booleans. IDs,
types, and availability cannot be edited; use checkout/return for state changes.
Failed updates are atomic. Deleted IDs are never reused.

All mutating API requests require `X-Library-Request: 1`. This custom header,
same-origin checks, absent CORS permissions, and trusted loopback hosts prevent
unrelated browser pages from invoking local writes or the paid speech gateway.
For example, without any Azure credentials in the request:

```sh
curl -X POST http://127.0.0.1:5000/api/items \
  -H 'X-Library-Request: 1' -H 'Content-Type: application/json' \
  -d '{"type":"book","title":"Dune","author":"Frank Herbert","page_count":412}'
```

Voice endpoints:

- `GET /api/speech/status`: readiness boolean, fixed language and recording limit;
  no key, region, token, or endpoint. Readiness does not test Azure authentication.
- `POST /api/speech/recognize`: `Content-Type: audio/wav`, raw mono 16 kHz,
  16-bit PCM WAV, 0.1–30 seconds; returns `{"text":"..."}`.
- `POST /api/voice/parse`: `{"text":"..."}`; returns a reviewable `command`
  with action, method, path, body, summary and confirmation flag. **Never executes
  the command.** Existing-item writes include a snapshot and ETag.
- `POST /api/speech/synthesize`: `{"text":"..."}` (up to 2,000 characters);
  returns Azure WAV audio. XML is escaped before building SSML.

Item GET responses include an `ETag`; existing-item writes optionally accept
`If-Match` to reject stale changes. Voice writes use it automatically. Audio and
API responses use `Cache-Control: no-store`. There are no automatic write retries.

## Code map

- `custom_classes.py`: existing hierarchy, validation and collection rules.
- `app.py`: application factory, process-local state/lock, REST handlers,
  review preconditions, local browser protections and speech gateway.
- `voice_commands.py`: deterministic grammar, number parsing and request plans.
- `speech_service.py`: private configuration, audio validation, HTTPS Azure calls,
  SSML escaping, timeouts, response limits and sanitized provider errors.
- `static/recorder-worklet.js`: bounded PCM capture in the browser audio thread.
- `static/recorder.js`: microphone cleanup, resampling and WAV encoding.
- `static/voice.js`: transcript, confirmation, endpoint calls and spoken feedback.
- `static/script.js`, `templates/index.html`, `static/style.css`: responsive
  dashboard and voice interface. Text is rendered with DOM text nodes.
- `tests/`: API/parser/speech tests and Chromium integration tests.
- `scripts/check_azure.py`: opt-in live Azure checks with disposable data.

## Verify

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m py_compile app.py custom_classes.py main.py voice_commands.py speech_service.py
.venv/bin/python main.py
```

Default tests use local speech doubles and fake browser microphone input, never
the Azure account. To run only backend tests, use `python -m pytest -q -m 'not browser'`.

These opt-in checks use the configured Azure account and consume quota. They
synthesize test commands, recognize them, verify the exact parsed requests,
exercise a fresh library instance, and synthesize feedback. Audio stays in memory.

```sh
.venv/bin/python -m scripts.check_azure        # one list round trip
.venv/bin/python -m scripts.check_azure --all  # all eight operations
```

## Privacy and scope

The subscription key stays in Python and is sent only in an HTTPS header to the
fixed regional Azure hosts. No reusable Azure token goes to the browser. Provider
error bodies and request exception details are not returned or logged. WAV uploads
are validated and bounded; at most two upstream speech calls run concurrently.
The app does not save recordings or transcripts. Azure handles submitted speech
under the resource's own service policies.

This is a single-user local course app without accounts or persistent storage.
It needs authentication, deployment-specific browser protection configuration,
durable storage and a production WSGI server before public hosting.

The gateway uses the documented Azure
[short-audio recognition protocol](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-speech-to-text-short)
and [text-to-speech REST protocol](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech).
It keeps credentials private and avoids native SDK dependencies while browser
AudioWorklet supplies PCM in the required format.
