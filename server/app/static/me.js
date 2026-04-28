(function () {
  const dataEl = document.getElementById("initial-data");
  if (!dataEl) return;

  const initial = JSON.parse(dataEl.textContent || "{}");
  let currentWindow = initial.window;
  let currentZ = Number.isInteger(initial.z) ? initial.z : 0;
  const home = initial.home || { x: 0, y: 0 };
  let lastTarget = null;

  const mapEl = document.getElementById("map-grid");
  const statusEl = document.getElementById("action-status");
  const unitPosEl = document.getElementById("hud-unit-pos");
  const zEl = document.getElementById("hud-z");

  const setStatus = (text, kind) => {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.remove("ok", "err");
    if (kind) statusEl.classList.add(kind);
  };

  const detectScoutPos = () => {
    if (!currentWindow || !currentWindow.cells) return { x: home.x, y: home.y, z: currentZ };
    for (const row of currentWindow.cells) {
      for (const c of row.row) {
        const hasScoutFleet = (c.objects || []).some((o) => o.type === "fleet" && o.unit_type === "scout");
        if (hasScoutFleet) return { x: c.x, y: c.y, z: c.z };
      }
    }
    return { x: home.x, y: home.y, z: currentZ };
  };

  const renderMap = () => {
    if (!mapEl || !currentWindow || !currentWindow.cells) return;
    const size = currentWindow.radius * 2 + 1;
    mapEl.innerHTML = "";
    mapEl.style.setProperty("--map-size", String(size));

    const scout = detectScoutPos();
    if (unitPosEl) unitPosEl.textContent = `${scout.x}, ${scout.y}, ${scout.z}`;
    if (zEl) zEl.textContent = String(currentZ);

    for (const row of currentWindow.cells) {
      const rowEl = document.createElement("div");
      rowEl.className = "map-row";
      for (const c of row.row) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cell";

        const hasObjects = c.flags && c.flags.has_objects;
        const isCenter = c.flags && c.flags.is_center;
        const hasScoutFleet = (c.objects || []).some((o) => o.type === "fleet" && o.unit_type === "scout");

        if (hasObjects) btn.classList.add("cell-object");
        if (isCenter) btn.classList.add("cell-center");
        if (hasScoutFleet) btn.classList.add("cell-unit");
        if (c.terrain === "anomaly") btn.classList.add("cell-unknown");
        if (lastTarget && c.x === lastTarget.x && c.y === lastTarget.y && c.z === lastTarget.z) btn.classList.add("cell-target");

        const marker = hasScoutFleet ? "U" : (isCenter ? "P" : c.glyph || ".");
        btn.innerHTML = `<div><div>${marker}</div><div class='coord'>${c.x},${c.y}</div></div>`;
        btn.title = `Сектор (${c.x}, ${c.y}, z=${c.z})`;
        btn.addEventListener("click", () => moveScout(c.x, c.y, c.z));
        rowEl.appendChild(btn);
      }
      mapEl.appendChild(rowEl);
    }
  };

  const refreshWindow = async () => {
    const r = await fetch(`/api/world/window?radius=4&z=${currentZ}`);
    if (!r.ok) {
      setStatus("Ошибка загрузки карты", "err");
      return;
    }
    currentWindow = await r.json();
    renderMap();
  };

  const moveScout = async (x, y, z) => {
    setStatus(`Отправка юнита в ${x},${y},${z}...`);
    try {
      const r = await fetch("/api/units/move_scout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        const msg = body.error || "move_failed";
        setStatus(`Ошибка движения: ${msg}`, "err");
        return;
      }
      lastTarget = { x, y, z };
      setStatus(`Юнит перемещён: ${x},${y},${z}`, "ok");
      await refreshWindow();
    } catch (_e) {
      setStatus("Сетевая ошибка при движении", "err");
    }
  };

  const dirToTarget = (dir) => {
    if (dir === "N") return { x: home.x, y: home.y - 1, z: 0 };
    if (dir === "S") return { x: home.x, y: home.y + 1, z: 0 };
    if (dir === "W") return { x: home.x - 1, y: home.y, z: 0 };
    if (dir === "E") return { x: home.x + 1, y: home.y, z: 0 };
    return { x: home.x, y: home.y, z: 0 };
  };

  document.querySelectorAll("button[data-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = dirToTarget(btn.dataset.dir);
      moveScout(target.x, target.y, target.z);
    });
  });

  const zDown = document.getElementById("z-down");
  const zUp = document.getElementById("z-up");
  if (zDown) {
    zDown.addEventListener("click", async () => {
      currentZ = Math.max(-10, currentZ - 1);
      await refreshWindow();
      setStatus(`Слой изменён: z=${currentZ}`);
    });
  }
  if (zUp) {
    zUp.addEventListener("click", async () => {
      currentZ = Math.min(10, currentZ + 1);
      await refreshWindow();
      setStatus(`Слой изменён: z=${currentZ}`);
    });
  }

  const versionChip = document.getElementById("api-version-chip");
  const checkVersion = async () => {
    if (!versionChip) return;
    try {
      const r = await fetch("/api/version");
      if (!r.ok) throw new Error("bad status");
      const body = await r.json();
      versionChip.classList.add("status-ok");
      versionChip.querySelector("span:last-child").textContent = `API: ${body.app}`;
    } catch (_e) {
      versionChip.classList.add("status-fail");
      versionChip.querySelector("span:last-child").textContent = "API: offline";
    }
  };

  renderMap();
  checkVersion();
})();
