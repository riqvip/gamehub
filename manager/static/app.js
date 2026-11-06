"use strict";
const $ = (id) => document.getElementById(id);
let csrf = "",
  selected = "",
  tab = "health",
  servers = [],
  modData = [],
  updateId = "",
  busy = false;
const text = (tag, content, cls) => {
  const e = document.createElement(tag);
  e.textContent = content;
  if (cls) e.className = cls;
  return e;
};
function button(label, action, cls) {
  const b = text("button", label, cls);
  b.type = "button";
  b.onclick = () => run(b, action);
  return b;
}
function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(
    () => ($("notice").hidden = true),
    error ? 12000 : 6000,
  );
}
async function run(b, action) {
  if (busy) return;
  busy = true;
  b.disabled = true;
  try {
    await action();
  } catch (e) {
    notify(e.message, true);
  } finally {
    b.disabled = false;
    busy = false;
  }
}
async function api(path, options = {}) {
  const headers = { "X-CSRF-Token": csrf, ...options.headers };
  if (options.body && !(options.body instanceof File))
    headers["Content-Type"] = "application/json";
  const r = await fetch("/api/" + path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  let data;
  try {
    data = await r.json();
  } catch {
    throw new Error("The service returned an unreadable response.");
  }
  if (!r.ok) {
    if (r.status === 401 && path !== "login") showLogin();
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the form values and try again.",
    );
  }
  return data;
}
const post = (path, value) =>
  api(path, {
    method: "POST",
    ...(value === undefined ? {} : { body: JSON.stringify(value) }),
  });
const base = () => "servers/" + selected;
function showLogin() {
  csrf = "";
  $("app").hidden = true;
  $("login-view").hidden = false;
}
async function boot() {
  $("app").hidden = false;
  $("login-view").hidden = true;
  await loadServers();
}
$("login-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    $("login-error").textContent = "";
    try {
      const j = await post("login", {
        username: $("login-user").value,
        password: $("login-pass").value,
      });
      csrf = j.csrf;
      $("login-pass").value = "";
      await boot();
    } catch (err) {
      $("login-error").textContent = err.message;
    }
  });
};
$("logout").onclick = () =>
  run($("logout"), async () => {
    await post("logout");
    showLogin();
  });
function showPage(page) {
  for (const p of ["overview", "activity", "detail"]) $(p).hidden = p !== page;
}
$("overview-link").onclick = () => {
  selected = "";
  showPage("overview");
  $("breadcrumb").textContent = "Workspace / Overview";
  loadServers().catch((e) => notify(e.message, true));
};
$("activity-link").onclick = () =>
  run($("activity-link"), async () => {
    selected = "";
    showPage("activity");
    $("breadcrumb").textContent = "Workspace / Activity";
    const rows = await api("activity");
    $("activity-list").replaceChildren(
      ...rows.map((r) =>
        text(
          "p",
          `${new Date(r.at * 1000).toLocaleString()} · ${r.actor} · ${r.action} ${r.target} · ${r.outcome}`,
          "small",
        ),
      ),
    );
  });
async function loadServers() {
  servers = await api("servers");
  $("server-list").replaceChildren();
  $("overview-cards").replaceChildren();
  for (const s of servers) {
    const b = button(
      "◉  " + s.name,
      () => selectServer(s.id),
      "nav-link" + (selected === s.id ? " active" : ""),
    );
    $("server-list").append(b);
    const card = text("div", "", "card");
    card.append(
      text("p", "PALWORLD", "eyebrow"),
      text("h2", s.name),
      text("p", s.state, "muted"),
      button("Manage server →", () => selectServer(s.id)),
    );
    $("overview-cards").append(card);
  }
  if (!servers.length)
    $("overview-cards").append(
      text(
        "div",
        "Your first world is a few clicks away. Create a server to get started.",
        "empty",
      ),
    );
}
async function selectServer(id) {
  selected = id;
  tab = "health";
  showPage("detail");
  await loadServers();
  await refreshDetail();
  await openTab("health");
}
async function refreshDetail() {
  const s = await api(base());
  $("server-name").textContent = s.name;
  $("server-meta").textContent =
    `${s.state} · Game UDP ${s.game_port} · Native Linux`;
  $("breadcrumb").textContent = "Servers / " + s.name;
  const j = s.job || {};
  $("job-panel").hidden = j.state === "idle" || !j.state;
  $("job-title").textContent = `${j.kind || "Installation"} · ${j.state}`;
  $("job-log").textContent =
    (j.log || []).join("\n") + (j.error ? "\nERROR: " + j.error : "");
  document.querySelector('[data-action="cancel"]').hidden =
    j.state !== "running";
  for (const b of document.querySelectorAll(".page-title [data-action]"))
    b.disabled =
      j.state === "running" ||
      (b.dataset.action === "start" &&
        (!s.installed || s.state === "running")) ||
      (b.dataset.action !== "start" && s.state !== "running");
  $("more-actions").textContent = s.installed
    ? "Update runtime"
    : "Install runtime";
  $("more-actions").disabled = j.state === "running";
}
for (const b of document.querySelectorAll("[data-action]"))
  b.onclick = () =>
    run(b, async () => {
      const action = b.dataset.action;
      if (
        ["stop", "restart", "cancel"].includes(action) &&
        !confirm(`${action} this server operation?`)
      )
        return;
      await post(base() + "/actions", { action });
      notify("Requested: " + action);
      await refreshDetail();
    });
