const H = window.HealthOS;

let currentTaskId = null;
let pollTimer = null;
const encounterTranscripts = new Map();

function renderShap(containerId, shapData) {
  const el = H.$(containerId);
  const phrases = shapData?.phrases || [];
  if (!phrases.length) {
    el.innerHTML = "<p class='hint'>No attributions</p>";
    return;
  }
  el.innerHTML = phrases
    .slice(0, 6)
    .map((p) => {
      const pct = Math.round((p.shap_value || 0) * 100);
      return `<div class="shap-bar">
        <span style="width:40%">${(p.phrase || "").slice(0, 40)}</span>
        <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
        <span>${pct}%</span>
      </div>`;
    })
    .join("");
}

function renderCodeList(containerId, items) {
  const el = H.$(containerId);
  if (!items?.length) {
    el.innerHTML = "<p class='hint'>None</p>";
    return;
  }
  el.innerHTML = items
    .map(
      (c, i) =>
        `<div class="chip" style="display:block;margin:0.25rem 0;padding:0.4rem 0.6rem">
          <strong>${i + 1}. ${c.code}</strong> — ${c.description || ""}
          <span class="badge">${((c.confidence || 0) * 100).toFixed(0)}%</span>
          ${(c.risk_flags || []).map((f) => `<span class="badge blocked">${f}</span>`).join(" ")}
        </div>`
    )
    .join("");
}

function showReport(task) {
  const report = task.agent_outputs?.rcm_audit_report;
  if (!report) {
    H.setError(H.$("intake-error"), "No RCM report on task");
    return;
  }
  currentTaskId = task.task_id;

  renderCodeList("icd-list", report.icd10_suggestions);
  renderCodeList("cpt-list", report.cpt_suggestions);
  renderShap("shap-icd", report.shap_explanations?.icd10_primary);
  renderShap("shap-cpt", report.shap_explanations?.cpt_primary);

  const val = report.validation || {};
  H.$("validation-result").innerHTML = `
    <span class="badge ${val.validation_ok ? "ok" : "blocked"}">${val.validation_ok ? "PASS" : "FLAGS"}</span>
    ${(val.flags || []).map((f) => `<span class="chip">${f}</span>`).join(" ")}
    <ul>${(val.reasons || []).map((r) => `<li>${r.reason_code || r}: ${r.message || ""}</li>`).join("")}</ul>`;

  const pb = report.prebill_audit || {};
  H.$("prebill-result").innerHTML = `Pre-bill score: <strong>${((pb.score_ratio || 0) * 100).toFixed(0)}%</strong> · ${pb.passed_count || 0}/${pb.total_checkpoints || 12} checkpoints`;

  const risk = report.denial_risk?.risk_score ?? 0;
  const badge = H.$("risk-badge");
  badge.textContent = `Denial risk ${(risk * 100).toFixed(0)}%`;
  badge.className = `badge ${risk > 0.55 ? "blocked" : "ok"}`;

  if (report.icd10_suggestions?.[0]) H.$("override-icd").placeholder = report.icd10_suggestions[0].code;
  if (report.cpt_suggestions?.[0]) H.$("override-cpt").placeholder = report.cpt_suggestions[0].code;

  H.show(H.$("review-panel"));
}

async function loadEncounters() {
  const rows = await H.apiFetch("/ui/encounters");
  const sel = H.$("encounter-select");
  sel.innerHTML = '<option value="">— Select —</option>';
  encounterTranscripts.clear();
  for (const row of rows) {
    const opt = document.createElement("option");
    opt.value = row.encounter_id;
    opt.textContent = `${row.patient_name} (${row.status})`;
    if (row.demo_transcript) encounterTranscripts.set(row.encounter_id, row.demo_transcript);
    sel.appendChild(opt);
  }
}

async function bootstrapDemo() {
  await H.apiFetch("/ui/demo/bootstrap", { method: "POST" });
  await loadEncounters();
}

async function runAudit() {
  H.setError(H.$("intake-error"), null);
  H.hide(H.$("review-panel"));
  const enc = H.$("encounter-select").value;
  const note = H.$("clinical-note").value.trim();
  if (!enc || !note) {
    H.setError(H.$("intake-error"), "Select encounter and enter clinical note");
    return;
  }
  H.$("audit-btn").disabled = true;
  H.show(H.$("intake-status"));
  H.$("intake-status").textContent = "Submitting code audit…";

  const form = new FormData();
  form.set("encounter_id", enc);
  form.set("clinical_note_text", note);
  form.set("specialty", H.$("specialty").value);
  form.set("payer_org_identifier", H.$("payer").value);

  try {
    const created = await H.apiFetch("/tasks/code-audit", { method: "POST", body: form });
    currentTaskId = created.task_id;
    pollTask(created.task_id);
  } catch (err) {
    H.setError(H.$("intake-error"), err.message);
    H.$("audit-btn").disabled = false;
    H.hide(H.$("intake-status"));
  }
}

function pollTask(taskId) {
  if (pollTimer) clearInterval(pollTimer);
  const tick = async () => {
    const task = await H.apiFetch(`/tasks/${taskId}/status`);
    H.$("intake-status").textContent = `Task ${task.status}${task.hitl_pending ? " (HITL)" : ""}…`;
    if (task.hitl_pending) {
      await H.apiFetch(`/tasks/${taskId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, notes: "Auto-resumed from RCM review UI" }),
      });
      return;
    }
    if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(task.status)) {
      clearInterval(pollTimer);
      H.$("audit-btn").disabled = false;
      H.hide(H.$("intake-status"));
      if (task.status === "SUCCEEDED") showReport(task);
      else H.setError(H.$("intake-error"), task.error_message || task.status);
    }
  };
  tick();
  pollTimer = setInterval(tick, 2000);
}

async function submitReview(approved) {
  H.setError(H.$("review-error"), null);
  try {
    const result = await H.apiFetch(`/ui/rcm/tasks/${currentTaskId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        override_icd10: H.$("override-icd").value.trim() || null,
        override_cpt: H.$("override-cpt").value.trim() || null,
        reviewer_notes: H.$("reviewer-notes").value.trim() || null,
      }),
    });
    H.$("review-result").textContent = approved
      ? `Approved — claim ${result.claim_id || "n/a"} ready to submit`
      : "Rejected — codes not approved for submission";
    H.show(H.$("review-result"));
  } catch (err) {
    H.setError(H.$("review-error"), err.message);
  }
}

async function onReady() {
  H.show(H.$("intake-panel"));
  await loadEncounters();
}

H.renderNav("rcm");
H.wireLoginForm({ onSuccess: onReady });
H.$("bootstrap-btn")?.addEventListener("click", bootstrapDemo);
H.$("encounter-select")?.addEventListener("change", () => {
  const t = encounterTranscripts.get(H.$("encounter-select").value);
  if (t) H.$("clinical-note").value = t;
});
H.$("audit-btn")?.addEventListener("click", runAudit);
H.$("approve-btn")?.addEventListener("click", () => submitReview(true));
H.$("reject-btn")?.addEventListener("click", () => {
  if (confirm("Reject these code suggestions?")) submitReview(false);
});
H.requireAuth(onReady);
