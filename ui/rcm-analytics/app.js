const H = window.HealthOS;

function barChart(containerId, data, labelKey) {
  const el = H.$(containerId);
  const entries = Object.entries(data || {});
  if (!entries.length) {
    el.innerHTML = "<p class='hint'>No data for selected filters</p>";
    return;
  }
  const max = Math.max(...entries.map(([, v]) => v), 1);
  el.innerHTML = entries
    .map(
      ([k, v]) => `<div class="shap-bar">
        <span style="width:35%">${k}</span>
        <div class="bar"><div class="fill" style="width:${(v / max) * 100}%"></div></div>
        <span>${v}</span>
      </div>`
    )
    .join("");
}

async function loadAnalytics() {
  H.setError(H.$("analytics-error"), null);
  const params = new URLSearchParams();
  const df = H.$("date-from").value;
  const dt = H.$("date-to").value;
  const payer = H.$("payer-filter").value.trim();
  if (df) params.set("date_from", new Date(df).toISOString());
  if (dt) params.set("date_to", new Date(dt + "T23:59:59").toISOString());
  if (payer) params.set("payer", payer);

  try {
    const data = await H.apiFetch(`/rcm/analytics/summary?${params}`);
    const fp = data.first_pass_rate_proxy;
    const rr = data.recovery_rate_proxy;
    H.$("summary-stats").innerHTML = [
      { label: "Total claims", value: data.total_claims },
      { label: "First-pass rate", value: fp != null ? `${(fp * 100).toFixed(1)}%` : "—" },
      { label: "Denied", value: data.denied_count },
      { label: "Paid", value: data.paid_count },
      { label: "Recovery rate", value: rr != null ? `${(rr * 100).toFixed(1)}%` : "—" },
      { label: "Revenue at risk", value: `$${(data.revenue_at_risk_usd || 0).toLocaleString()}` },
    ]
      .map((s) => `<div class="stat-card"><div class="value">${s.value}</div><div class="label">${s.label}</div></div>`)
      .join("");

    H.$("analytics-note").textContent = data.note || "";
    barChart("payer-chart", data.denial_by_payer);
    barChart("cpt-chart", data.denial_by_cpt);

    const tbody = H.$("status-table").querySelector("tbody");
    tbody.innerHTML = Object.entries(data.claims_by_status || {})
      .map(([st, cnt]) => `<tr><td>${st}</td><td>${cnt}</td></tr>`)
      .join("");

    H.show(H.$("analytics-panel"));
  } catch (err) {
    H.setError(H.$("analytics-error"), err.message);
  }
}

H.renderNav("analytics");
H.wireLoginForm({ onSuccess: loadAnalytics });
H.$("apply-btn")?.addEventListener("click", loadAnalytics);
H.requireAuth(loadAnalytics);
