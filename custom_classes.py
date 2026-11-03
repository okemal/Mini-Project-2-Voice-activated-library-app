"""Domain model for library items and the collection that manages them.

The classes in this module contain the library's state and rules. HTTP handlers
and other callers should use :class:`LibraryCollection` methods instead of
changing item IDs or bypassing the checkout and update operations.
"""

from typing import override


class ItemNotFoundError(LookupError):
    """Raised when a collection lookup references an ID it does not contain.

    This exception is intended for callers that need to distinguish a missing
    item from invalid input or an invalid state transition.
    """


class ItemStateError(ValueError):
    """Raised when an item cannot make a requested availability transition.

    Checkout of an unavailable item, return of an available item, and removal
    of a checked-out item are invalid transitions and raise this exception.
    """


class MediaItem:
    """Represent a generic library item that can be checked out and returned.

    An item starts without an ID. A :class:`LibraryCollection` assigns its ID
    when it is added. The ID is read-only through the public interface and the
    same item instance can only be assigned to a collection once.

    Args:
        title: Non-empty display title. Surrounding whitespace is stripped.
        author: Non-empty author, creator, or director name. Whitespace is
            stripped before the value is stored.
        is_available: Initial checkout state. Defaults to ``True``.

    Raises:
        ValueError: If the title or author is empty, or availability is not a
            boolean.
    """

    def __init__(self, title: str, author: str, is_available: bool = True) -> None:
        self._id: int | None = None
        self.title = self._validate_text("title", title)
        self.author = self._validate_text("author", author)
        if not isinstance(is_available, bool):
            raise ValueError("is_available must be a boolean")
        self.is_available = is_available

    @property
    def id(self) -> int | None:
        """Return the collection-assigned ID, if this item has been added."""
        return self._id

    def _assign_id(self, item_id: int) -> None:
        """Assign the collection's next ID exactly once.

        This is an internal collection operation. IDs are never overwritten,
        even when an item is later removed from its collection.

        Args:
            item_id: The positive integer ID selected by the collection.

        Raises:
            ValueError: If this item already has an ID.
        """
        if self._id is not None:
            raise ValueError("An item can only be added to a collection once")
        self._id = item_id

    @staticmethod
    def _validate_text(field: str, value: object) -> str:
        """Validate and normalize a required text field."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _validate_positive_integer(field: str, value: object) -> int:
        """Validate a positive integer, explicitly rejecting booleans."""
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
        return value

    def _validate_update(self, field: str, value: object) -> object:
        """Validate a base-class editable field before an update is applied.

        Subclasses extend this method for their own type-specific attributes.
        """
        if field in {"title", "author"}:
            return self._validate_text(field, value)
        raise ValueError(f"Field cannot be updated: {field}")

    def checkout(self) -> str:
        """Mark the item checked out and return a success message.

        Returns:
            A message describing the successful checkout.

        Raises:
            ItemStateError: If the item is already checked out. Its state is
                left unchanged when this happens.
        """
        if not self.is_available:
            raise ItemStateError(f"Item {self.id} is already checked out")
        self.is_available = False
        return "Successful checkout"

    def return_item(self) -> None:
        """Mark the item available again.

        Raises:
            ItemStateError: If the item is already available. Its state is
                left unchanged when this happens.
        """
        if self.is_available:
            raise ItemStateError(f"Item {self.id} is not checked out")
        self.is_available = True

    def to_dict(self) -> dict[str, int | str | bool | None]:
        """Serialize the common item data for JSON or other consumers.

        ``type`` is the lowercase class name (``"mediaitem"`` for this base
        class). An item not yet added to a collection has an ``id`` of ``None``.
        Subclasses add their type-specific measurement field.
        """
        return {
            "id": self.id,
            "type": type(self).__name__.lower(),
            "title": self.title,
            "author": self.author,
            "is_available": self.is_available,
        }

    @override
    def __str__(self) -> str:
        status = "Available" if self.is_available else "Checked Out"
        return f"{self.title} by {self.author} {status}"


class Book(MediaItem):
    """Represent a book whose extent is measured in pages.

    Args:
        title: Non-empty book title.
        author: Non-empty author name.
        page_count: Positive number of pages in the edition.
        is_available: Initial availability state.

    Raises:
        ValueError: If any text field is empty, availability is not boolean,
            or ``page_count`` is not a positive integer.
    """

    def __init__(self, title: str, author: str, page_count: int, is_available: bool = True) -> None:
        super().__init__(title, author, is_available)
        self.page_count = self._validate_positive_integer("page_count", page_count)

    @override
    def _validate_update(self, field: str, value: object) -> object:
        if field == "page_count":
            return self._validate_positive_integer(field, value)
        return super()._validate_update(field, value)

    @override
    def to_dict(self) -> dict[str, int | str | bool | None]:
        """Return common fields plus ``page_count`` using API field names."""
        return {
            "id": self.id,
            "type": "book",
            "title": self.title,
            "author": self.author,
            "page_count": self.page_count,
            "is_available": self.is_available,
        }

    @override
    def __str__(self) -> str:
        status = "Available" if self.is_available else "Checked Out"
        return f"{self.title} by {self.author} {status} ({self.page_count} pages)"


class DVD(MediaItem):
    """Represent a DVD whose running time is measured in whole minutes.

    Args:
        title: Non-empty DVD title.
        author: Non-empty creator or director name.
        duration: Positive running time in minutes.
        is_available: Initial availability state.

    Raises:
        ValueError: If any text field is empty, availability is not boolean,
            or ``duration`` is not a positive integer.
    """

    def __init__(self, title: str, author: str, duration: int, is_available: bool = True) -> None:
        super().__init__(title, author, is_available)
        self.duration = self._validate_positive_integer("duration", duration)

    @override
    def _validate_update(self, field: str, value: object) -> object:
        if field == "duration":
            return self._validate_positive_integer(field, value)
        return super()._validate_update(field, value)

    @override
    def checkout(self) -> str:
        """Check out the DVD and include the disc-care reminder in the result.

        The base implementation performs the state transition and raises
        :class:`ItemStateError` if the DVD is already checked out.
        """
        super().checkout()
        return "Successful checkout. Handle with care: Do not scratch the disc."

    @override
    def to_dict(self) -> dict[str, int | str | bool | None]:
        """Return common fields plus ``duration`` using API field names."""
        return {
            "id": self.id,
            "type": "dvd",
            "title": self.title,
            "author": self.author,
            "duration": self.duration,
            "is_available": self.is_available,
        }


class LibraryCollection:
    """Manage item membership, stable IDs, filtering, and permitted updates.

    IDs start at one and increase for each successful addition. Deleting an
    item never lowers the counter or makes its ID available again. The initial
    ``items`` iterable, when provided as a list, is added in order and receives
    IDs using the same rule.

    Args:
        items: Optional starting list of ``MediaItem`` objects.

    Raises:
        TypeError: If a starting entry is not a ``MediaItem``.
        ValueError: If a starting item was already assigned an ID.
    """

    def __init__(self, items: list[MediaItem] | None = None) -> None:
        self.items: list[MediaItem] = []
        self._next_id = 1
        for item in items or []:
            self.add_item(item)

    def add_item(self, item: MediaItem) -> int:
        """Add a new item, assign its next ID, and return that ID.

        Args:
            item: A previously unassigned ``MediaItem`` instance.

        Returns:
            The unique integer ID assigned to ``item``.

        Raises:
            TypeError: If ``item`` is not a ``MediaItem``.
            ValueError: If the item already has an ID, including when it was
                removed earlier. Re-adding an old object would undermine the
                never-reuse guarantee, so callers should create a new object.
        """
        if not isinstance(item, MediaItem):
            raise TypeError("item must be a MediaItem")
        if item.id is not None:
            raise ValueError("An item can only be added to a collection once")
        item._assign_id(self._next_id)
        self._next_id += 1
        self.items.append(item)
        return item.id

    def get_item(self, item_id: int) -> MediaItem:
        """Find and return one item by its collection ID.

        Args:
            item_id: Integer ID to find.

        Raises:
            ItemNotFoundError: If there is no current item with that ID.
        """
        for item in self.items:
            if item.id == item_id:
                return item
        raise ItemNotFoundError(f"No item with ID {item_id}")

    def list_items(
        self, available: bool | None = None, item_type: str | None = None
    ) -> list[MediaItem]:
        """Return a new list of items matching the optional filters.

        Args:
            available: ``True`` for available items, ``False`` for checked-out
                items, or ``None`` to include both states.
            item_type: Exact Python class name such as ``"Book"`` or ``"DVD"``.
                ``None`` includes every media type.

        Returns:
            Matching items in their current collection order. The returned
            list is a copy; changing its membership does not change the
            collection.
        """
        result = self.items
        if available is not None:
            result = [item for item in result if item.is_available is available]
        if item_type is not None:
            result = [item for item in result if type(item).__name__ == item_type]
        return list(result)

    def update_item(self, item_id: int, **fields: object) -> MediaItem:
        """Change one or more editable attributes and return the item.

        Every supplied field is validated before any mutation is applied.
        Common editable fields are ``title`` and ``author``; books additionally
        accept ``page_count`` and DVDs additionally accept ``duration``.
        IDs, type, availability, and fields irrelevant to the item's subtype
        cannot be changed through this method.

        Args:
            item_id: ID of the item to update.
            **fields: Partial set of editable field names and new values. An
                empty set is accepted as a no-op.

        Returns:
            The same item object after its fields have been updated.

        Raises:
            ItemNotFoundError: If the ID is not in the collection.
            ValueError: If any field is not editable or any value is invalid.
                No fields are changed when validation fails.
        """
        item = self.get_item(item_id)
        protected = {"id", "type", "is_available"}
        editable = {"title", "author"}
        if isinstance(item, Book):
            editable.add("page_count")
        if isinstance(item, DVD):
            editable.add("duration")
        invalid = protected.intersection(fields) | (fields.keys() - editable)
        if invalid:
            names = ", ".join(sorted(invalid))
            raise ValueError(f"Fields cannot be updated: {names}")
        validated = {name: item._validate_update(name, value) for name, value in fields.items()}
        for name, value in validated.items():
            setattr(item, name, value)
        return item

    def replace_item(self, item_id: int, **fields: object) -> MediaItem:
        """Replace every editable field for an item in one operation.

        A book replacement must provide exactly ``title``, ``author``, and
        ``page_count``. A DVD replacement must provide exactly ``title``,
        ``author``, and ``duration``. This supports HTTP ``PUT`` semantics;
        use :meth:`update_item` for partial changes.

        Args:
            item_id: ID of the item to replace.
            **fields: Complete set of editable fields for that subtype.

        Returns:
            The updated item.

        Raises:
            ItemNotFoundError: If the item does not exist.
            ValueError: If fields are missing, extra, protected, or invalid.
        """
        item = self.get_item(item_id)
        required = {"title", "author"}
        if isinstance(item, Book):
            required.add("page_count")
        if isinstance(item, DVD):
            required.add("duration")
        if fields.keys() != required:
            raise ValueError(
                f"Replacement requires exactly these fields: {', '.join(sorted(required))}"
            )
        return self.update_item(item_id, **fields)

    def remove_item(self, item_id: int) -> MediaItem:
        """Remove and return an available item without recycling its ID.

        Args:
            item_id: ID of the item to remove.

        Raises:
            ItemNotFoundError: If the item does not exist.
            ItemStateError: If it is checked out. The collection is unchanged.
        """
        item = self.get_item(item_id)
        if not item.is_available:
            raise ItemStateError(f"Cannot remove checked-out item {item_id}")
        self.items.remove(item)
        return item

    def list_available(self) -> list[str]:
        """Return titles of all currently available items in collection order."""
        return [item.title for item in self.items if item.is_available]
