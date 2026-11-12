/* Forge Installer UI. No disk-write endpoints exist in this application. */
"use strict";
const token = new URLSearchParams(location.search).get("token") || "";
const sections = ["welcome", "hardware", "storage", "configure", "review"];
let step = 0;
let inventory = null;
let selected = null;
let draftRevision = 0;
function invalidateDraft() {
  draftRevision += 1;
  $("validated-config").replaceChildren();
  $("summary").replaceChildren();
}

const $ = (id) => document.getElementById(id);

function element(tag, className, content) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (content !== undefined) e.textContent = String(content);
  return e;
}
function show(index) {
  step = index;
  sections.forEach((name, i) => $(name).classList.toggle("active", index === i));
  document.querySelectorAll(".step").forEach((s, i) => {
    s.classList.toggle("active", index === i);
    s.classList.toggle("done", i < index);
    if (i === index) s.setAttribute("aria-current", "step");
    else s.removeAttribute("aria-current");
  });
  const heading = $(sections[index]).querySelector("h1,h2");
  if (heading) heading.setAttribute("tabindex", "-1"), heading.focus({preventScroll: true});
}
async function getJSON(path) {
  const response = await fetch(path, {
    headers: {"X-Forge-Token": token},
    cache: "no-store",
    credentials: "omit"
  });
  if (!response.ok) throw new Error("Could not read hardware information (" + response.status + ")");
  return response.json();
}
function gib(bytes) { return (Number(bytes || 0) / (1024 ** 3)).toFixed(1) + " GiB"; }
function card(label, value, passed) {
  const box = element("div", "hardware-card" + (passed ? "" : " fail"));
  box.append(element("div", "hint", label), element("div", "value", value),
             element("div", "test", passed ? "✓ PASSED" : "✕ REQUIREMENT NOT MET"));
  return box;
}
async function loadHardware() {
  $("hardware-grid").replaceChildren(element("p", "", "Checking system hardware…"));
  $("hardware-alert").classList.add("hidden");
  $("to-storage").disabled = true;
  try {
    inventory = await getJSON("/api/inventory");
    const system = inventory.system;
    const list = $("hardware-grid");
    list.replaceChildren(
      card("ARCHITECTURE", system.architecture, system.architecture_supported),
      card("BOOT METHOD", system.uefi ? "UEFI" : "Legacy / unknown", system.uefi),
      card("SYSTEM MEMORY", gib(system.memory_bytes), system.sufficient_memory));
    const blockers = [];
    if (!system.architecture_supported) blockers.push("x86_64 Linux is required.");
    if (!system.uefi) blockers.push("UEFI boot is required.");
    if (!system.sufficient_memory) blockers.push("At least 4 GiB of memory is required.");
    if (blockers.length) {
      const alert = $("hardware-alert");
      alert.replaceChildren(element("span", "", "⚠"), element("div", "", blockers.join(" ")));
      alert.classList.remove("hidden");
    }
    $("to-storage").disabled = false;
    renderDisks();
  } catch (error) {
    const alert = $("hardware-alert");
    alert.replaceChildren(element("span", "", "⚠"), element("div", "", error.message));
    alert.classList.remove("hidden");
    $("hardware-grid").replaceChildren();
  }
}
function renderDisks() {
  selected = null;
  invalidateDraft();
  $("to-config").disabled = true;
  const list = $("disks");
  list.replaceChildren();
  list.setAttribute("aria-label", "Eligible installation disks (preview only)");
  const disks = inventory?.disks || [];
  $("disk-empty").classList.toggle("hidden", disks.length !== 0);
  disks.forEach((disk) => {
    const button = element("button", "disk-option" + (disk.eligible ? "" : " blocked"));
    button.type = "button";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", "false");
    button.disabled = !disk.eligible || !disk.by_id;
    button.tabIndex = button.disabled ? -1 : (list.querySelector(".disk-option:not(:disabled)") ? -1 : 0);
    button.append(element("span", "disk-radio"));
    const info = element("span", "disk-info");
    info.append(element("strong", "", disk.model || disk.path),
                element("small", "", disk.path + " · " + gib(disk.size) + " · " + disk.transport),
                element("small", "", disk.by_id || "No stable device identifier"));
    if (disk.reasons?.length) info.append(element("div", "reason", disk.reasons.join(" · ")));
    button.append(info, element("span", "disk-state", disk.eligible ? "CANDIDATE" : "BLOCKED"));
    button.addEventListener("click", () => {
      if (selected !== disk.by_id) invalidateDraft();
      selected = disk.by_id;
      list.querySelectorAll(".disk-option").forEach((option) => {
        option.setAttribute("aria-checked", String(option === button));
        option.tabIndex = option === button ? 0 : -1;
      });
      $("to-config").disabled = false;
    });
    list.append(button);
  });
  // Standard radio-group navigation: keyboard selection never triggers writes.
  list.onkeydown = (event) => {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const enabled = [...list.querySelectorAll(".disk-option:not(:disabled)")];
    if (!enabled.length) return;
    event.preventDefault();
    const current = enabled.indexOf(document.activeElement);
    let next;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = enabled.length - 1;
    else if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (current + 1) % enabled.length;
    else next = (current + enabled.length - 1) % enabled.length;
    enabled[next].focus();
    enabled[next].click();
  };
}
async function validateConfiguration() {
  const requestedId = selected;
  const revision = draftRevision;
  const alert = $("config-alert");
  const button = $("validate-config");
  alert.classList.add("hidden");
  button.disabled = true;
  try {
    if (!requestedId) throw new Error("Select a disk before configuration.");
    const draft = {
      hostname: $("hostname").value,
      username: $("username").value,
      disk_by_id: requestedId
    };
    const response = await fetch("/api/config/validate", {
      method: "POST",
      headers: {"X-Forge-Token": token, "Content-Type": "application/json"},
      cache: "no-store",
      credentials: "omit",
      body: JSON.stringify(draft)
    });
    if (!response.ok) throw new Error("Configuration validation unavailable (" + response.status + ")");
    const result = await response.json();
    if (selected !== requestedId || step !== 3 || draftRevision !== revision) return;
    if (result.valid !== true || result.mode !== "dry-run-only" ||
        result.write_operations_enabled !== false || !Array.isArray(result.errors) ||
        result.errors.length !== 0) {
      const errors = Array.isArray(result.errors) ? result.errors.join(" · ") : "Unexpected response";
      throw new Error(errors || "Configuration draft was refused.");
    }
    const details = $("validated-config");
    details.replaceChildren(
      element("strong", "", "VALIDATED DRAFT — NOT AN INSTALLATION"),
      element("p", "", "Hostname: " + draft.hostname),
      element("p", "", "Username: " + draft.username),
      element("p", "", "Disk identifier: " + draft.disk_by_id)
    );
    show(4);
    renderReview();
  } catch (error) {
    if (step === 3 && draftRevision === revision) {
      alert.replaceChildren(element("span", "", "⚠"), element("div", "", error.message));
      alert.classList.remove("hidden");
    }
  } finally {
    button.disabled = false;
  }
}
async function renderReview() {
  const summary = $("summary");
  const revision = draftRevision;
  summary.replaceChildren(element("p", "", "Rechecking selected disk…"));
  try {
    if (!selected) throw new Error("No disk selected; return to Storage.");
    const requestedId = selected;
    const plan = await getJSON("/api/preview?id=" + encodeURIComponent(requestedId));
    // This endpoint reports server-owned capabilities, not draft readiness.
    // Even a validated preview must never become an executable permission.
    const capability = await getJSON("/api/capabilities");
    // A stale asynchronous response must not replace a newer disk selection.
    if (selected !== requestedId || step !== 4 || draftRevision !== revision || !$("validated-config").hasChildNodes()) return;
    if (capability.version !== "eduardos.forge.capabilities.v1" ||
        capability.mode !== "dry-run-only" ||
        capability.installation_available !== false ||
        capability.physical_disk_writes_enabled !== false ||
        capability.credential_collection_enabled !== false ||
        capability.privileged_executor_connected !== false ||
        capability.automatic_retry_enabled !== false ||
        !Array.isArray(capability.required_gates)) {
      throw new Error("Unexpected installation capability response; review is blocked.");
    }
    const box = element("div", "summary");
    box.append(element("h3", "", "PROPOSED STORAGE PLAN"));
    const disk = plan.selected_disk;
    box.append(element("div", "target", disk ? disk.model : "Unavailable"),
               element("div", "meta", disk ? disk.by_id + " · " + gib(disk.size) : "Selected device missing"));
    (plan.planned_layout || []).forEach((text, i) => {
      const row = element("div", "layout-item");
      row.append(element("span", "marker", String(i + 1).padStart(2, "0")), element("span", "", text));
      box.append(row);
    });
    const safePreview = plan.mode === "dry-run-only" && plan.would_write_to_disk === false;
    const sameDisk = disk && disk.by_id === requestedId;
    const ready = safePreview && sameDisk && plan.status === "ready-for-review" &&
      Array.isArray(plan.blockers) && plan.blockers.length === 0;
    if (ready) box.append(element("p", "ready-text", "✓ READY FOR REVIEW — NOT AN INSTALLATION"));
    else {
      const reasons = Array.isArray(plan.blockers) ? plan.blockers.filter(x => typeof x === "string") : [];
      box.append(element("p", "blocked-text", "BLOCKED: " + (reasons.length ? reasons.join(" · ") :
        "Preview is inconsistent or the selected disk changed. Return to Storage and inspect again.")));
    }
    const blockedInstall = element("p", "blocked-text",
      "INSTALLATION NOT YET AVAILABLE — This validated preview cannot erase or install. " +
      "Independent authorization, durable recovery, sealed credentials and QEMU GUI integration are still required.");
    box.append(blockedInstall);
    summary.replaceChildren(box);
    // Lab mode is *never* exposed by the production Forge preview server.
    // The separate root-operator QEMU launcher alone supplies this endpoint.
    if (ready) showDisposableLabControls(summary, requestedId, revision);
  } catch (error) {
    if (step !== 4 || draftRevision !== revision || !$("validated-config").hasChildNodes()) return;
    summary.replaceChildren(element("p", "blocked-text", error.message));
  }
}
// Only fixed disposable-QEMU lab sessions can expose this user-facing trigger.
// No password or LUKS passphrase is ever collected by the HTTP frontend.
// All real installation authority remains independently held by root.
async function postLab(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"X-Forge-Token": token, "Content-Type": "application/json"},
    cache: "no-store",
    credentials: "omit",
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error("QEMU lab action refused (" + response.status + ")");
  return response.json();
}

