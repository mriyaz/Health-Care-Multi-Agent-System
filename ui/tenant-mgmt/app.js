const H = window.HealthOS;

async function saveTenant(tenantId, row) {
  const tier = row.querySelector(".tier-select").value;
  const name = row.querySelector(".name-input").value.trim();
  await H.apiFetch(`/ui/tenants/${tenantId}/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ llm_tier: tier, display_name: name || null }),
  });
}

async function loadTenants() {
  H.setError(H.$("tenant-error"), null);
  try {
    const rows = await H.apiFetch("/ui/tenants");
    const tbody = H.$("tenant-table").querySelector("tbody");
    tbody.innerHTML = rows
      .map(
        (t) => `<tr data-tenant="${t.tenant_id}">
          <td><code>${t.tenant_id.slice(0, 8)}…</code>${t.is_current ? " <span class='badge ok'>current</span>" : ""}</td>
          <td>${t.user_count}</td>
          <td>${t.task_count}</td>
          <td>
            <select class="tier-select">
              <option value="dev" ${t.llm_tier === "dev" ? "selected" : ""}>dev</option>
              <option value="production" ${t.llm_tier === "production" ? "selected" : ""}>production</option>
              <option value="demo" ${t.llm_tier === "demo" ? "selected" : ""}>demo</option>
            </select>
          </td>
          <td><input class="name-input" value="${t.display_name || ""}" style="min-width:140px" /></td>
          <td><button class="btn btn-primary btn-sm btn-save">Save</button></td>
        </tr>`
      )
      .join("");

    tbody.querySelectorAll("tr").forEach((row) => {
      row.querySelector(".btn-save").addEventListener("click", async () => {
        try {
          await saveTenant(row.dataset.tenant, row);
          row.querySelector(".btn-save").textContent = "Saved ✓";
          setTimeout(() => (row.querySelector(".btn-save").textContent = "Save"), 1500);
        } catch (err) {
          H.setError(H.$("tenant-error"), err.message);
        }
      });
    });

    H.show(H.$("tenant-panel"));
  } catch (err) {
    H.setError(H.$("tenant-error"), err.message);
  }
}

H.renderNav("tenants");
H.wireLoginForm({ onSuccess: loadTenants });
H.requireAuth(loadTenants);
