import pytest

from voice_commands import parse_command, positive_number


@pytest.mark.parametrize(
    "text,method,path,body",
    [
        ("List items", "GET", "/api/items", None),
        ("Please show all books.", "GET", "/api/items?type=book", None),
        ("list available DVDs", "GET", "/api/items?type=dvd&available=true", None),
        ("show checked out books", "GET", "/api/items?type=book&available=false", None),
        ("list items that are on loan", "GET", "/api/items?available=false", None),
        ("List unavailable items", "GET", "/api/items?available=false", None),
        ("get item three", "GET", "/api/items/3", None),
        ("Read item ID 3", "GET", "/api/items/3", None),
        ("Check out item three", "POST", "/api/items/3/checkout", None),
        ("checkout book #3", "POST", "/api/items/3/checkout", None),
        ("borrow DVD 2", "POST", "/api/items/2/checkout", None),
        ("Return item 3", "POST", "/api/items/3/return", None),
        ("Remove item three", "DELETE", "/api/items/3", None),
        ("delete item 3", "DELETE", "/api/items/3", None),
        (
            "Update item 3, pages three hundred and ten",
            "PATCH",
            "/api/items/3",
            {"page_count": 310},
        ),
        ("Change item ID 2 with duration 148", "PATCH", "/api/items/2", {"duration": 148}),
        ("Edit item 3, title is A New Title", "PATCH", "/api/items/3", {"title": "A New Title"}),
        (
            "Replace item 3, title Hobbit, author Tolkien, pages 320",
            "PUT",
            "/api/items/3",
            {"title": "Hobbit", "author": "Tolkien", "page_count": 320},
        ),
        (
            "replace item two title Inception director Nolan minutes 148",
            "PUT",
            "/api/items/2",
            {"title": "Inception", "author": "Nolan", "duration": 148},
        ),
        (
            "Create item, type book, title The Catcher in the Rye, author J.D. Salinger, pages 220",
            "POST",
            "/api/items",
            {
                "type": "book",
                "title": "The Catcher in the Rye",
                "author": "J.D. Salinger",
                "page_count": 220,
            },
        ),
        (
            "add DVD title Spirited Away author Hayao Miyazaki duration one hundred twenty five",
            "POST",
            "/api/items",
            {"type": "dvd", "title": "Spirited Away", "author": "Hayao Miyazaki", "duration": 125},
        ),
        (
            'Create book, title "The Author Returns, Again", author "Pages and Title", pages 12',
            "POST",
            "/api/items",
            {
                "type": "book",
                "title": "The Author Returns, Again",
                "author": "Pages and Title",
                "page_count": 12,
            },
        ),
    ],
)
def test_request_mapping(text, method, path, body):
    command = parse_command(text)
    assert (command.method, command.path, command.body) == (method, path, body)
    assert command.requires_confirmation == (method != "GET")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        3,
        "do anything",
        "yes",
        "do not confirm",
        "don't delete item 3",
        "check out item three and delete item two",
        "get item https://example.com",
        "checkout item 0",
        "delete item -2",
        "return item 3.5",
        "get item true",
        "Create item, title Missing, author A, pages 10",
        "create book title B author A pages 0",
        "create book title B author A pages 10 duration 20",
        "create book type DVD title B author A pages 10",
        "create item type magazine title B author A pages 10",
        "replace item 1 title B",
        "update item 1 type dvd",
        "update item 1",
        "update item 1 pages 2 pages 3",
        'update item 1 title "unclosed',
        "list available items checked out",
        "x" * 1201,
        "delete item 1\0",
    ],
)
def test_incomplete_or_ambiguous_input_is_rejected(text):
    with pytest.raises(ValueError):
        parse_command(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", 1),
        ("one", 1),
        ("thirteen", 13),
        ("twenty-two", 22),
        ("one hundred", 100),
        ("two hundred twenty", 220),
        ("1,024", 1024),
        ("one thousand and five", 1005),
        ("twelve thousand three hundred forty five", 12345),
        ("nine hundred ninety nine thousand nine hundred ninety nine", 999999),
    ],
)
def test_spoken_numbers(text, expected):
    assert positive_number(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "zero",
        "one two",
        "hundred",
        "one hundred and",
        "one thousand and",
        "one or two",
        "-3",
        "3.2",
        "1,2",
        "two thousand thousand",
        "999999999999999",
    ],
)
def test_ambiguous_numbers_are_rejected(text):
    with pytest.raises(ValueError):
        positive_number(text)


@pytest.mark.parametrize(
    "text,action",
    [
        ("Confirm.", "confirm"),
        ("yes confirm", "confirm"),
        ("cancel command", "cancel"),
        ("never mind", "cancel"),
    ],
)
def test_control_commands_cannot_make_requests(text, action):
    command = parse_command(text)
    assert command.action == action
    assert command.method is command.path is command.body is None


def test_sentence_punctuation_and_explicit_field_phrasing():
    command = parse_command(
        "Create item. Type is book. Title is Dune. Author is Frank Herbert. Pages 412."
    )
    assert command.body == {
        "type": "book",
        "title": "Dune",
        "author": "Frank Herbert",
        "page_count": 412,
    }
    assert "412 pages" in command.summary


def test_title_starting_with_to_is_not_changed():
    command = parse_command("Create book title To Kill a Mockingbird author Harper Lee pages 281")
    assert command.body["title"] == "To Kill a Mockingbird"
