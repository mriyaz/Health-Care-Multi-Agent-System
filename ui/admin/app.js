const H = window.HealthOS;

async function loadDashboard() {
  H.setError(H.$("dash-error"), null);
  try {
    const [summary, hitl, audit] = await Promise.all([
      H.apiFetch("/ui/dashboard/summary"),
      H.apiFetch("/ui/hitl-queue"),
      H.apiFetch("/ui/audit-trail?limit=20"),
    ]);

    const agents = H.$("agent-indicators");
    agents.innerHTML = Object.entries(summary.agents)
      .map(([name, ok]) => `<span class="agent-dot ${ok ? "ok" : "err"}">${name}</span>`)
      .join("");

    const stats = H.$("task-stats");
    const statusCounts = summary.task_counts_by_status || {};
    const hitlN = summary.hitl_pending_count || 0;
    stats.innerHTML = [
      { label: "HITL pending", value: hitlN },
      { label: "Queued", value: statusCounts.QUEUED || 0 },
      { label: "Running", value: statusCounts.RUNNING || 0 },
      { label: "Succeeded", value: statusCounts.SUCCEEDED || 0 },
      { label: "Failed", value: statusCounts.FAILED || 0 },
      { label: "Blocked", value: statusCounts.BLOCKED || 0 },
    ]
      .map((s) => `<div class="stat-card"><div class="value">${s.value}</div><div class="label">${s.label}</div></div>`)
      .join("");

    H.$("hitl-count").textContent = String(hitlN);
    const hitlBody = H.$("hitl-table").querySelector("tbody");
    hitlBody.innerHTML = hitl.length
      ? hitl
          .map((t) => {
            const conf = t.confidence_scores?.specialist ?? t.confidence_scores?.documentation;
            const confStr = conf != null ? `${(conf * 100).toFixed(0)}%` : "—";
            return `<tr>
              <td>${H.priorityBadge(t.priority)}</td>
              <td>${t.task_type}</td>
              <td><code>${t.task_id.slice(0, 8)}…</code></td>
              <td>${confStr}</td>
              <td>${H.fmtDate(t.updated_at)}</td>
            </tr>`;
          })
          .join("")
      : `<tr><td colspan="5">No tasks awaiting HITL approval</td></tr>`;

    const tasksBody = H.$("tasks-table").querySelector("tbody");
    tasksBody.innerHTML = (summary.recent_tasks || [])
      .map(
        (t) => `<tr>
          <td><span class="badge ${t.hitl_pending ? "blocked" : t.status === "SUCCEEDED" ? "ok" : ""}">${t.status}</span></td>
          <td>${t.task_type}</td>
          <td>${H.priorityBadge(t.priority)}</td>
          <td><code>${t.task_id.slice(0, 8)}…</code></td>
          <td>${H.fmtDate(t.updated_at)}</td>
        </tr>`
      )
      .join("");

    const auditBody = H.$("audit-table").querySelector("tbody");
    auditBody.innerHTML = audit.length
      ? audit
          .map(
            (a) => `<tr>
              <td>${H.fmtDate(a.created_at)}</td>
              <td>${a.action}</td>
              <td>${a.actor_id || a.actor_type}</td>
              <td>${a.resource_type}${a.resource_id ? ` · ${a.resource_id.slice(0, 8)}…` : ""}</td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="4">No audit events yet</td></tr>`;

    H.show(H.$("dashboard"));
  } catch (err) {
    H.setError(H.$("dash-error"), err.message);
  }
}

H.renderNav("admin");
H.wireLoginForm({ onSuccess: loadDashboard });
H.$("refresh-btn")?.addEventListener("click", loadDashboard);
H.requireAuth(loadDashboard);
