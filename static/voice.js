import { PCMRecorder } from "./recorder.js";

function itemDescription(item) {
  const extent = item.type === "book" ? `${item.page_count} pages` : `${item.duration} minutes`;
  return `Item ${item.id}, “${item.title}”, by ${item.author}. ${extent}. ${item.is_available ? "Available" : "Checked out"}.`;
}

/** Build feedback only from a successful response, never from an intended write. */
export function resultMessage(command, data) {
  const item = data?.item || data;
  switch (command.action) {
    case "list": {
      const count = data.length;
      const titles = data.slice(0, 5).map((entry) => `Item ${entry.id}, “${entry.title}”, ${entry.is_available ? "available" : "checked out"}.`).join(" ");
      return `Found ${count} item${count === 1 ? "" : "s"}. ${titles}${count > 5 ? " The remaining items are shown on screen." : ""}`.trim();
    }
    case "get": return itemDescription(item);
    case "create": return `Successfully created ${item.type} “${item.title}” with ID ${item.id}.`;
    case "update": return `Updated item ${item.id}. ${itemDescription(item)}`;
    case "replace": return `Replaced the editable fields of item ${item.id}. ${itemDescription(item)}`;
    case "checkout": return `Item ${item.id}, “${item.title}”, has been checked out.${item.type === "dvd" ? " Handle with care: do not scratch the disc." : ""}`;
    case "return": return `Item ${item.id}, “${item.title}”, has been returned.`;
    case "delete": return `Successfully deleted item ${command.path.split("/")[3]}${command.target ? `, “${command.target.title}”` : ""}.`;
    default: throw new Error("The server returned an unsupported command.");
  }
}

