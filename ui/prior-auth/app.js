const H = window.HealthOS;

const COLUMNS = [
  { id: "pending", label: "Pending" },
  { id: "submitted", label: "Submitted" },
  { id: "approved", label: "Approved" },
  { id: "denied", label: "Denied" },
  { id: "appealing", label: "Appealing" },
];

async function moveCard(cardId, column) {
  await H.apiFetch(`/ui/prior-auth/cards/${cardId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ column }),
  });
}

function renderBoard(data) {
  H.$("board-note").textContent = data.note || `Source: ${data.source}`;
  const cards = data.cards || [];
  const kanban = H.$("kanban");
  kanban.innerHTML = COLUMNS.map((col) => {
    const colCards = cards.filter((c) => c.column === col.id);
    return `<div class="kanban-col" data-col="${col.id}">
      <h3>${col.label} (${colCards.length})</h3>
      ${colCards
        .map(
          (c) => `<div class="kanban-card">
            <strong>${c.patient_name}</strong><br>
            ${c.procedure}<br>
            <span class="chip">${c.payer}</span>
            <select data-card="${c.id}">
              ${COLUMNS.map((o) => `<option value="${o.id}" ${o.id === c.column ? "selected" : ""}>${o.label}</option>`).join("")}
            </select>
          </div>`
        )
        .join("")}
    </div>`;
  }).join("");

  kanban.querySelectorAll("select[data-card]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      try {
        await moveCard(sel.dataset.card, sel.value);
        await loadBoard();
      } catch (err) {
        H.setError(H.$("board-error"), err.message);
      }
    });
  });
}

async function loadBoard() {
  H.setError(H.$("board-error"), null);
  try {
    const data = await H.apiFetch("/ui/prior-auth/board");
    renderBoard(data);
    H.show(H.$("board-panel"));
  } catch (err) {
    H.setError(H.$("board-error"), err.message);
  }
}

H.renderNav("prior-auth");
H.wireLoginForm({ onSuccess: loadBoard });
H.$("seed-btn")?.addEventListener("click", async () => {
  try {
    await H.apiFetch("/ui/prior-auth/seed", { method: "POST" });
    await loadBoard();
  } catch (err) {
    H.setError(H.$("board-error"), err.message);
  }
});
H.requireAuth(loadBoard);
