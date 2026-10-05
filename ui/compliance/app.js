const H = window.HealthOS;

function buildParams() {
  const params = new URLSearchParams();
  const action = H.$("filter-action").value.trim();
  const actor = H.$("filter-actor").value.trim();
  const resource = H.$("filter-resource").value.trim();
  const from = H.$("filter-from").value;
  const to = H.$("filter-to").value;
  if (action) params.set("action", action);
  if (actor) params.set("actor_id", actor);
  if (resource) params.set("resource_type", resource);
  if (from) params.set("date_from", new Date(from).toISOString());
  if (to) params.set("date_to", new Date(to + "T23:59:59").toISOString());
  params.set("limit", "200");
  return params;
}

function renderRows(rows) {
  const tbody = H.$("audit-table").querySelector("tbody");
  tbody.innerHTML = rows.length
    ? rows
        .map(
          (a) => `<tr>
            <td>${H.fmtDate(a.created_at)}</td>
            <td>${a.action}</td>
            <td>${a.actor_id || a.actor_type}</td>
            <td>${a.resource_type}</td>
            <td>${a.resource_id ? `<code>${a.resource_id.slice(0, 10)}…</code>` : "—"}</td>
            <td>${a.task_id ? `<code>${String(a.task_id).slice(0, 8)}…</code>` : "—"}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="6">No matching audit events</td></tr>`;
}

async function search() {
  H.setError(H.$("compliance-error"), null);
  try {
    const rows = await H.apiFetch(`/ui/audit-trail?${buildParams()}`);
    renderRows(rows);
    H.show(H.$("compliance-panel"));
  } catch (err) {
    H.setError(H.$("compliance-error"), err.message);
  }
}

async function exportCsv() {
  const token = H.getToken();
  const params = buildParams();
  params.delete("limit");
  params.set("limit", "2000");
  const res = await fetch(`/ui/audit-trail/export?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `healthos-audit-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

H.renderNav("compliance");
H.wireLoginForm({ onSuccess: search });
H.$("search-btn")?.addEventListener("click", search);
H.$("export-btn")?.addEventListener("click", () => exportCsv().catch((e) => H.setError(H.$("compliance-error"), e.message)));
H.requireAuth(search);