$("more-actions").onclick = () =>
  run($("more-actions"), async () => {
    const s = await api(base());
    const action = s.installed ? "update" : "install";
    if (
      !confirm(
        `${action} Palworld? Downloads can take several minutes. An update first stops the server and creates a verified Saved backup.`,
      )
    )
      return;
    await post(base() + "/actions", { action });
    await refreshDetail();
  });
for (const b of document.querySelectorAll("[data-tab]"))
  b.onclick = () =>
    openTab(b.dataset.tab).catch((e) => notify(e.message, true));
async function openTab(name) {
  tab = name;
  for (const b of document.querySelectorAll("[data-tab]")) {
    b.classList.toggle("active", b.dataset.tab === name);
    $("tab-" + b.dataset.tab).hidden = b.dataset.tab !== name;
  }
  await refreshTab();
}
async function refreshTab() {
  if (!selected) return;
  return {
    health: loadHealth,
    logs: loadLogs,
    players: loadPlayers,
    settings: loadSettings,
    mods: loadMods,
    backups: loadBackups,
  }[tab]();
}
async function loadHealth() {
  const h = await api(base() + "/health");
  $("health-cards").replaceChildren();
  for (const [label, value] of [
    ["CONTAINER", h.state],
    ["CPU", h.cpu_percent === null ? "—" : h.cpu_percent + "%"],
    ["MEMORY", h.mem_mb === null ? "—" : Math.round(h.mem_mb) + " MiB"],
  ]) {
    const c = text("div", "", "card");
    c.append(text("p", label, "eyebrow"), text("div", value, "metric"));
    $("health-cards").append(c);
  }
  $("health-checks").replaceChildren();
  for (const [key, label] of [
    ["container_running", "Container running"],
    ["game_process_running", "Game process running"],
    ["game_initialized", "Game initialized (authenticated RCON)"],
    ["game_port_bound", "Game port bound"],
    ["external_connectivity_verified", "External connectivity verified"],
  ]) {
    const row = text("div", "", "health-line");
    row.append(
      text("span", label),
      text(
        "span",
        h[key] === null ? "Unknown" : h[key] ? "Confirmed" : "Not confirmed",
        h[key] === true ? "yes" : "unknown",
      ),
    );
    $("health-checks").append(row);
  }
}
async function loadLogs() {
  const j = await api(base() + "/logs");
  const e = $("logs");
  const bottom = e.scrollHeight - e.scrollTop - e.clientHeight < 60;
  e.textContent = j.logs;
  if (bottom) e.scrollTop = e.scrollHeight;
}
$("rcon-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const j = await post(base() + "/rcon", {
      command: $("rcon-command").value,
    });
    $("rcon-output").textContent = j.output;
  });
};
async function loadPlayers() {
  const j = await api(base() + "/players");
  $("players-list").replaceChildren(
    ...j.players.map((p) => {
      const row = text("div", "", "player-row");
      row.append(text("b", p.name), text("span", p.steam_id, "muted"));
      return row;
    }),
  );
  if (!j.players.length)
    $("players-list").append(text("p", "No connected players.", "muted"));
}
$("refresh-players").onclick = () => run($("refresh-players"), loadPlayers);
async function loadSettings() {
  const j = await api(base() + "/settings");
  for (const [k, v] of Object.entries(j))
    if ($("settings-form").elements[k])
      $("settings-form").elements[k].value = v;
}
$("settings-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const values = Object.fromEntries(new FormData(e.target));
    values.players = Number(values.players);
    if (!values.admin_password) delete values.admin_password;
    if (!values.server_password && !$("clear-join-password").checked)
      delete values.server_password;
    await api(base() + "/settings", {
      method: "PUT",
      body: JSON.stringify(values),
    });
    notify("Settings saved. Start the server to apply them.");
    await loadSettings();
  });
};
$("remove-server").onclick = () =>
  run($("remove-server"), async () => {
    const s = await api(base());
    const confirmation = prompt(
      `Type ${s.name} to remove its registration. Files and backups are retained.`,
    );
    if (confirmation === null) return;
    await post(base() + "/actions", { action: "remove", confirmation });
    selected = "";
    showPage("overview");
    await loadServers();
  });