export function initVoice({ api, loadItems, showNotice }) {
  const find = (id) => document.getElementById(id);
  const recordButton = find("voice-record");
  const transcript = find("voice-transcript");
  const state = find("voice-state");
  const responseText = find("voice-response-text");
  const audio = find("voice-audio");
  const audioStatus = find("voice-audio-status");
  const review = find("voice-review");
  const results = find("voice-results");
  const speakToggle = find("voice-speak");
  const recorder = new PCMRecorder();
  const supported = Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode);
  let configured = false;
  let busy = false;
  let recording = false;
  let pending = null;
  let reviewTimer;
  let recordingTimer;
  let recordingStart;
  let audioUrl;
  let audioRequest;
  let playbackVersion = 0;

  function updateControls() {
    recordButton.disabled = busy || !configured || !supported;
    recordButton.textContent = recording ? "Stop & transcribe" : "Start speaking";
    recordButton.classList.toggle("is-recording", recording);
    recordButton.setAttribute("aria-pressed", String(recording));
    find("voice-discard").hidden = !recording;
    find("voice-discard").disabled = busy;
    transcript.readOnly = busy || recording;
    ["voice-submit", "voice-confirm", "voice-cancel"].forEach((id) => { find(id).disabled = busy || recording; });
    document.querySelectorAll("[data-command]").forEach((button) => { button.disabled = busy || recording; });
  }

  function stopAudio() {
    playbackVersion += 1;
    audioRequest?.abort();
    audio.pause();
    audio.removeAttribute("src");
    audio.hidden = true;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = null;
    audioStatus.textContent = "";
  }

  /** Speech failure is separate from command failure; a write is never retried. */
  async function speak(text) {
    stopAudio();
    if (!speakToggle.checked) return;
    if (!configured) {
      audioStatus.textContent = "Configure Azure Speech on the server to hear this response.";
      return;
    }
    const version = playbackVersion;
    audioRequest = new AbortController();
    audioStatus.textContent = "Preparing spoken reply…";
    try {
      const response = await fetch("/api/speech/synthesize", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Library-Request": "1" },
        body: JSON.stringify({ text: text.slice(0, 2000) }), signal: audioRequest.signal,
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || "The spoken reply is unavailable.");
      }
      const blob = await response.blob();
      if (version !== playbackVersion) return;
      audioUrl = URL.createObjectURL(blob);
      audio.src = audioUrl;
      audio.hidden = false;
      try {
        await audio.play();
        audioStatus.textContent = "Azure spoken reply · use the player to replay or pause.";
      } catch {
        audioStatus.textContent = "Press play to hear the Azure spoken reply.";
      }
    } catch (error) {
      if (error.name !== "AbortError" && version === playbackVersion) {
        audioStatus.textContent = `Spoken reply unavailable: ${error.message} The written response is above.`;
      }
    }
  }

  function clearReview() {
    pending = null;
    clearTimeout(reviewTimer);
    review.hidden = true;
  }

  function clearResults() {
    results.replaceChildren();
    results.hidden = true;
  }

  async function reportError(error) {
    clearReview();
    clearResults();
    const message = `Sorry, ${error.message}`;
    responseText.textContent = message;
    state.textContent = "Command could not be completed.";
    showNotice(message);
    await speak(message);
  }

  async function runBusy(action) {
    if (busy) return;
    busy = true;
    updateControls();
    try { await action(); }
    catch (error) { await reportError(error); }
    finally { busy = false; updateControls(); }
  }

  async function execute(command) {
    // Consume the review before sending the request, preventing double submits.
    clearReview();
    state.textContent = "Running command…";
    let data;
    try {
      data = await api(command.path, {
        method: command.method,
        ...(command.body ? { body: JSON.stringify(command.body) } : {}),
        headers: command.etag ? { "If-Match": command.etag } : {},
      });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new Error("The connection was interrupted. Check the collection before trying the command again.");
      }
      throw error;
    }
    const message = resultMessage(command, data);
    responseText.textContent = message;
    state.textContent = "Command completed.";
    clearResults();
    if (command.action === "list" || command.action === "get") {
      const items = Array.isArray(data) ? data : [data];
      items.forEach((item) => {
        const row = document.createElement("li");
        row.textContent = itemDescription(item);
        results.append(row);
      });
      results.hidden = items.length === 0;
    }
    if (command.method !== "GET") await loadItems();
    showNotice(message, false);
    await speak(message);
  }

  async function confirm() {
    if (!pending) throw new Error("There is no command waiting for confirmation.");
    if (Date.now() > pending.expiresAt) {
      clearReview();
      throw new Error("The review expired. Review your command again.");
    }
    await execute(pending.command);
  }

  async function cancel() {
    clearReview();
    clearResults();
    responseText.textContent = "Command cancelled. No changes were made.";
    state.textContent = "Ready for another command.";
    await speak(responseText.textContent);
  }

  async function processText() {
    stopAudio();
    state.textContent = "Understanding command…";
    const { command } = await api("/api/voice/parse", {
      method: "POST", body: JSON.stringify({ text: transcript.value }),
    });
    if (command.action === "confirm") return confirm();
    if (command.action === "cancel") return cancel();
    clearReview();
    clearResults();
    if (!command.requires_confirmation) return execute(command);
    pending = { command, expiresAt: Date.now() + 120000 };
    review.hidden = false;
    find("voice-summary").textContent = command.summary;
    const target = command.target;
    find("voice-target").textContent = target
      ? `Current record: ${itemDescription(target)}`
      : command.action === "create" ? "A new ID will be assigned by the library." : "This ID is not currently in the collection.";
    responseText.textContent = "Your command is ready for review.";
    state.textContent = "Waiting for confirmation.";
    reviewTimer = setTimeout(() => {
      clearReview();
      responseText.textContent = "The review expired. Review your command again to continue.";
      state.textContent = "Ready for another command.";
    }, 120000);
    await speak(`${command.summary} ${find("voice-target").textContent} Say confirm to apply this change, or cancel.`);
  }

  async function finishRecording(discard = false) {
    if (!recording || busy) return;
    recording = false;
    clearInterval(recordingTimer);
    await runBusy(async () => {
      state.textContent = discard ? "Discarding recording…" : "Transcribing with Azure…";
      const wav = await recorder.stop(discard);
      if (discard) {
        state.textContent = "Recording discarded.";
        return;
      }
      const response = await fetch("/api/speech/recognize", {
        method: "POST", headers: { "Content-Type": "audio/wav", "X-Library-Request": "1" }, body: wav,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Speech recognition failed.");
      transcript.value = data.text;
      await processText();
    });
  }

  recordButton.addEventListener("click", async () => {
    if (recording) return finishRecording();
    await runBusy(async () => {
      stopAudio();
      state.textContent = "Waiting for microphone permission…";
      try {
        await recorder.start(() => finishRecording());
      } catch (error) {
        const messages = {
          NotAllowedError: "Microphone permission was denied. Allow access in your browser, or type a command.",
          NotFoundError: "No microphone was found. Connect one, or type a command.",
          NotReadableError: "The microphone is busy or unavailable. Check it, or type a command.",
        };
        throw new Error(messages[error.name] || "Could not start the microphone. Try again, or type a command.");
      }
      recording = true;
      recordingStart = performance.now();
      state.textContent = "Listening… 0 / 30 seconds. Click stop when finished.";
      recordingTimer = setInterval(() => {
        const seconds = Math.floor((performance.now() - recordingStart) / 1000);
        state.textContent = `Listening… ${Math.min(seconds, 30)} / 30 seconds. Click stop when finished.`;
        if (seconds >= 30) finishRecording();
      }, 250);
    });
  });
  find("voice-discard").addEventListener("click", () => finishRecording(true));
  find("voice-form").addEventListener("submit", (event) => { event.preventDefault(); runBusy(processText); });
  find("voice-confirm").addEventListener("click", () => runBusy(confirm));
  find("voice-cancel").addEventListener("click", () => runBusy(cancel));
  transcript.addEventListener("input", () => {
    if (pending) state.textContent = "Command edited. Review it again before confirming.";
    clearReview();
  });
  speakToggle.addEventListener("change", () => { if (!speakToggle.checked) stopAudio(); });
  document.querySelectorAll("[data-command]").forEach((button) => button.addEventListener("click", () => {
    clearReview();
    transcript.value = button.dataset.command;
    transcript.focus();
    state.textContent = "Example selected. Edit it, then review the command.";
  }));
  window.addEventListener("pagehide", () => { stopAudio(); recorder.release(); clearInterval(recordingTimer); });
  api("/api/speech/status").then((status) => {
    configured = status.configured;
    state.textContent = !supported
      ? "Microphone recording needs a supported browser on localhost or HTTPS. You can type a command."
      : configured ? "Ready. Start speaking, or type a command." : "Add your Azure key and region to .env, then restart. Typed commands work now.";
    updateControls();
  }).catch(() => {
    state.textContent = "Could not check speech configuration. Reload the page to try again.";
    updateControls();
  });
  updateControls();
}
