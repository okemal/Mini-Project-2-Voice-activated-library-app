"""Opt-in live speech checks against an isolated, disposable library.

Run from the repository root: python -m scripts.check_azure [--all]
This uses the local Azure configuration and consumes a small amount of quota.
It never prints credentials, records the microphone, or saves audio to disk.
"""

import argparse

from app import create_app
from voice_commands import parse_command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Check all eight library operations")
    args = parser.parse_args()
    client = create_app().test_client()
    client.environ_base["HTTP_X_LIBRARY_REQUEST"] = "1"
    if not client.get("/api/speech/status").json["configured"]:
        print("Azure Speech is not configured. Set the key and region in .env.")
        return 1
    cases = ["List available books"]
    if args.all:
        cases = [
            "Create item, type book, title Ocean Stories, author Alice Green, pages 220",
            "List available books",
            "Get item four",
            "Replace item four, title is Dune, author is Frank Herbert, pages 230",
            "Update item four, pages 240",
            "Check out item four",
            "Return item four",
            "Delete item four",
        ]
    print("Using an isolated sample collection. All changes are discarded on exit.", flush=True)
    for text in cases:
        expected = parse_command(text)
        audio = client.post("/api/speech/synthesize", json={"text": text})
        if audio.status_code != 200:
            print(f"FAIL {expected.action}: {audio.json['error']}", flush=True)
            return 1
        recognized = client.post("/api/speech/recognize", data=audio.data, content_type="audio/wav")
        if recognized.status_code != 200:
            print(f"FAIL {expected.action}: {recognized.json['error']}", flush=True)
            return 1
        planned = client.post("/api/voice/parse", json={"text": recognized.json["text"]})
        if planned.status_code != 200:
            print(f"FAIL {expected.action}: recognized audio could not be parsed.", flush=True)
            return 1
        plan = planned.json["command"]
        if (plan["method"], plan["path"], plan["body"]) != (
            expected.method,
            expected.path,
            expected.body,
        ):
            print(
                f"FAIL {expected.action}: recognized command differs from the intended request.",
                flush=True,
            )
            return 1
        # Intentionally confirm only the known synthetic test requests.
        response = client.open(
            plan["path"],
            method=plan["method"],
            json=plan["body"],
            headers={"If-Match": plan["etag"]} if plan.get("etag") else {},
        )
        expected_status = (
            201 if plan["action"] == "create" else 204 if plan["action"] == "delete" else 200
        )
        if response.status_code != expected_status:
            print(
                f"FAIL {expected.action}: unexpected library HTTP {response.status_code}.",
                flush=True,
            )
            return 1
        feedback = client.post(
            "/api/speech/synthesize",
            json={"text": f"Successfully completed the {expected.action} command."},
        )
        if feedback.status_code != 200:
            print(f"FAIL {expected.action}: library succeeded, spoken feedback failed.", flush=True)
            return 1
        print(
            f"PASS {expected.action}: Azure audio -> transcript -> {plan['method']} {plan['path']} -> spoken feedback",
            flush=True,
        )
    print(f"Live Azure check passed: {len(cases)} operation(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