async function loadMods() {
  const j = await api(base() + "/mods");
  modData = j.installed;
  renderMods();
  $("mod-events").textContent =
    j.events
      .map((e) => new Date(e.at * 1000).toLocaleString() + " · " + e.message)
      .join("\n") || "No installations yet.";
}
function renderMods() {
  const query = $("mod-search").value.toLowerCase(),
    filter = $("mod-filter").value,
    sort = $("mod-sort").value;
  const mods = modData
    .filter(
      (m) =>
        [m.name, m.author, m.version, m.description]
          .join(" ")
          .toLowerCase()
          .includes(query) &&
        (filter === "all" || m.enabled === (filter === "enabled")),
    )
    .sort((a, b) =>
      sort === "newest"
        ? b.installed_at - a.installed_at
        : String(a[sort]).localeCompare(String(b[sort])),
    );
  $("mod-list").replaceChildren();
  for (const m of mods) {
    const card = text("article", "", "card mod-card");
    card.append(
      text(
        "span",
        m.enabled ? "ENABLED · RESTART TO APPLY" : "DISABLED · FILES PRESERVED",
        "tag",
      ),
      text("h3", m.name || m.id),
      text("p", m.description || "No description supplied.", "description"),
    );
    const dl = document.createElement("dl");
    for (const [k, v] of [
      ["Version", m.version],
      ["Author", m.author],
      ["Source", m.source],
      ["Installed", new Date(m.installed_at * 1000).toLocaleDateString()],
      ["Compatibility", "Unverified · Linux"],
      ["Updates", "Not checked"],
      ["Dependencies", m.dependencies.join(", ") || "None declared"],
      ["Files", m.files.map((f) => f.name).join(", ")],
      ["Package ID", m.id],
    ])
      dl.append(text("dt", k), text("dd", v));
    card.append(dl);
    if (m.installation_error)
      card.append(text("p", m.installation_error, "error"));
    const actions = text("div", "", "actions");
    actions.append(
      button(m.enabled ? "Disable" : "Enable", async () => {
        let ack = false;
        if (!m.enabled) {
          ack = confirm(
            "This stages the package's files. Game mod loading is disabled in the current runtime, so staging does not activate the mod in-game. Continue?",
          );
          if (!ack) return;
        }
        await post(base() + `/mods/${m.id}/actions`, {
          action: m.enabled ? "disable" : "enable",
          acknowledge_unverified: ack,
        });
        await loadMods();
        notify("Mod state saved. Start / restart to apply.");
      }),
      button("Update", () => openInstall(m.id)),
      button(
        "Remove",
        async () => {
          if (!confirm(`Remove ${m.name} from the library?`)) return;
          await post(base() + `/mods/${m.id}/actions`, { action: "remove" });
          await loadMods();
        },
        "danger",
      ),
    );
    if (m.previous)
      actions.append(
        button("Revert update", async () => {
          if (!confirm("Restore the previous package revision?")) return;
          await post(base() + `/mods/${m.id}/actions`, { action: "rollback" });
          await loadMods();
        }),
      );
    card.append(actions);
    $("mod-list").append(card);
  }
  if (!mods.length)
    $("mod-list").append(
      text(
        "div",
        query
          ? "No matching mods."
          : "Your library is ready. Upload a package to get started.",
        "empty",
      ),
    );
}
for (const id of ["mod-search", "mod-filter", "mod-sort"])
  $(id).addEventListener("input", renderMods);
