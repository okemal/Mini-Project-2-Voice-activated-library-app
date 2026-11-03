/**
 * Browser controller for the single-page collection dashboard.
 *
 * The Flask API is the source of truth. This file fetches JSON, builds list
 * rows with DOM methods (so item text is not interpreted as HTML), sends
 * create/update/delete and checkout/return requests, and refreshes the view.
 */
import { initVoice } from "./voice.js";

const itemList = document.querySelector("#item-list");
const notice = document.querySelector("#notice");
const noticeText = document.querySelector("#notice-text");
const form = document.querySelector("#item-form");
const panel = document.querySelector("#form-panel");
const titleInput = document.querySelector("#title");
const authorInput = document.querySelector("#author");
const detailInput = document.querySelector("#detail");
const filterButtons = [...document.querySelectorAll(".filter")];
let allItems = [];
let selectedType = "all";
let selectedItemType = "book";
let editingId = null;

/** Show a request result in the persistent page-level status area. */
function showNotice(message, isError = true) {
  noticeText.textContent = message;
  notice.classList.toggle("success", !isError);
  notice.hidden = false;
}

/** Hide the status area and clear its previous message. */
function clearNotice() {
  notice.hidden = true;
  noticeText.textContent = "";
}

/**
 * Send a same-origin API request and decode its JSON response.
 *
 * DELETE success is the only normal response without a body (HTTP 204). Error
 * bodies use ``{error: message}`` and become exceptions for the UI to display.
 */
async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "X-Library-Request": "1", ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request could not be completed.");
  return data;
}

/** Fetch the selected type view and the full collection for the counters. */
async function loadItems() {
  try {
    const [items, stats] = await Promise.all([
      api(`/api/items${selectedType === "all" ? "" : `?type=${selectedType}`}`),
      api("/api/items"),
    ]);
    allItems = stats;
    renderItems(items);
    updateStats(stats);
  } catch (error) {
    showNotice(error.message);
    itemList.replaceChildren();
    document.querySelector("#visible-count").textContent = "Unavailable";
  }
}

/** Recompute the total, available, and checked-out counters. */
function updateStats(items) {
  const available = items.filter((item) => item.is_available).length;
  document.querySelector("#total-count").textContent = String(items.length).padStart(2, "0");
  document.querySelector("#available-count").textContent = String(available).padStart(2, "0");
  document.querySelector("#loan-count").textContent = String(items.length - available).padStart(2, "0");
}

/** Create a text button without interpreting labels as HTML. */
function makeButton(label, className, action, accessibleLabel) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  if (accessibleLabel) button.setAttribute("aria-label", accessibleLabel);
  button.addEventListener("click", action);
  return button;
}

/** Create the accessible trash-can control for removing one item. */
function makeDeleteButton(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button delete-button";
  button.setAttribute("aria-label", `Delete ${item.title}`);
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("width", "16");
  icon.setAttribute("height", "16");
  icon.setAttribute("fill", "none");
  icon.setAttribute("stroke", "currentColor");
  icon.setAttribute("stroke-width", "1.7");
  icon.setAttribute("stroke-linecap", "round");
  icon.setAttribute("stroke-linejoin", "round");
  icon.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
  shape.setAttribute("d", "M4 7h16M10 11v6m4-6v6M5 7l1 14h12l1-14M9 7V4h6v3M3 7h18");
  icon.append(shape);
  button.append(icon);
  button.addEventListener("click", () => deleteItem(item));
  return button;
}

/** Rebuild the visible list, applying the availability toggle locally. */
function renderItems(items) {
  const availableOnly = document.querySelector("#available-only").checked;
  const visible = items.filter((item) => !availableOnly || item.is_available);
  itemList.replaceChildren();
  document.querySelector("#visible-count").textContent = `${visible.length} item${visible.length === 1 ? "" : "s"}`;
  document.querySelector("#list-summary").textContent = `Showing ${visible.length} of ${allItems.length} item${allItems.length === 1 ? "" : "s"}`;

  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = `empty-list${allItems.length === 0 ? " collection-empty" : ""}`;
    if (allItems.length === 0) {
      const heading = document.createElement("strong");
      heading.textContent = "No items yet";
      const message = document.createElement("p");
      message.textContent = "Add your first book or DVD to begin building your collection.";
      empty.append(heading, message, makeButton("＋ Add your first item", "button button-primary", () => openForm()));
    } else {
      empty.textContent = "No items match these filters. Try another view.";
    }
    itemList.append(empty);
    return;
  }

  visible.forEach((item) => {
    const row = document.createElement("article");
    row.className = `item-row${item.is_available ? " available-highlight" : ""}`;
    const info = document.createElement("div");
    info.className = "item-main";
    const name = document.createElement("div");
    name.className = "item-name";
    name.textContent = item.title;
    const author = document.createElement("div");
    author.className = "item-author";
    author.textContent = `${item.author} · ID ${item.id}`;
    info.append(name, author);

    const meta = document.createElement("div");
    meta.className = "item-meta";
    const type = document.createElement("div");
    type.className = "item-type";
    type.textContent = item.type === "dvd" ? "DVD" : "Book";
    const extent = document.createElement("div");
    extent.className = "item-detail-sub";
    extent.textContent = item.type === "dvd" ? `${item.duration} min` : `${item.page_count} pages`;
    meta.append(type, extent);

    const status = document.createElement("span");
    status.className = `status item-status${item.is_available ? " available" : ""}`;
    status.textContent = item.is_available ? "Available" : "Checked out";

    const actions = document.createElement("div");
    actions.className = "actions";
    actions.append(makeButton(item.is_available ? "Checkout" : "Return", `button ${item.is_available ? "button-primary" : "button-secondary"}`, () => toggleLoan(item), `${item.is_available ? "Check out" : "Return"} ${item.title}`));
    actions.append(makeButton("✎", "icon-button", () => openForm(item), `Edit ${item.title}`));
    actions.append(makeDeleteButton(item));
    row.append(info, meta, status, actions);
    itemList.append(row);
  });
}

