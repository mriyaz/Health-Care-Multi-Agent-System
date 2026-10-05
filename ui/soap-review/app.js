/**
 * SOAP Note Review — wires transcript → Documentation Agent → clinician approval → FHIR.
 */

const H = window.HealthOS;

const SOAP_KEYS = ["subjective", "objective", "assessment", "plan"];

let currentTaskId = null;
let currentNoteId = null;
let originalSoap = {};
let encounterTranscripts = new Map();
let pollTimer = null;
let pollStartedAt = 0;
const STALE_QUEUED_MS = 45_000;

function onAuthenticated() {
  H.$("auth-status").textContent = "Signed in";
  H.hide(H.$("login-panel"));
  H.show(H.$("intake-panel"));
  H.$("transcript").value = "";
  H.$("encounter-select").value = "";
  loadEncounters();
}

async function loadEncounters() {
  const select = H.$("encounter-select");
  const prev = select.value;
  encounterTranscripts = new Map();
  try {
    const rows = await H.apiFetch("/ui/encounters");
    select.innerHTML = '<option value="">— Select encounter —</option>';
    for (const row of rows) {
      const opt = document.createElement("option");
      opt.value = row.encounter_id;
      const fhir = row.fhir_encounter_id ? ` · ${row.fhir_encounter_id}` : "";
      opt.textContent = `${row.patient_name} (${row.status})${fhir}`;
      if (row.demo_transcript) {
        encounterTranscripts.set(row.encounter_id, row.demo_transcript);
      }
      select.appendChild(opt);
    }
    if (prev) select.value = prev;
    onEncounterSelected();
  } catch (err) {
    H.setError(H.$("intake-error"), err.message);
  }
}

function onEncounterSelected() {
  const encounterId = H.$("encounter-select").value;
  const transcript = encounterTranscripts.get(encounterId) || "";
  H.$("transcript").value = transcript;
  H.$("transcript").placeholder = encounterId
    ? "Demo transcript loaded — edit or replace before generating"
    : "Select an encounter to load a demo transcript, or paste your own…";
}

async function bootstrapDemo() {
  H.setError(H.$("intake-error"), null);
  H.$("bootstrap-btn").disabled = true;
  try {
    const data = await H.apiFetch("/ui/demo/bootstrap", { method: "POST" });
    await loadEncounters();
    if (!data.synced?.length) {
      H.setError(H.$("intake-error"), "No demo encounters were synced.");
    }
  } catch (err) {
    H.setError(H.$("intake-error"), err.message);
  } finally {
    H.$("bootstrap-btn").disabled = false;
  }
}