function openInstall(id = "") {
  updateId = id;
  $("install-error").textContent = "";
  $("install-context").textContent = id
    ? "Select a replacement package. The previous revision remains available to revert."
    : "Validated first. Installed disabled. Yours to enable.";
  $("install-dialog").showModal();
}
$("open-install").onclick = () => openInstall();
$("upload-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const file = $("mod-file").files[0];
    if (file.size > 128 * 1024 * 1024) throw new Error("File exceeds 128 MiB.");
    try {
      await api(base() + "/mods/upload", {
        method: "POST",
        body: file,
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": file.name,
          "X-Update-Id": updateId,
        },
      });
      $("install-dialog").close();
      await loadMods();
      notify("Package validated and stored. New packages remain disabled.");
    } catch (err) {
      $("install-error").textContent = err.message;
    }
  });
};
$("url-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    try {
      await post(base() + "/mods/url", {
        ...Object.fromEntries(new FormData(e.target)),
        update_id: updateId,
      });
      $("install-dialog").close();
      await loadMods();
      notify("Download validated and installed.");
    } catch (err) {
      $("install-error").textContent = err.message;
    }
  });
};
async function loadBackups() {
  const j = await api(base() + "/backups");
  for (const [k, v] of Object.entries(j.policy))
    $("backup-policy").elements[k].value = v;
  $("schedule-status").textContent = j.schedule.status
    ? `Last scheduled attempt: ${j.schedule.status}${j.schedule.error ? " · " + j.schedule.error : ""}`
    : "No scheduled backup has run yet.";
  $("backup-list").replaceChildren();
  for (const b of j.backups) {
    const row = text("div", "", "card backup-row"),
      label = text("div", "");
    label.append(
      text("b", b.filename),
      text(
        "p",
        `${new Date(b.created * 1000).toLocaleString()} · ${(b.size_bytes / 1024 ** 2).toFixed(1)} MiB · Checksum verified`,
        "small muted",
      ),
    );
    const actions = text("div", "", "actions");
    actions.append(
      button("Preview restore", async () => {
        const preview = await post(base() + "/backups/restore", {
          filename: b.filename,
          dry_run: true,
        });
        const s = await api(base());
        restoreTarget = { sid: selected, filename: b.filename };
        $("restore-summary").replaceChildren(
          text("b", b.filename),
          text(
            "p",
            `${preview.files} verified files · ${(preview.extracted_bytes / 1024 ** 2).toFixed(1)} MiB · ${preview.destination}`,
          ),
        );
        $("restore-label").textContent = `Type ${s.name} to confirm`;
        $("restore-confirmation").value = "";
        $("restore-dialog").showModal();
      }),
      button(
        "Delete",
        async () => {
          if (!confirm("Delete this backup permanently?")) return;
          await api(base() + "/backups/" + b.filename, { method: "DELETE" });
          await loadBackups();
        },
        "danger",
      ),
    );
    row.append(label, actions);
    $("backup-list").append(row);
  }
  if (!j.backups.length)
    $("backup-list").append(
      text(
        "div",
        "No snapshots yet. Create one before changing your world.",
        "empty",
      ),
    );
}
$("backup-now").onclick = () =>
  run($("backup-now"), async () => {
    if (
      !confirm(
        "Create a backup? A running server will stop and restart after a successful verified backup.",
      )
    )
      return;
    notify("Creating and verifying backup. Please wait…");
    await post(base() + "/backups");
    await loadBackups();
    await refreshDetail();
    notify("Backup verified and saved.");
  });
$("backup-policy").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const v = Object.fromEntries(new FormData(e.target));
    for (const k of Object.keys(v)) v[k] = Number(v[k]);
    await api(base() + "/backups/policy", {
      method: "PUT",
      body: JSON.stringify(v),
    });
    notify("Backup schedule saved.");
  });
};
for (const b of document.querySelectorAll("[data-close]"))
  b.onclick = () => $(b.dataset.close).close();
for (const id of ["new-server", "overview-create"])
  $(id).onclick = () => $("create-dialog").showModal();
$("create-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const v = Object.fromEntries(new FormData(e.target));
    const s = await post("servers", {
      name: v.name,
      game_port: Number(v.game_port),
      settings: { admin_password: v.admin_password, server_name: v.name },
    });
    $("create-dialog").close();
    e.target.reset();
    await selectServer(s.id);
    notify("Server registered. Choose Install runtime when ready.");
  });
};
setInterval(async () => {
  if (!csrf || !selected || busy || document.hidden) return;
  try {
    await refreshDetail();
    if (tab === "health" || tab === "logs") await refreshTab();
  } catch (e) {
    notify(e.message, true);
  }
}, 5000);
(async () => {
  try {
    const j = await api("session");
    csrf = j.csrf;
    await boot();
  } catch {
    showLogin();
  }
})();

let restoreTarget = null;
$("restore-form").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    if (!restoreTarget) return;
    await post(`servers/${restoreTarget.sid}/backups/restore`, {
      filename: restoreTarget.filename,
      dry_run: false,
      confirmation: $("restore-confirmation").value,
    });
    $("restore-dialog").close();
    notify("Saved data restored. Server remains stopped.");
  });
};
