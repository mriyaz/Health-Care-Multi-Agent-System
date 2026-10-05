const H = window.HealthOS;

async function approveTask(taskId, approved, notes) {
  return H.apiFetch(`/tasks/${taskId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, notes: notes || null }),
  });
}

function renderQueue(items) {
  const list = H.$("queue-list");
  if (!items.length) {
    list.innerHTML = `<p class="hint">No tasks in the HITL queue. Tasks appear here when confidence is low or the orchestrator blocks for review.</p>`;
    return;
  }
  list.innerHTML = items
    .map((t) => {
      const conf =
        t.confidence_scores?.specialist ??
        t.confidence_scores?.documentation ??
        null;
      const confStr = conf != null ? `${(conf * 100).toFixed(0)}%` : "—";
      const summary = t.agent_outputs?.documentation?.soap
        ? "SOAP note generated"
        : t.agent_outputs?.rcm_audit_report
          ? "RCM audit report"
          : t.agent_outputs?.specialist?.summary || "—";
      return `<div class="card" style="margin-bottom:0.75rem" data-task="${t.task_id}">
        <div class="panel-head">
          <div>
            ${H.priorityBadge(t.priority)}
            <span class="badge blocked">${t.task_type}</span>
            <span class="chip">Confidence ${confStr}</span>
          </div>
          <span class="chip">${H.fmtDate(t.updated_at)}</span>
        </div>
        <p class="hint"><code>${t.task_id}</code> · ${summary}</p>
        <label class="full-width">Reviewer notes (optional)
          <textarea class="review-notes" rows="2" placeholder="Reason for approval or rejection…"></textarea>
        </label>
        <div class="actions">
          <button class="btn btn-success btn-approve">Approve</button>
          <button class="btn btn-danger btn-reject">Reject</button>
        </div>
        <p class="task-result error hidden"></p>
      </div>`;
    })
    .join("");

  list.querySelectorAll("[data-task]").forEach((card) => {
    const taskId = card.dataset.task;
    const notesEl = card.querySelector(".review-notes");
    const resultEl = card.querySelector(".task-result");
    card.querySelector(".btn-approve").addEventListener("click", async () => {
      try {
        await approveTask(taskId, true, notesEl.value.trim());
        resultEl.textContent = "Approved — task resumed.";
        resultEl.classList.remove("error");
        resultEl.classList.add("hint");
        H.show(resultEl);
        setTimeout(loadQueue, 800);
      } catch (err) {
        H.setError(resultEl, err.message);
      }
    });
    card.querySelector(".btn-reject").addEventListener("click", async () => {
      if (!confirm("Reject this task?")) return;
      try {
        await approveTask(taskId, false, notesEl.value.trim() || "Rejected from HITL UI");
        resultEl.textContent = "Rejected.";
        H.show(resultEl);
        setTimeout(loadQueue, 800);
      } catch (err) {
        H.setError(resultEl, err.message);
      }
    });
  });
}

async function loadQueue() {
  H.setError(H.$("queue-error"), null);
  try {
    const items = await H.apiFetch("/ui/hitl-queue");
    renderQueue(items);
    H.show(H.$("queue-panel"));
  } catch (err) {
    H.setError(H.$("queue-error"), err.message);
  }
}

H.renderNav("hitl");
H.wireLoginForm({ onSuccess: loadQueue });
H.$("refresh-btn")?.addEventListener("click", loadQueue);
H.requireAuth(loadQueue);