/** Call the item's checkout or return endpoint based on its current state. */
async function toggleLoan(item) {
  clearNotice();
  try {
    const action = item.is_available ? "checkout" : "return";
    const result = await api(`/api/items/${item.id}/${action}`, { method: "POST" });
    showNotice(result.message || `${item.title} ${item.is_available ? "checked out" : "returned"}.`, false);
    await loadItems();
  } catch (error) {
    showNotice(error.message);
  }
}

/** Delete an item; the API reports checked-out items as a conflict. */
async function deleteItem(item) {
  if (!window.confirm(`Permanently delete item ${item.id}, “${item.title}”?`)) return;
  clearNotice();
  try {
    await api(`/api/items/${item.id}`, { method: "DELETE" });
    if (editingId === item.id) resetForm();
    showNotice(`${item.title} was removed from the collection.`, false);
    await loadItems();
  } catch (error) {
    showNotice(error.message);
  }
}

/** Keep the form's detail label, units, help, and selected type in sync. */
function setType(type) {
  selectedItemType = type;
  document.querySelectorAll(".type-option[data-item-type]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.itemType === type);
  });
  const isBook = type === "book";
  document.querySelector("#detail-label").textContent = isBook ? "Page count" : "Duration (minutes)";
  document.querySelector("#detail-unit").textContent = isBook ? "pages" : "min";
  document.querySelector("#detail-help").textContent = isBook
    ? "Total number of pages in this edition."
    : "Running time of the DVD in minutes.";
  detailInput.placeholder = isBook ? "320" : "124";
}

/** Prepare the form to create a new item or edit an existing one. */
function openForm(item = null) {
  editingId = item?.id ?? null;
  document.querySelector("#form-title").textContent = item ? "Edit item" : "Add an item";
  document.querySelector(".save-button").textContent = item ? "Save changes" : "Save item";
  document.querySelector("#editing-summary").textContent = item ? `Editing ${item.title} →` : "";
  titleInput.value = item?.title || "";
  authorInput.value = item?.author || "";
  selectedItemType = item?.type || selectedItemType;
  setType(selectedItemType);
  detailInput.value = item ? (item.type === "dvd" ? item.duration : item.page_count) : "";
  const typeButtons = [...document.querySelectorAll(".type-option[data-item-type]")];
  typeButtons.forEach((button) => { button.disabled = Boolean(item); });
  panel.classList.add("mobile-open");
  if (window.matchMedia("(max-width: 720px)").matches) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  if (!item) titleInput.focus({ preventScroll: true });
}

/** Clear edit state and restore the blank Book creation form. */
function resetForm() {
  editingId = null;
  form.reset();
  document.querySelector("#form-title").textContent = "Add an item";
  document.querySelector(".save-button").textContent = "Save item";
  document.querySelector("#editing-summary").textContent = "";
  document.querySelectorAll(".type-option[data-item-type]").forEach((button) => { button.disabled = false; });
  setType("book");
  panel.classList.remove("mobile-open");
}

// PUT sends the complete type-specific field set; POST adds the chosen type.
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearNotice();
  const detailName = selectedItemType === "book" ? "page_count" : "duration";
  const payload = {
    title: titleInput.value.trim(),
    author: authorInput.value.trim(),
    [detailName]: Number(detailInput.value),
  };
  try {
    const isEditing = editingId !== null;
    const url = isEditing ? `/api/items/${editingId}` : "/api/items";
    const data = await api(url, {
      method: isEditing ? "PUT" : "POST",
      body: JSON.stringify(isEditing ? payload : { ...payload, type: selectedItemType }),
    });
    showNotice(isEditing ? `${data.title} was updated.` : `${data.title} was added to the collection.`, false);
    resetForm();
    await loadItems();
  } catch (error) {
    showNotice(error.message);
  }
});

filterButtons.forEach((button) => button.addEventListener("click", () => {
  selectedType = button.dataset.type;
  filterButtons.forEach((filter) => filter.classList.toggle("active", filter === button));
  clearNotice();
  loadItems();
}));
document.querySelector("#available-only").addEventListener("change", () => { clearNotice(); loadItems(); });
document.querySelectorAll(".type-option[data-item-type]").forEach((button) => button.addEventListener("click", () => setType(button.dataset.itemType)));
document.querySelector("#add-item").addEventListener("click", () => openForm());
document.querySelector("#cancel-form").addEventListener("click", resetForm);
document.querySelector("#close-form").addEventListener("click", resetForm);
document.querySelector("#dismiss-notice").addEventListener("click", clearNotice);

setType("book");
loadItems();
initVoice({ api, loadItems, showNotice });
