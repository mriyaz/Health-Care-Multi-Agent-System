/**
 * HealthOS shared UI utilities — auth, API, navigation (Section J).
 */
window.HealthOS = (function () {
  const TOKEN_KEY = "healthos_access_token";

  const NAV_LINKS = [
    { href: "/ui/admin/", label: "Dashboard", id: "admin" },
    { href: "/ui/hitl-review/", label: "HITL Queue", id: "hitl" },
    { href: "/ui/soap-review/", label: "SOAP Review", id: "soap" },
    { href: "/ui/rcm-review/", label: "RCM Review", id: "rcm" },
    { href: "/ui/rcm-analytics/", label: "RCM Analytics", id: "analytics" },
    { href: "/ui/prior-auth/", label: "Prior Auth", id: "prior-auth" },
    { href: "/ui/tenant-mgmt/", label: "Tenants", id: "tenants" },
    { href: "/ui/compliance/", label: "Compliance", id: "compliance" },
  ];

  function $(id) {
    return document.getElementById(id);
  }

  function show(el) {
    el.classList.remove("hidden");
  }
  function hide(el) {
    el.classList.add("hidden");
  }

  function setError(el, msg) {
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      show(el);
    } else {
      el.textContent = "";
      hide(el);
    }
  }

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
  }

  async function apiFetch(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      clearToken();
      throw new Error("Session expired — please sign in again.");
    }
    const text = await res.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!res.ok) {
      const detail =
        typeof body === "object" && body !== null
          ? body.detail || JSON.stringify(body)
          : String(body);
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  async function login(username, password) {
    const form = new URLSearchParams();
    form.set("username", username);
    form.set("password", password);
    const res = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Login failed");
    setToken(body.access_token);
    return body;
  }

  function renderNav(activeId) {
    const nav = document.querySelector(".top-nav");
    if (!nav) return;
    nav.innerHTML = NAV_LINKS.map(
      (l) =>
        `<a href="${l.href}" class="${l.id === activeId ? "active" : ""}">${l.label}</a>`
    ).join("");
  }

  function wireLoginForm(opts) {
    const form = $(opts.formId || "login-form");
    const errEl = $(opts.errorId || "login-error");
    const onSuccess = opts.onSuccess || (() => location.reload());

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      setError(errEl, null);
      try {
        await login($(opts.usernameId || "username").value, $(opts.passwordId || "password").value);
        onSuccess();
      } catch (err) {
        setError(errEl, err.message);
      }
    });
  }

  async function requireAuth(onReady) {
    const statusEl = $("auth-status");
    if (!getToken()) {
      if (statusEl) statusEl.textContent = "Not signed in";
      show($("login-panel"));
      return;
    }
    try {
      await apiFetch("/auth/me");
      if (statusEl) statusEl.textContent = "Signed in";
      hide($("login-panel"));
      if (onReady) await onReady();
    } catch {
      if (statusEl) statusEl.textContent = "Not signed in";
      show($("login-panel"));
    }
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  }

  function priorityBadge(p) {
    const cls = p === "URGENT" ? "urgent" : p === "HIGH" ? "high" : "";
    return `<span class="badge ${cls}">${p}</span>`;
  }

  return {
    TOKEN_KEY,
    $,
    show,
    hide,
    setError,
    getToken,
    login,
    apiFetch,
    renderNav,
    wireLoginForm,
    requireAuth,
    fmtDate,
    priorityBadge,
  };
})();
