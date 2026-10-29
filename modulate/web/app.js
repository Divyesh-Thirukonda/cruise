"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const ui = {
    state: null, token: null, online: false, submitting: false, mutating: new Set(),
    previewKey: null, previewLoaded: false, previewError: false, eventKey: null,
    inspectSource: "active", inspectView: "code", pairing: null, noticeTimer: null,
  };
  const names = {joystick: "Joystick", encoder: "Encoder", button_a: "Button A",
    button_b: "Button B", encoder_pressed: "Encoder press", pitft_buttons: "PiTFT buttons"};

  function text(id, value) {
    const element = $(id);
    const next = String(value ?? "");
    if (element.textContent !== next) element.textContent = next;
  }

  function human(value) {
    return String(value ?? "").replace(/_/g, " ").replace(/^./, (first) => first.toUpperCase());
  }

  function stringify(value) {
    if (typeof value === "string") return value;
    try { return JSON.stringify(value, null, 2); } catch (_) { return "Details unavailable"; }
  }

  function dateValue(value) {
    if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
    return Date.parse(value);
  }

  function timeLabel(value) {
    const date = new Date(dateValue(value));
    return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "";
  }

  function announce(message, error = false) {
    clearTimeout(ui.noticeTimer);
    const notice = $("action-notice");
    text("action-notice", message);
    notice.className = error ? "notice notice-error" : "notice";
    notice.hidden = false;
    if (!error) ui.noticeTimer = setTimeout(() => { notice.hidden = true; }, 7000);
  }

  async function fetchJSON(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options, signal: controller.signal});
      let result;
      try { result = await response.json(); } catch (_) { throw new Error("The studio returned an unreadable response."); }
      if (!response.ok) {
        if (response.status === 403) ui.token = null;
        const detail = result?.error || result?.message || `Request failed (${response.status}).`;
        throw new Error(typeof detail === "string" ? detail : stringify(detail));
      }
      return result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The local studio did not respond in time.");
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function csrf() {
    if (ui.token) return ui.token;
    const result = await fetchJSON("/api/csrf");
    if (typeof result.token !== "string" || !result.token) throw new Error("The studio session could not be established. Reload this page.");
    ui.token = result.token;
    return ui.token;
  }

  async function post(path, payload = {}) {
    const token = await csrf();
    return fetchJSON(path, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": token}, body: JSON.stringify(payload)});
  }

  async function action(key, path, payload, success) {
    if (ui.mutating.has(key)) return null;
    ui.mutating.add(key);
    renderButtons();
    try {
      const result = await post(path, payload);
      if (success) announce(success);
      await refresh();
      return result;
    } catch (error) {
      announce(error.message || "The action could not be completed.", true);
      return null;
    } finally {
      ui.mutating.delete(key);
      renderButtons();
    }
  }

  function connection(online) {
    ui.online = online;
    $("service-notice").hidden = online;
    if (!online) text("service-notice", "The local studio is disconnected. Reconnecting automatically; displayed device information may be out of date.");
    renderConnection();
    renderPreview();
    renderHardware();
    renderButtons();
  }

  function renderConnection() {
    const device = ui.state?.device;
    const simulated = device?.simulated === true || device?.mode === "simulator";
    const connected = ui.online && device?.connected === true;
    const label = !ui.online ? "Studio offline" : simulated ? "Simulator" : connected ? "Device connected" : "Device offline";
    text("connection-label", label);
    $("connection-badge").dataset.status = connected && !simulated ? "connected" : "error";
  }

  function renderButtons() {
    const state = ui.state;
    const running = state?.agent?.running === true;
    $("request-submit").disabled = !ui.online || state?.device?.connected !== true || running || ui.submitting || !$("request").value.trim();
    $("cancel").hidden = !running;
    $("cancel").disabled = !ui.online || ui.mutating.has("cancel");
    $("rollback").disabled = !ui.online || running || !state?.active?.previous || ui.mutating.has("rollback");
    $("pairing-open").disabled = !ui.online || ui.mutating.has("pairing");
    $("pairing-refresh").disabled = !ui.online || ui.mutating.has("pairing");
    $("revoke").disabled = !ui.online || ui.mutating.has("revoke");
    $("wake-toggle").disabled = !ui.online || !state?.device?.connected || ui.mutating.has("wake");
    $("inspect-candidate").disabled = !state?.candidate;
    $("inspect-active").disabled = !state?.active;
  }

  function setPlaceholder(title, detail) {
    text("placeholder-title", title);
    text("placeholder-detail", detail);
  }

  function renderPreview() {
    const state = ui.state;
    const active = state?.active;
    const packageData = active?.package;
    const running = state?.agent?.running === true;
    const kind = active?.kind || packageData?.kind;
    $("preview-placeholder").dataset.mode = kind === "control" ? "volume" : "empty";
    text("preview-title", active?.title || packageData?.title || "A blank canvas");
    text("program-kind", running ? (active ? "PROGRAM PAUSED" : "PROCESSING") : active ? (kind === "control" ? "CONTROL MODE" : kind === "game" ? "GAME RUNNING" : "ACTIVE PROGRAM") : "NO ACTIVE PROGRAM");
    $("program-kind").dataset.status = running ? "busy" : active ? "active" : "idle";
    text("active-revision", active?.revision ? `REV ${String(active.revision).slice(0, 8).toUpperCase()}` : "REV —");
    text("generation-note", running ? (active ? "Your current program is preserved and paused on the Pi while this request is processed." : "The Pi shows progress while the agent creates and checks your program.") : "A new request creates and checks a program before activation.");

    if (!active) {
      ui.previewKey = null;
      ui.previewLoaded = false;
      ui.previewError = false;
      $("preview-image").hidden = true;
      $("preview-image").removeAttribute("src");
      $("preview-placeholder").hidden = false;
      setPlaceholder(running ? "Processing your request" : "Ready for an idea.", running ? "Follow the actual agent stages alongside." : "Your program will appear here.");
      text("preview-origin", "Host preview · awaiting a program");
      $("preview-dot").className = "status-dot";
      return;
    }
    if (kind === "control") {
      ui.previewKey = null;
      ui.previewLoaded = false;
      ui.previewError = false;
      $("preview-image").hidden = true;
      $("preview-image").removeAttribute("src");
      $("preview-placeholder").hidden = false;
      const volume = state.volume;
      const hasVolume = Number.isFinite(volume?.volume) && volume.volume >= 0 && volume.volume <= 100;
      const current = ui.online && state.paired === true && state.device?.connected === true;
      setPlaceholder(hasVolume ? (volume.muted ? "Muted" : `${Math.round(volume.volume)}%`) : "Volume control",
        hasVolume ? `${current ? "This Mac" : "Last reported"} · system volume${volume.muted ? ` ${Math.round(volume.volume)}%` : ""}` : "Awaiting paired Mac volume status.");
      text("preview-origin", current && hasVolume ? (running ? "Host status · controls paused" : "Host status · actual Mac volume") : "Host status · awaiting connection");
      $("preview-dot").className = current && hasVolume ? "status-dot live" : "status-dot";
      return;
    }
    const key = `${active.revision ?? "active"}:${state.preview_version ?? "initial"}`;
    if (ui.previewKey !== key) {
      ui.previewKey = key;
      ui.previewError = false;
      $("preview-image").src = `/api/preview.png?v=${encodeURIComponent(key)}`;
    }
    if (!ui.previewLoaded && !ui.previewError) setPlaceholder("Loading the actual frame…", "Host preview from the running program.");
    const suffix = !ui.online ? " · connection lost" : ui.previewError ? " · frame unavailable" : running ? " · program paused on Pi" : " · actual program output";
    text("preview-origin", `Host preview${suffix}`);
    $("preview-dot").className = ui.online && ui.previewLoaded && !ui.previewError ? "status-dot live" : "status-dot";
  }

  function eventStatus(event) {
    const status = String(event.status || event.type || "").toLowerCase();
    if (/fail|error|reject|cancel/.test(status)) return "error";
    if (/start|running|model_call/.test(status)) return "running";
    return "complete";
  }

  function renderEvents() {
    const events = Array.isArray(ui.state?.events) ? ui.state.events.slice(-50) : [];
    const key = JSON.stringify(events);
    if (key === ui.eventKey) return;
    ui.eventKey = key;
    const fragment = document.createDocumentFragment();
    for (const event of [...events].reverse()) {
      const item = document.createElement("li");
      item.className = "timeline-item";
      item.dataset.status = eventStatus(event);
      const role = ["coder", "artist", "reviewer"].includes(event.role) ? event.role : "orchestrator";
      item.dataset.role = role;
      const marker = document.createElement("span");
      marker.className = "timeline-marker";
      marker.setAttribute("aria-hidden", "true");
      const top = document.createElement("div");
      top.className = "event-topline";
      const roleLabel = document.createElement("span");
      roleLabel.className = "event-role";
      roleLabel.textContent = event.role ? `${human(event.role)}${role !== "orchestrator" ? " · specialist" : ""}` : "Studio";
      const timestamp = document.createElement("time");
      timestamp.className = "event-time";
      timestamp.textContent = timeLabel(event.at);
      const parsedTime = dateValue(event.at);
      if (Number.isFinite(parsedTime)) timestamp.dateTime = new Date(parsedTime).toISOString();
      top.append(roleLabel, timestamp);
      const title = document.createElement("p");
      title.className = "event-title";
      title.textContent = String(event.title || human(event.tool || event.type || "Activity"));
      item.append(marker, top, title);
      if (event.detail !== undefined && event.detail !== null && event.detail !== "") {
        const value = stringify(event.detail).slice(0, 6000);
        if (typeof event.detail === "object" || value.length > 220) {
          const details = document.createElement("details");
          details.className = "event-detail";
          const summary = document.createElement("summary");
          summary.textContent = eventStatus(event) === "error" ? "View error details" : "View result";
          const pre = document.createElement("pre");
          pre.textContent = value;
          details.append(summary, pre);
          item.append(details);
        } else {
          const detail = document.createElement("p");
          detail.className = "event-detail";
          detail.textContent = value;
          item.append(detail);
        }
      }
      fragment.append(item);
    }
    $("timeline").replaceChildren(fragment);
    $("timeline-empty").hidden = events.length > 0;
  }

  function renderAgent() {
    const agent = ui.state?.agent || {};
    const events = Array.isArray(ui.state?.events) ? ui.state.events : [];
    const lifecycle = [...events].reverse().find((event) =>
      ["request_started", "request_finished", "request_failed"].includes(event.type) &&
      (!agent.request_id || event.request_id === agent.request_id));
    const hasTerminalStatus = ["completed", "failed", "cancelled"].includes(agent.status);
    const failed = !agent.running && (hasTerminalStatus ? agent.status === "failed" : lifecycle?.type === "request_failed");
    const cancelled = !agent.running && agent.status === "cancelled";
    $("agent-status").dataset.status = agent.running ? "running" : failed ? "error" : "idle";
    const badge = $("agent-status");
    const statusText = agent.running ? "WORKING" : failed ? "STOPPED" : "READY";
    if (badge.lastChild?.nodeType === Node.TEXT_NODE) badge.lastChild.textContent = statusText;
    const phaseTitles = {queued: "Request accepted", planning: "Planning the change", coding: "Writing the program", checking: "Checking the package",
      previewing: "Preparing the preview", activating: "Activating on your device", ready: "Finishing the request",
      error: "The request encountered an error", cancelled: "Stopping the request"};
    const phaseTitle = typeof agent.title === "string" && agent.title.trim() ? agent.title.slice(0, 200) : phaseTitles[agent.phase];
    const activity = [...events].reverse().find((event) =>
      ["model_call", "tool_started", "tool_finished"].includes(event.type) &&
      (agent.request_id ? event.request_id === agent.request_id : agent.job_id && event.job_id === agent.job_id));
    const hasApiActivity = "role" in agent || "tool" in agent;
    const currentRole = hasApiActivity ? agent.role : activity?.role;
    const currentTool = hasApiActivity ? agent.tool : activity?.tool;
    const role = typeof currentRole === "string" ? human(currentRole) : "";
    const tool = typeof currentTool === "string" ? human(currentTool) : "";
    const step = [role, tool ? `${!hasApiActivity && activity?.type === "tool_finished" ? "Last tool: " : ""}${tool}` : role && ["planning", "coding"].includes(agent.phase) ? "Model is deciding" : ""].filter(Boolean).join(" · ");
    text("agent-summary-title", agent.running ? "Processing your request" : failed ? "The last request stopped." : cancelled ? "The request was cancelled." : ui.state?.active ? "Ready for your next idea." : "An idea starts the process.");
    text("agent-summary-detail", agent.running ? phaseTitle || "Waiting for the agent’s next step." : agent.summary ? String(agent.summary).slice(0, 400) : failed ? "Review the activity below, then adjust your request." : "Follow tool calls, specialist work, and checks as they happen.");
    text("agent-current-step", step);
    $("agent-current-step").hidden = !agent.running || !step;
    text("agent-footnote", agent.running ? "Voice paused · wait for this request or cancel" : "Activity comes from the running agent.");
    renderEvents();
  }

  function controlsFrom(capabilities) {
    if (Array.isArray(capabilities)) return capabilities.filter((value) => typeof value === "string");
    return Array.isArray(capabilities?.controls) ? capabilities.controls.filter((value) => typeof value === "string") : [];
  }

  function renderHardware() {
    const device = ui.state?.device || {};
    const capabilities = device.capabilities || {};
    const controls = controlsFrom(capabilities);
    const input = device.input || {};
    text("device-name", device.name || (device.connected ? "CONNECTED DEVICE" : "NO DEVICE"));
    const fragment = document.createDocumentFragment();
    if (!controls.length) {
      const empty = document.createElement("p");
      empty.className = "muted small";
      empty.textContent = device.connected ? "No verified controls reported yet." : "Connect the device to see its available controls.";
      fragment.append(empty);
    }
    for (const control of controls) {
      const pill = document.createElement("div");
      pill.className = "control-pill";
      pill.dataset.pressed = String(input[control] === true && device.connected === true && ui.online);
      const dot = document.createElement("span");
      dot.className = "status-dot";
      dot.setAttribute("aria-hidden", "true");
      const name = document.createElement("span");
      name.textContent = names[control] || human(control);
      pill.append(dot, name);
      let reading = "";
      if (device.connected && ui.online) {
        if (control === "joystick" && Number.isFinite(input.joystick_x) && Number.isFinite(input.joystick_y)) reading = `${input.joystick_x.toFixed(2)} / ${input.joystick_y.toFixed(2)}`;
        else if (control === "encoder" && Number.isFinite(input.encoder_delta)) reading = `Δ ${input.encoder_delta > 0 ? "+" : ""}${input.encoder_delta}`;
        else if (input[control] === true) reading = "PRESSED";
      }
      if (reading) {
        const value = document.createElement("span");
        value.className = "control-reading";
        value.textContent = reading;
        pill.append(value);
      }
      fragment.append(pill);
    }
    $("control-list").replaceChildren(fragment);
    const warnings = Array.isArray(capabilities.warnings) ? capabilities.warnings : [];
    $("hardware-notes").hidden = warnings.length === 0;
    text("hardware-notes-summary", `${warnings.length} device note${warnings.length === 1 ? "" : "s"}`);
    const list = document.createDocumentFragment();
    warnings.forEach((warning) => { const item = document.createElement("li"); item.textContent = String(warning); list.append(item); });
    $("hardware-warnings").replaceChildren(list);
    $("wake-toggle").setAttribute("aria-checked", String(ui.state?.wake === true));
    const voice = device.telemetry?.voice;
    const voiceLabels = {error: "Microphone error", wake_listening: "Listening", listening: "Recording",
      transcribing: "Transcribing", idle: "Idle", muted: "Wake off"};
    const currentVoice = ui.online && device.connected === true && voice && typeof voice === "object";
    $("wake-detail").dataset.state = currentVoice && voice.state === "error" ? "error" : "normal";
    if (!ui.online || device.connected !== true) text("wake-detail", "Device offline · voice status unavailable");
    else if (currentVoice && typeof voice.state === "string") {
      const label = voiceLabels[voice.state] || human(voice.state);
      const message = typeof voice.message === "string" ? voice.message : "";
      text("wake-detail", message ? `${label} · ${message}` : label);
    } else text("wake-detail", ui.state?.wake ? "On · awaiting device voice status" : "Off · use push-to-talk");
  }

  function renderHost() {
    const paired = ui.state?.paired === true;
    $("paired-chip").hidden = !paired;
    $("pairing-open").hidden = paired;
    $("revoke").hidden = !paired;
    text("pairing-status", paired ? "Device linked · access can be revoked." : "Pair to give your controls a new job.");
    const volume = ui.state?.volume;
    const validVolume = typeof volume?.volume === "number" && Number.isFinite(volume.volume) && volume.volume >= 0 && volume.volume <= 100;
    $("volume-display").hidden = !validVolume;
    if (validVolume) {
      text("volume-value", volume.muted ? `Muted · ${Math.round(volume.volume)}%` : `${Math.round(volume.volume)}%`);
      $("volume-fill").style.width = `${volume.volume}%`;
      $("volume-fill").style.opacity = volume.muted ? ".4" : "1";
      $("volume-meter").setAttribute("aria-valuenow", String(volume.volume));
      $("volume-meter").setAttribute("aria-valuetext", volume.muted ? `Muted, volume ${volume.volume} percent` : `${volume.volume} percent`);
    }
    if (paired && $("pairing-dialog").open) {
      text("pairing-expiry", "Paired successfully. You can close this window.");
      $("pairing-code").hidden = true;
    }
  }

  function renderFooter() {
    const state = ui.state;
    text("provider-label", state?.provider || "Provider unavailable");
    text("model-label", state?.model || "No model configured");
    $("model-label").title = typeof state?.model === "string" ? state.model : "";
    const budget = state?.budget;
    const spent = budget?.charged_or_reserved_dollars;
    const limit = budget?.limit_dollars;
    if (Number.isFinite(spent) && Number.isFinite(limit)) text("budget-label", `$${spent.toFixed(3)} / $${limit.toFixed(2)} reserved or used`);
    else text("budget-label", "Budget unavailable");
    text("last-sync", ui.online ? "Studio connected" : "Studio disconnected");
  }

  function checksFor(source) {
    const item = ui.state?.[source];
    if (item?.report) return item.report;
    if (item?.checks) return item.checks;
    const events = Array.isArray(ui.state?.events) ? [...ui.state.events].reverse() : [];
    const found = events.find((event) => event.tool === "test_package" && event.detail && typeof event.detail === "object" && (!item?.revision || event.detail.candidate_id === item.revision));
    return found?.detail || {status: "No verification report available for this package yet.", note: "The activity timeline contains the recorded tool results."};
  }

  function renderInspector() {
    if (!$("inspect-dialog").open) return;
    const item = ui.state?.[ui.inspectSource];
    const packageData = item?.package;
    $("inspect-active").classList.toggle("selected", ui.inspectSource === "active");
    $("inspect-candidate").classList.toggle("selected", ui.inspectSource === "candidate");
    $("inspect-active").setAttribute("aria-pressed", String(ui.inspectSource === "active"));
    $("inspect-candidate").setAttribute("aria-pressed", String(ui.inspectSource === "candidate"));
    text("inspect-meta", packageData ? `${packageData.title || item.title || "Program"} · ${human(packageData.kind || item.kind || "package")} · ${item.revision || "Unactivated candidate"}` : "No package to inspect.");
    let content = "No program yet. Create an experience to inspect its source.";
    let language = "JAVASCRIPT";
    if (ui.inspectView === "code" && packageData) {
      content = typeof packageData.code === "string" ? packageData.code : stringify(packageData);
      language = typeof packageData.code === "string" ? "JAVASCRIPT · READ ONLY" : "DECLARATIVE PACKAGE · READ ONLY";
    } else if (ui.inspectView === "assets") {
      content = packageData?.assets ? stringify(packageData.assets) : "No sprite assets in this package.";
      language = "GENERATED ASSETS · JSON";
    } else if (ui.inspectView === "checks") {
      content = stringify(checksFor(ui.inspectSource));
      language = "RECORDED VERIFICATION · JSON";
    }
    text("source-code", content);
    text("code-language", language);
    $("copy-code").disabled = !packageData;
    document.querySelectorAll("[data-view]").forEach((button) => {
      const selected = button.dataset.view === ui.inspectView;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    $("inspect-content").setAttribute("aria-labelledby", `tab-${ui.inspectView}`);
  }

  function render() {
    renderConnection(); renderPreview(); renderAgent(); renderHardware(); renderHost(); renderFooter(); renderButtons(); renderInspector();
  }

  let refreshing = null;
  async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        const state = await fetchJSON("/api/state");
        if (!state || typeof state !== "object" || Array.isArray(state)) throw new Error("Invalid studio state.");
        ui.state = state;
        connection(true);
        render();
      } catch (_) { connection(false); renderFooter(); }
      finally { refreshing = null; }
    })();
    return refreshing;
  }

  async function poll() {
    await refresh();
    setTimeout(poll, 750);
  }

  function pairingCountdown() {
    if (!ui.pairing || !$("pairing-dialog").open || ui.state?.paired) return;
    const expires = dateValue(ui.pairing.expires_at);
    if (!Number.isFinite(expires)) {
      text("pairing-expiry", "One-time code. Confirm on the device with screen button A.");
      return;
    }
    const seconds = Math.max(0, Math.ceil((expires - Date.now()) / 1000));
    text("pairing-expiry", seconds ? `Expires in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` : "This code has expired. Create a new one below.");
    if (!seconds) text("pairing-code", "EXPIRED");
  }

  async function createPairing() {
    if (ui.mutating.has("pairing")) return;
    if (!$("pairing-dialog").open) $("pairing-dialog").showModal();
    ui.pairing = null;
    $("pairing-code").hidden = false;
    text("pairing-code", "······");
    text("pairing-expiry", "Creating a one-time code…");
    $("pairing-host").hidden = true;
    const result = await action("pairing", "/api/pairing", {});
    if (!result || typeof result.code !== "string") {
      text("pairing-code", "—");
      text("pairing-expiry", "Could not create a code. Close this window for error details.");
      return;
    }
    ui.pairing = result;
    text("pairing-code", result.code);
    if (typeof result.host_url === "string") {
      text("pairing-host-url", result.host_url);
      $("pairing-host").hidden = false;
    }
    pairingCountdown();
  }

  $("request").addEventListener("input", renderButtons);
  $("request").addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!$("request-submit").disabled) $("request-form").requestSubmit();
    }
  });
  $("request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const request = $("request").value.trim();
    if (!request || !ui.online || ui.state?.device?.connected !== true || ui.submitting || ui.state?.agent?.running) return;
    ui.submitting = true;
    renderButtons();
    try {
      await post("/api/request", {text: request});
      announce("Request sent. Follow the agent’s work in the timeline.");
      if ($("request").value.trim() === request) $("request").value = "";
      await refresh();
    } catch (error) { announce(error.message || "The request could not be sent.", true); }
    finally { ui.submitting = false; renderButtons(); }
  });
  document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
    $("request").value = button.dataset.example;
    $("request").focus();
    renderButtons();
  }));
  $("voice-help").addEventListener("click", () => {
    const expanded = $("voice-help").getAttribute("aria-expanded") !== "true";
    $("voice-help").setAttribute("aria-expanded", String(expanded));
    $("voice-instructions").hidden = !expanded;
  });
  $("cancel").addEventListener("click", () => action("cancel", "/api/cancel", {}, "Cancellation requested. The current program stays available."));
  $("rollback").addEventListener("click", () => action("rollback", "/api/rollback", {}, "Previous version restored."));
  $("revoke").addEventListener("click", () => action("revoke", "/api/revoke", {}, "Device access revoked."));
  $("wake-toggle").addEventListener("click", () => action("wake", "/api/wake", {enabled: ui.state?.wake !== true}));
  $("pairing-open").addEventListener("click", createPairing);
  $("pairing-refresh").addEventListener("click", createPairing);

  $("inspect-open").addEventListener("click", () => {
    ui.inspectSource = ui.state?.candidate ? "candidate" : "active";
    $("inspect-dialog").showModal();
    renderInspector();
  });
  ["active", "candidate"].forEach((source) => $("inspect-" + source).addEventListener("click", () => { ui.inspectSource = source; renderInspector(); }));
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => { ui.inspectView = button.dataset.view; renderInspector(); });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const views = ["code", "assets", "checks"];
      const current = views.indexOf(ui.inspectView);
      const index = event.key === "Home" ? 0 : event.key === "End" ? 2 : (current + (event.key === "ArrowRight" ? 1 : 2)) % 3;
      ui.inspectView = views[index]; renderInspector(); $("tab-" + ui.inspectView).focus();
    });
  });
  $("copy-code").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("source-code").textContent);
      text("copy-code", "Copied");
      setTimeout(() => text("copy-code", "Copy"), 1700);
    } catch (_) { text("copy-code", "Select text to copy"); }
  });
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
  ["inspect-dialog", "pairing-dialog"].forEach((id) => $(id).addEventListener("click", (event) => {
    if (event.target !== $(id)) return;
    const rect = $(id).getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $(id).close();
  }));
  $("preview-image").addEventListener("load", () => {
    if (!ui.state?.active || (ui.state.active.kind || ui.state.active.package?.kind) === "control") return;
    ui.previewLoaded = true; ui.previewError = false;
    $("preview-image").hidden = false; $("preview-placeholder").hidden = true;
    renderPreview();
  });
  $("preview-image").addEventListener("error", () => {
    if (!ui.state?.active || (ui.state.active.kind || ui.state.active.package?.kind) === "control") return;
    ui.previewLoaded = false; ui.previewError = true;
    $("preview-image").hidden = true; $("preview-placeholder").hidden = false;
    setPlaceholder("Frame unavailable.", "The active program’s preview could not be loaded.");
    renderPreview();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  setInterval(pairingCountdown, 1000);
  renderButtons();
  poll();
})();