async function showDisposableLabControls(summary, diskId, revision) {
  let initial;
  try {
    initial = await getJSON("/api/lab/status");
  } catch (_) {
    return; // Normal production GUI: no lab interface exists.
  }
  if (step !== 4 || draftRevision !== revision || selected !== diskId) return;
  if (initial.version !== "eduardos.forge.qemu-gui-install.v1" ||
      initial.lab_only !== true ||
      initial.physical_hardware_supported !== false ||
      initial.authorization_to_write !== false ||
      initial.automatic_retry_enabled !== false ||
      diskId !== "/dev/disk/by-id/virtio-root" ||
      $("username").value !== "testpilot" ||
      $("hostname").value !== "edos-installed-lab") return;

  // The generic read-only notice applies to the production UI, not this
  // independently authorized disposable-QEMU session.
  const previewOnlyNotice = summary.querySelector(".blocked-text");
  if (previewOnlyNotice) previewOnlyNotice.remove();
  const panel = element("div", "summary");
  panel.append(element("h3", "", "DISPOSABLE QEMU INSTALLATION LAB"),
               element("p", "", "A trusted local root operator pre-authorized this VM session. " +
                 "Only the throwaway /dev/vda target is supported. " +
                 "Public test credentials are held outside the browser."));
  const status = element("p", "ready-text", "State: " + initial.status);
  const progress = element("div", "lab-progress");
  panel.append(status, progress);
  const action = element("button", "primary", "Install disposable VM");
  const cancel = element("button", "secondary", "Stop lab installation");
  action.type = cancel.type = "button";
  action.disabled = initial.status !== "awaiting-lab-trigger";
  cancel.disabled = initial.status !== "running";
  panel.append(action, cancel);
  summary.append(panel);

  let last = "";
  const render = (data) => {
    if (step !== 4 || draftRevision !== revision || selected !== diskId) return false;
    if (data.version !== "eduardos.forge.qemu-gui-install.v1" ||
        data.lab_only !== true || data.authorization_to_write !== false ||
        data.automatic_retry_enabled !== false || !Array.isArray(data.phases)) {
      status.textContent = "Invalid lab progress evidence";
      return false;
    }
    status.textContent = "State: " + data.status;
    const lines = data.phases.join("\n");
    if (lines !== last) {
      last = lines;
      progress.replaceChildren(...data.phases.map((phase, i) =>
        element("p", "layout-item", String(i + 1) + ". " + phase)));
    }
    action.disabled = true;
    cancel.disabled = data.status !== "running";
    return ["running", "preflight"].includes(data.status);
  };
  action.addEventListener("click", async () => {
    action.disabled = true;
    if (!window.confirm("ERASE DISPOSABLE /dev/vda — TEST VM ONLY. Continue?")) {
      action.disabled = false;
      return;
    }
    try {
      const result = await postLab("/api/lab/start", {
        operation: "start-disposable-qemu-install",
        confirmation: "ERASE DISPOSABLE /dev/vda",
        disk_by_id: diskId,
        username: "testpilot",
        hostname: "edos-installed-lab"
      });
      render(result);
      const poll = async () => {
        if (step !== 4 || draftRevision !== revision || selected !== diskId) return;
        try {
          if (render(await getJSON("/api/lab/status")))
            window.setTimeout(poll, 900);
        } catch (_) {
          status.textContent = "Cannot verify installation status; inspect VM manually.";
        }
      };
      window.setTimeout(poll, 900);
    } catch (error) {
      status.textContent = error.message;
    }
  });
  cancel.addEventListener("click", async () => {
    cancel.disabled = true;
    try {
      render(await postLab("/api/lab/cancel", {
        operation: "cancel-disposable-qemu-install"
      }));
    } catch (_) {
      status.textContent = "Cancellation state unknown; inspect VM manually.";
    }
  });
}

$("start").addEventListener("click", () => { show(1); loadHardware(); });
$("to-storage").addEventListener("click", () => show(2));
$("to-config").addEventListener("click", () => show(3));
$("validate-config").addEventListener("click", validateConfiguration);
$("restart").addEventListener("click", () => { selected = null; invalidateDraft(); show(0); });
["hostname", "username"].forEach(id => $(id).addEventListener("input", invalidateDraft));
document.querySelectorAll("[data-back]").forEach((b) =>
  b.addEventListener("click", () => {
    // Returning to configuration or storage invalidates any prior review.
    if (step >= 3) invalidateDraft();
    show(Math.max(0, step - 1));
  }));