async function submitDocumentTask() {
  H.setError(H.$("intake-error"), null);
  H.hide(H.$("review-panel"));
  H.setError(H.$("review-error"), null);
  H.hide(H.$("approval-result"));

  const encounterId = H.$("encounter-select").value;
  const transcript = H.$("transcript").value.trim();
  if (!encounterId) {
    H.setError(H.$("intake-error"), "Select an encounter first.");
    return;
  }
  if (!transcript) {
    H.setError(H.$("intake-error"), "Paste a transcript before generating.");
    return;
  }

  H.$("generate-btn").disabled = true;
  H.show(H.$("task-status"));
  H.$("status-label").textContent = "Submitting to Documentation Agent…";
  H.hide(H.$("confidence-badge"));

  const form = new FormData();
  form.set("encounter_id", encounterId);
  form.set("transcript", transcript);
  form.set("note_kind", "soap");

  try {
    const created = await H.apiFetch("/tasks/document", { method: "POST", body: form });
    currentTaskId = created.task_id;
    pollTaskStatus();
  } catch (err) {
    H.setError(H.$("intake-error"), err.message);
    H.hide(H.$("task-status"));
    H.$("generate-btn").disabled = false;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollTaskStatus() {
  stopPolling();
  pollStartedAt = Date.now();
  const tick = async () => {
    try {
      const task = await H.apiFetch(`/tasks/${currentTaskId}/status`);
      updateTaskStatusUI(task);

      if (
        task.status === "QUEUED" &&
        Date.now() - pollStartedAt > STALE_QUEUED_MS
      ) {
        stopPolling();
        H.$("generate-btn").disabled = false;
        H.setError(
          H.$("intake-error"),
          "Task is still queued — the server may have failed to start the agent. " +
            "Restart the API and try again. If using Windows, ensure the API was restarted after the latest update."
        );
        H.hide(H.$("task-status"));
        return;
      }

      if (task.hitl_pending) {
        H.$("status-label").textContent =
          "Low confidence — resuming HITL gate…";
        await H.apiFetch(`/tasks/${currentTaskId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, notes: "Auto-resumed from SOAP review UI" }),
        });
        return;
      }

      const terminal = ["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.status);
      if (terminal) {
        stopPolling();
        H.$("generate-btn").disabled = false;
        if (task.status === "SUCCEEDED") {
          showSoapReview(task);
        } else {
          const docErr = task.agent_outputs?.documentation?.error;
          H.setError(
            H.$("intake-error"),
            task.error_message ||
              docErr ||
              `Task ended with status ${task.status}`
          );
          H.hide(H.$("task-status"));
        }
      }
    } catch (err) {
      stopPolling();
      H.$("generate-btn").disabled = false;
      H.setError(H.$("intake-error"), err.message);
      H.hide(H.$("task-status"));
    }
  };
  await tick();
  pollTimer = setInterval(tick, 2000);
}

function updateTaskStatusUI(task) {
  H.show(H.$("task-status"));
  const conf = task.confidence_scores?.documentation;
  let label = `Task ${task.status}`;
  if (task.status === "QUEUED") {
    label = "Queued — starting Documentation Agent…";
  } else if (task.status === "RUNNING") {
    label = "Documentation Agent is generating the SOAP note…";
  } else if (task.hitl_pending) {
    label = "Awaiting human-in-the-loop approval…";
  } else if (task.status === "SUCCEEDED") {
    label = "SOAP note ready for review";
  }
  H.$("status-label").textContent = label;

  const badge = H.$("confidence-badge");
  if (conf != null) {
    badge.textContent = `Confidence ${(conf * 100).toFixed(0)}%`;
    H.show(badge);
  } else {
    H.hide(badge);
  }
}

function showSoapReview(task) {
  const doc = task.agent_outputs?.documentation;
  if (!doc || doc.error) {
    H.setError(H.$("intake-error"), doc?.error || "No documentation output on task.");
    return;
  }
  if (!doc.soap || !doc.note_id) {
    H.setError(H.$("intake-error"), "Task succeeded but note payload is missing.");
    return;
  }

  currentNoteId = doc.note_id;
  originalSoap = { ...doc.soap };
  for (const key of SOAP_KEYS) {
    const el = H.$(`soap-${key}`);
    el.value = doc.soap[key] || "";
    markEdited(key);
  }

  const meta = task.model_versions?.documentation || {};
  const chips = H.$("meta-chips");
  chips.innerHTML = "";
  const addChip = (text) => {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = text;
    chips.appendChild(span);
  };
  if (meta.model_used) addChip(`Model: ${meta.model_used}`);
  if (meta.latency_ms != null) addChip(`Latency: ${meta.latency_ms} ms`);
  if (meta.sections_flagged?.length) {
    addChip(`Flagged: ${meta.sections_flagged.join(", ")}`);
  }

  H.show(H.$("review-panel"));
  H.$("review-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function markEdited(key) {
  const field = document.querySelector(`.soap-field[data-key="${key}"]`);
  const ta = H.$(`soap-${key}`);
  const changed = (ta.value || "") !== (originalSoap[key] || "");
  field.classList.toggle("edited", changed);
  field.querySelector(".edited-tag").classList.toggle("hidden", !changed);
}

function collectEditedSoap() {
  const edited = {};
  for (const key of SOAP_KEYS) {
    const val = H.$(`soap-${key}`).value;
    if (val !== (originalSoap[key] || "")) {
      edited[key] = val;
    }
  }
  return Object.keys(edited).length ? edited : null;
}

async function approveNote() {
  H.setError(H.$("review-error"), null);
  H.hide(H.$("approval-result"));
  H.$("approve-btn").disabled = true;

  try {
    const body = {
      approved: true,
      edited_soap: collectEditedSoap(),
    };
    const result = await H.apiFetch(`/notes/${currentNoteId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const banner = H.$("approval-result");
    banner.classList.remove("success", "warn");
    if (result.fhir_documentreference_id) {
      banner.classList.add("success");
      banner.innerHTML =
        `<strong>Approved and written to FHIR.</strong><br>` +
        `DocumentReference ID: <code>${result.fhir_documentreference_id}</code>`;
    } else {
      banner.classList.add("warn");
      banner.innerHTML =
        `<strong>Note approved locally.</strong> ` +
        (result.fhir_warning || "FHIR write-back did not return a resource ID.");
    }
    H.show(banner);
    H.$("approve-btn").disabled = true;
    H.$("reject-btn").disabled = true;
  } catch (err) {
    H.setError(H.$("review-error"), err.message);
    H.$("approve-btn").disabled = false;
  }
}

async function rejectNote() {
  if (!confirm("Reject this note? It will not be written to FHIR.")) return;
  H.setError(H.$("review-error"), null);
  H.$("reject-btn").disabled = true;

  try {
    await H.apiFetch(`/notes/${currentNoteId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: false, reviewer_notes: "Rejected from SOAP review UI" }),
    });
    const banner = H.$("approval-result");
    banner.className = "result-banner warn";
    banner.textContent = "Note rejected. Task marked failed; no FHIR write-back.";
    H.show(banner);
    H.$("approve-btn").disabled = true;
  } catch (err) {
    H.setError(H.$("review-error"), err.message);
    H.$("reject-btn").disabled = false;
  }
}

H.renderNav("soap");
H.wireLoginForm({ onSuccess: onAuthenticated });
H.$("bootstrap-btn").addEventListener("click", bootstrapDemo);
H.$("encounter-select").addEventListener("change", onEncounterSelected);
H.$("generate-btn").addEventListener("click", submitDocumentTask);
H.$("approve-btn").addEventListener("click", approveNote);
H.$("reject-btn").addEventListener("click", rejectNote);

for (const key of SOAP_KEYS) {
  H.$(`soap-${key}`).addEventListener("input", () => markEdited(key));
}

H.requireAuth(onAuthenticated);
