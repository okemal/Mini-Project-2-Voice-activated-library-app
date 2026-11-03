"""Translate a small, explicit English grammar into existing library requests.

Parsing never executes a request. Unknown, incomplete, or ambiguous commands
raise ValueError, so a recognition mistake cannot fall through to a write.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from custom_classes import DVD, Book

MAX_TRANSCRIPT_LENGTH = 1200
MAX_FIELD_LENGTH = 300
_SMALL = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
    )
)
_TENS = dict(
    zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10))
)
_FIELDS = re.compile(
    r"\b(page[ _]count|duration(?: in minutes)?|director|minutes|author|pages|title|type)"
    r"(?=\s|[:=])(?:\s*[:=]\s*|\s+(?:is\s+)?)",
    re.IGNORECASE,
)
_ALIASES = {
    "pages": "page_count",
    "page count": "page_count",
    "page_count": "page_count",
    "minutes": "duration",
    "duration in minutes": "duration",
    "director": "author",
}


@dataclass(frozen=True)
class VoiceCommand:
    """A reviewable request plan, or a confirm/cancel control command."""

    action: str
    summary: str
    method: str | None = None
    path: str | None = None
    body: dict | None = None
    requires_confirmation: bool = False

    def to_dict(self) -> dict:
        """Return the public request plan without hidden execution state."""
        return asdict(self)


def positive_number(value: str) -> int:
    """Read a positive integer in digits or English words up to 999,999."""
    text = value.strip().rstrip(".,;").lower()
    if re.fullmatch(r"\d+|\d{1,3}(?:,\d{3})+", text):
        number = int(text.replace(",", ""))
    else:
        words = text.replace("-", " ").split()

        def group(tokens: list[str]) -> int:
            result = 0
            if (
                len(tokens) >= 2
                and tokens[0] in _SMALL
                and 1 <= _SMALL[tokens[0]] <= 9
                and tokens[1] == "hundred"
            ):
                result = _SMALL[tokens[0]] * 100
                tokens = tokens[2:]
                if tokens and tokens[0] == "and":
                    tokens = tokens[1:]
                    if not tokens:
                        raise ValueError("Incomplete number")
                if not tokens:
                    return result
            if len(tokens) == 1 and tokens[0] in _SMALL:
                return result + _SMALL[tokens[0]]
            if tokens and tokens[0] in _TENS:
                if len(tokens) == 1:
                    return result + _TENS[tokens[0]]
                if len(tokens) == 2 and tokens[1] in _SMALL and 1 <= _SMALL[tokens[1]] <= 9:
                    return result + _TENS[tokens[0]] + _SMALL[tokens[1]]
            raise ValueError("Use a positive whole number, such as 3 or two hundred twenty")

        if words.count("thousand") == 1:
            index = words.index("thousand")
            leading = group(words[:index])
            trailing = words[index + 1 :]
            if trailing and trailing[0] == "and":
                trailing = trailing[1:]
                if not trailing:
                    raise ValueError("Incomplete number")
            number = leading * 1000 + (group(trailing) if trailing else 0)
            if leading == 0:
                raise ValueError("Use a positive whole number")
        else:
            number = group(words)
    if not 1 <= number <= 2_147_483_647:
        raise ValueError("Use a positive whole number no larger than 2147483647")
    return number


def _field_matches(text: str) -> list[re.Match]:
    """Ignore field-label words inside double-quoted values."""
    if text.count('"') % 2:
        raise ValueError("Close each double quote before reviewing the command")
    return [match for match in _FIELDS.finditer(text) if text[: match.start()].count('"') % 2 == 0]


def _read_fields(text: str) -> dict:
    matches = _field_matches(text)
    if not matches or text[: matches[0].start()].strip(" ,;.").lower() not in {"", "with", "set"}:
        raise ValueError("Name each field: type, title, author, pages or duration")
    fields = {}
    for index, match in enumerate(matches):
        label = match[1].lower()
        name = _ALIASES.get(label, label)
        if name in fields:
            raise ValueError(f"Specify {name} only once; quote titles containing field names")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end() : end].strip(" ,;.")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].strip()
        elif '"' in value:
            raise ValueError("Put double quotes around the entire field value")
        if not value or len(value) > MAX_FIELD_LENGTH:
            raise ValueError(f"{name} must contain 1 to {MAX_FIELD_LENGTH} characters")
        fields[name] = positive_number(value) if name in {"page_count", "duration"} else value
    if "type" in fields:
        fields["type"] = fields["type"].lower()
        if fields["type"] not in {"book", "dvd"}:
            raise ValueError("type must be book or DVD")
    if "page_count" in fields and "duration" in fields:
        raise ValueError("Use pages for a book or duration for a DVD, not both")
    return fields


def _write(action: str, method: str, path: str, body: dict | None, summary: str) -> VoiceCommand:
    return VoiceCommand(action, summary, method, path, body, requires_confirmation=True)


def _list_command(text: str) -> VoiceCommand | None:
    state = r"available|checked out|on loan|unavailable"
    match = re.fullmatch(
        rf"(?:list|show|find|display|get)\s+(?:me\s+)?(?:all\s+|only\s+)?"
        rf"(?:(?P<before>{state})\s+)?(?P<kind>items|books|dvds|collection)"
        rf"(?:\s+(?:that are\s+)?(?P<after>{state}))?(?:\s+only)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    before, after = match["before"], match["after"]
    states = [value.lower() == "available" for value in (before, after) if value]
    if len(set(states)) > 1:
        raise ValueError("Choose either available or checked out items")
    filters = {}
    kind = match["kind"].lower()
    if kind in {"books", "dvds"}:
        filters["type"] = kind[:-1]
    if states:
        filters["available"] = str(states[0]).lower()
    path = "/api/items" + (f"?{urlencode(filters)}" if filters else "")
    return VoiceCommand("list", "List matching library items.", "GET", path)


def parse_command(transcript: str) -> VoiceCommand:
    """Parse exactly one supported command without changing the collection."""
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("Say or type a command first")
    if len(transcript) > MAX_TRANSCRIPT_LENGTH:
        raise ValueError(f"Keep commands under {MAX_TRANSCRIPT_LENGTH} characters")
    text = unicodedata.normalize("NFKC", transcript).replace("“", '"').replace("”", '"')
    if any(
        (unicodedata.category(char) == "Cc" and not char.isspace())
        or unicodedata.category(char) == "Cs"
        for char in text
    ):
        raise ValueError("Commands must contain printable text")
    text = re.sub(r"\s+", " ", text).strip().rstrip(".!?")
    text = re.sub(r"^please\s+", "", text, flags=re.IGNORECASE)
    if text.lower() in {"confirm", "confirm command", "yes confirm"}:
        return VoiceCommand("confirm", "Confirm the reviewed command.")
    if text.lower() in {"cancel", "cancel command", "never mind"}:
        return VoiceCommand("cancel", "Cancel the reviewed command.")

    command = _list_command(text)
    if command:
        return command

    match = re.fullmatch(
        r"(check\s*out|borrow|return|delete|remove|get|show|read|describe|find|display)\s+"
        r"(?:me\s+)?(?:item|book|dvd)\s+(?:(?:number|id)\s+)?#?(.+)",
        text,
        re.IGNORECASE,
    )
    if match:
        action = match[1].lower().replace(" ", "")
        item_id = positive_number(match[2])
        path = f"/api/items/{item_id}"
        if action in {"checkout", "borrow"}:
            return _write(
                "checkout", "POST", path + "/checkout", None, f"Check out item {item_id}."
            )
        if action == "return":
            return _write("return", "POST", path + "/return", None, f"Return item {item_id}.")
        if action in {"delete", "remove"}:
            return _write("delete", "DELETE", path, None, f"Permanently delete item {item_id}.")
        return VoiceCommand("get", f"Read item {item_id}.", "GET", path)

    match = re.fullmatch(
        r"(?:create|add|new)\s+(?:an?\s+)?(item|book|dvd)[ ,;.:]+(.+)", text, re.IGNORECASE
    )
    if match:
        fields = _read_fields(match[2])
        implied_type = match[1].lower()
        if implied_type != "item":
            if fields.get("type", implied_type) != implied_type:
                raise ValueError("The item type is ambiguous; choose book or DVD")
            fields["type"] = implied_type
        kind = fields.get("type")
        if kind not in {"book", "dvd"}:
            raise ValueError("Include type book or type DVD")
        detail = "page_count" if kind == "book" else "duration"
        if fields.keys() != {"type", "title", "author", detail}:
            raise ValueError(
                f"Creating a {kind} requires type, title, author and {'pages' if kind == 'book' else 'duration'}"
            )
        model = Book if kind == "book" else DVD
        model(fields["title"], fields["author"], fields[detail])
        return _write(
            "create",
            "POST",
            "/api/items",
            fields,
            f'Create {kind} "{fields["title"]}" by {fields["author"]}, '
            f"{fields[detail]} {'pages' if kind == 'book' else 'minutes'}.",
        )

    match = re.fullmatch(
        r"(update|change|edit|patch|replace)\s+(?:item|book|dvd)\s+(.+)", text, re.IGNORECASE
    )
    if match:
        tail = match[2]
        labels = _field_matches(tail)
        if not labels:
            raise ValueError("Include the fields to update, such as title or pages")
        target = tail[: labels[0].start()].strip(" ,;.")
        target = re.sub(r"^(?:number|id)\s+", "", target, flags=re.IGNORECASE)
        target = re.sub(r"\b(?:with|set)$", "", target, flags=re.IGNORECASE).strip(" ,;.")
        item_id = positive_number(target.lstrip("#"))
        fields = _read_fields(tail[labels[0].start() :])
        if "type" in fields:
            raise ValueError("An existing item's type cannot be changed")
        replace = match[1].lower() == "replace"
        if replace and fields.keys() not in (
            {"title", "author", "page_count"},
            {"title", "author", "duration"},
        ):
            raise ValueError("Replacing an item requires title, author and pages or duration")
        method = "PUT" if replace else "PATCH"
        action = "replace" if replace else "update"
        changes = "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in fields.items())
        return _write(
            action,
            method,
            f"/api/items/{item_id}",
            fields,
            f"{action.capitalize()} item {item_id}: {changes}.",
        )

    raise ValueError(
        "Command not understood. Try 'list available books' or use a command example below"
    )
