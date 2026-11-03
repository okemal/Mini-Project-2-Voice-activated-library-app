"""Library REST API and same-origin Azure voice gateway. Run with python app.py."""

import hashlib
import json
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from custom_classes import DVD, Book, ItemNotFoundError, ItemStateError, LibraryCollection
from speech_service import MAX_AUDIO_BYTES, MAX_RECORDING_SECONDS, SpeechError, SpeechService
from voice_commands import parse_command


def seeded_collection() -> LibraryCollection:
    """Keep the Week 4 starting records and their IDs."""
    return LibraryCollection(
        [
            Book("The Left Hand of Darkness", "Ursula K. Le Guin", 304),
            DVD("Spirited Away", "Hayao Miyazaki", 125),
            Book("The Hobbit", "J. R. R. Tolkien", 310),
        ]
    )


def create_app(config: dict | None = None, *, speech_service=None) -> Flask:
    """Create isolated state for each application instance and test."""
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_AUDIO_BYTES,
        TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
    )
    app.config.update(config or {})
    collection = seeded_collection()
    lock = RLock()
    speech = speech_service if speech_service is not None else SpeechService.from_environment()
    app.extensions.update(collection=collection, speech=speech)

    @app.before_request
    def protect_local_api():
        """Reject browser cross-origin calls and simple cross-site form writes."""
        if not request.path.startswith("/api/"):
            return None
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin
            and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.scheme, request.host)
        ):
            return jsonify(error="Cross-origin API requests are not allowed"), 403
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("X-Library-Request") != "1"
        ):
            return jsonify(error="The X-Library-Request: 1 header is required"), 403
        return None

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; worker-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ItemNotFoundError)
    def not_found(error):
        return jsonify(error=str(error)), 404

    @app.errorhandler(ItemStateError)
    def conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(ValueError)
    def bad_value(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(SpeechError)
    def speech_error(error):
        return jsonify(error=str(error)), error.status_code

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify(error="An internal error occurred. Please try again."), 500

    def json_object() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def item_id_value(raw: str) -> int:
        try:
            return int(raw)
        except ValueError:
            raise ValueError("item_id must be an integer") from None

    def item_etag(item: dict) -> str:
        return '"' + hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest() + '"'

    def check_review(item: dict) -> None:
        if request.headers.get("If-Match") and request.headers["If-Match"] != item_etag(item):
            from werkzeug.exceptions import PreconditionFailed

            raise PreconditionFailed("This record changed after review. Review the command again.")

    def item_response(item, status: int = 200):
        data = item.to_dict()
        response = jsonify(data)
        response.headers["ETag"] = item_etag(data)
        return response, status

    def update_fields() -> dict:
        data = json_object()
        invalid = data.keys() - {"title", "author", "page_count", "duration"}
        if invalid:
            raise ValueError(f"Fields cannot be updated: {', '.join(sorted(invalid))}")
        return data

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/api/items", methods=["GET", "POST"])
    def items():
        with lock:
            if request.method in {"GET", "HEAD"}:
                available_arg = request.args.get("available")
                if available_arg is None:
                    available = None
                elif available_arg.lower() in {"true", "1", "false", "0"}:
                    available = available_arg.lower() in {"true", "1"}
                else:
                    raise ValueError("available must be true or false")
                types = {"book": "Book", "dvd": "DVD", "mediaitem": "MediaItem"}
                kind = request.args.get("type")
                if kind is not None and kind.lower() not in types:
                    raise ValueError("type must be book, dvd, or mediaitem")
                return jsonify(
                    [
                        item.to_dict()
                        for item in collection.list_items(
                            available,
                            types[kind.lower()] if kind else None,
                        )
                    ]
                )
            data = json_object()
            kind = data.get("type")
            if not isinstance(kind, str) or kind.lower() not in {"book", "dvd"}:
                raise ValueError("type must be Book or DVD")
            detail = "page_count" if kind.lower() == "book" else "duration"
            if data.keys() != {"type", "title", "author", detail}:
                raise ValueError(
                    f"Creating this item requires exactly type, title, author and {detail}"
                )
            model = Book if kind.lower() == "book" else DVD
            item = model(data["title"], data["author"], data[detail])
            collection.add_item(item)
            return item_response(item, 201)

    @app.route("/api/items/<item_id>", methods=["GET", "PUT", "PATCH", "DELETE"])
    def one_item(item_id: str):
        with lock:
            identifier = item_id_value(item_id)
            current = collection.get_item(identifier)
            if request.method not in {"GET", "HEAD"}:
                check_review(current.to_dict())
            if request.method == "DELETE":
                collection.remove_item(identifier)
                return "", 204
            if request.method == "PUT":
                item = collection.replace_item(identifier, **update_fields())
            elif request.method == "PATCH":
                item = collection.update_item(identifier, **update_fields())
            else:
                item = collection.get_item(identifier)
            return item_response(item)

    @app.post("/api/items/<item_id>/checkout")
    def checkout_item(item_id: str):
        with lock:
            item = collection.get_item(item_id_value(item_id))
            check_review(item.to_dict())
            message = item.checkout()
            return jsonify(item=item.to_dict(), message=message)

    @app.post("/api/items/<item_id>/return")
    def return_item(item_id: str):
        with lock:
            item = collection.get_item(item_id_value(item_id))
            check_review(item.to_dict())
            item.return_item()
            return item_response(item)

    @app.get("/api/speech/status")
    def speech_status():
        return jsonify(
            configured=speech.configured,
            language="en-US",
            max_recording_seconds=MAX_RECORDING_SECONDS,
        )

    @app.post("/api/speech/recognize")
    def recognize():
        if request.mimetype != "audio/wav":
            return jsonify(error="Send a PCM WAV recording with Content-Type audio/wav"), 415
        return jsonify(text=speech.recognize(request.get_data()))

    @app.post("/api/speech/synthesize")
    def synthesize():
        data = json_object()
        if data.keys() != {"text"}:
            raise ValueError("Provide only the text to speak")
        return Response(speech.synthesize(data["text"]), mimetype="audio/wav")

    @app.post("/api/voice/parse")
    def voice_parse():
        data = json_object()
        if data.keys() != {"text"}:
            raise ValueError("Provide only the command text")
        command = parse_command(data["text"]).to_dict()
        # Include the current record in the review without performing a write.
        if command["requires_confirmation"] and command["action"] != "create":
            identifier = int(command["path"].split("/")[3])
            with lock:
                try:
                    item = collection.get_item(identifier).to_dict()
                except ItemNotFoundError:
                    item = None
            command["target"] = item
            # A future ID must not become writable under a review of a missing record.
            command["etag"] = item_etag(item) if item else '"missing"'
        return jsonify(command=command)

    return app


app = create_app()

if __name__ == "__main__":
    # Local teaching application: no debugger, public bind, or reloader.
    app.run(host="127.0.0.1", port=5000, debug=False)
