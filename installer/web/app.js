/* Forge Installer UI. No disk-write endpoints exist in this application. */
"use strict";
const token = new URLSearchParams(location.search).get("token") || "";
const sections = ["welcome", "hardware", "storage", "configure", "review"];
let step = 0;
let inventory = null;
let selected = null;
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
    if (selected !== requestedId || step !== 3) return;
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
    if (step === 3) {
      alert.replaceChildren(element("span", "", "⚠"), element("div", "", error.message));
      alert.classList.remove("hidden");
    }
  } finally {
    button.disabled = false;
  }
}
async function renderReview() {
  const summary = $("summary");
  summary.replaceChildren(element("p", "", "Rechecking selected disk…"));
  try {
    if (!selected) throw new Error("No disk selected; return to Storage.");
    const requestedId = selected;
    const plan = await getJSON("/api/preview?id=" + encodeURIComponent(requestedId));
    // A stale asynchronous response must not replace a newer disk selection.
    if (selected !== requestedId || step !== 4) return;
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
    summary.replaceChildren(box);
  } catch (error) {
    if (step !== 4) return;
    summary.replaceChildren(element("p", "blocked-text", error.message));
  }
}
$("start").addEventListener("click", () => { show(1); loadHardware(); });
$("to-storage").addEventListener("click", () => show(2));
$("to-config").addEventListener("click", () => show(3));
$("validate-config").addEventListener("click", validateConfiguration);
$("restart").addEventListener("click", () => { selected = null; $("validated-config").replaceChildren(); show(0); });
document.querySelectorAll("[data-back]").forEach((b) =>
  b.addEventListener("click", () => show(Math.max(0, step - 1))));
