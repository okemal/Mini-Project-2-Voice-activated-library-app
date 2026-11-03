"""Run a small terminal walkthrough of the library domain model.

The script creates mixed item types and exercises serialization, lookup,
filtering, checkout/return, partial updates, safe deletion, and ID allocation
after deletion. It deliberately triggers and catches expected domain errors;
run it with ``python3 main.py`` from the repository root.
"""

from custom_classes import (
    DVD,
    Book,
    ItemNotFoundError,
    ItemStateError,
    LibraryCollection,
    MediaItem,
)

collection = LibraryCollection()
guide = Book("The Hitchhiker's Guide to the Galaxy", "Douglas Adams", 224)
inception = DVD("Inception", "Christopher Nolan", 148)
express = MediaItem("Chungking Express", "Wong Kar-wai")

guide_id = collection.add_item(guide)
dvd_id = collection.add_item(inception)
express_id = collection.add_item(express)
print("Added IDs:", guide_id, dvd_id, express_id)

print("Book dictionary:", guide.to_dict())
print("DVD dictionary:", inception.to_dict())
print("Found item:", collection.get_item(guide_id))
print("All items:", [item.to_dict() for item in collection.list_items()])
print(
    "Available books:",
    [item.title for item in collection.list_items(available=True, item_type="Book")],
)

print("DVD checkout:", inception.checkout())
try:
    inception.checkout()
except ItemStateError as error:
    print("Expected checkout error:", error)
inception.return_item()
try:
    inception.return_item()
except ItemStateError as error:
    print("Expected return error:", error)

collection.update_item(guide_id, title="The Hitchhiker's Guide", page_count=225)
print("Updated book:", guide.to_dict())
try:
    collection.update_item(guide_id, is_available=False)
except ValueError as error:
    print("Expected update error:", error)

try:
    collection.get_item(999)
except ItemNotFoundError as error:
    print("Expected missing-item error:", error)

guide.checkout()
try:
    collection.remove_item(guide_id)
except ItemStateError as error:
    print("Expected remove error:", error)
guide.return_item()
removed = collection.remove_item(guide_id)
print("Removed:", removed.title)
new_id = collection.add_item(Book("New item", "New author", 10))
print("ID after removal (not reused):", new_id)
print("Available titles:", collection.list_available())
