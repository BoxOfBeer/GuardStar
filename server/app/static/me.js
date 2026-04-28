(function () {
  const dataEl = document.getElementById("initial-data");
  if (!dataEl) return;

  const initial = JSON.parse(dataEl.textContent || "{}");
  let currentWindow = initial.window;
  let currentZ = Number.isInteger(initial.z) ? initial.z : 0;
  const home = initial.home || { x: 0, y: 0 };
  const playerId = initial.player || null;
  let viewCenter = (currentWindow && currentWindow.center) ? { ...currentWindow.center } : { ...home };
  let lastTarget = null;
  let selectedCell = null;
  let worldState = { current_tick: 0, fleet: null, events: [] };

  const mapEl = document.getElementById("map-grid");
  const mapWrapEl = document.querySelector(".map-wrap");
  const flightOverlayEl = document.getElementById("flight-overlay");
  const statusEl = document.getElementById("status");
  const unitPosEl = document.getElementById("hud-unit-pos");
  const zEl = document.getElementById("hud-z");
  const tickEl = document.getElementById("hud-tick");
  const unitStatusEl = document.getElementById("hud-unit-status");
  const etaEl = document.getElementById("hud-eta");
  const etaArriveEl = document.getElementById("hud-arrive-tick");
  const selCoordEl = document.getElementById("sel-coord");
  const selTerrainEl = document.getElementById("sel-terrain");
  const selGlyphEl = document.getElementById("sel-glyph");
  const selObjectsEl = document.getElementById("sel-objects");
  const selDistanceEl = document.getElementById("sel-distance");
  const selTravelEl = document.getElementById("sel-travel");
  const selArriveEl = document.getElementById("sel-arrive");
  const flyBtn = document.getElementById("fly-btn");
  const clearSelBtn = document.getElementById("clear-sel-btn");
  const eventsEl = document.getElementById("events");
  const planetPanelEl = document.getElementById("planet-panel");
  const buildPanelEl = document.getElementById("build-panel");
  const manualTickBtn = document.getElementById("manual-tick-btn");
  const autotickToggle = document.getElementById("autotick-toggle");
  const autotickText = document.getElementById("autotick-text");
  const autotickChip = document.getElementById("autotick-chip");
  const topMetalEl = document.getElementById("top-metal");
  const topCrystalEl = document.getElementById("top-crystal");
  const topEnergyEl = document.getElementById("top-energy");
  const topFuelEl = document.getElementById("top-fuel");
  const topDeltaEl = document.getElementById("top-delta");
  const overlayEl = document.getElementById("confirm-overlay");
  const cfFromEl = document.getElementById("cf-from");
  const cfToEl = document.getElementById("cf-to");
  const cfEtaEl = document.getElementById("cf-eta");
  const cfArriveEl = document.getElementById("cf-arrive");
  const cfFuelEl = document.getElementById("cf-fuel");
  const cfDestEl = document.getElementById("cf-dest");
  const cfWarnEl = document.getElementById("cf-warn");
  const cfOkBtn = document.getElementById("cf-ok");
  const cfCancelBtn = document.getElementById("cf-cancel");
  const fleetSelectEl = document.getElementById("fleet-select");
  const homeBtn = document.getElementById("home-btn");

  // Панорамирование мышью отключено — используем только стрелки по краям поля.

  let pendingFleetMove = null; // { fleet_id, from:{x,y,z}, to:{x,y,z}, qty, distance, travelTicks, arriveTick, fuelCost, destLabel, warn }
  let activeFleetId = null;

  const setStatus = (text, kind) => {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.remove("ok", "err");
    if (kind) statusEl.classList.add(kind);
  };

  const detectScoutPos = () => {
    if (worldState && worldState.fleet) return { x: worldState.fleet.x, y: worldState.fleet.y, z: worldState.fleet.z };
    if (!currentWindow || !currentWindow.cells) return { x: home.x, y: home.y, z: currentZ };
    for (const row of currentWindow.cells) {
      for (const c of row.row) {
        const hasOwnedFleet = (c.objects || []).some((o) => o.type === "fleet" && o.owner === playerId);
        if (hasOwnedFleet) return { x: c.x, y: c.y, z: c.z };
      }
    }
    return { x: home.x, y: home.y, z: currentZ };
  };

  const renderEvents = (events) => {
    if (!eventsEl) return;
    const list = Array.isArray(events) ? events : [];
    if (list.length === 0) {
      eventsEl.innerHTML = "<div class='muted'>Пока нет событий.</div>";
      return;
    }
    // Свежие события — сверху
    eventsEl.innerHTML = [...list]
      .reverse()
      .map((e) => `<div class="event"><span class="muted">Тик ${e.tick}</span> — ${e.message}</div>`)
      .join("");
  };

  const updateSelectedPanel = () => {
    const unit = worldState ? worldState.fleet : null;
    const isMoving = unit && unit.status === "moving";

    if (!selectedCell) {
      if (selCoordEl) selCoordEl.textContent = "—";
      if (selTerrainEl) selTerrainEl.textContent = "—";
      if (selGlyphEl) selGlyphEl.textContent = "—";
      if (selObjectsEl) selObjectsEl.textContent = "—";
      if (selDistanceEl) selDistanceEl.textContent = "—";
      if (selTravelEl) selTravelEl.textContent = "—";
      if (selArriveEl) selArriveEl.textContent = "—";
      if (flyBtn) flyBtn.disabled = true;
      if (planetPanelEl) planetPanelEl.innerHTML = "Выбери клетку с планетой.";
      if (buildPanelEl) buildPanelEl.innerHTML = "Выбери клетку в зоне стройки.";
      return;
    }

    if (selCoordEl) selCoordEl.textContent = `${selectedCell.x}, ${selectedCell.y}, ${selectedCell.z}`;
    if (selTerrainEl) selTerrainEl.textContent = selectedCell.terrain || "—";
    if (selGlyphEl) selGlyphEl.textContent = selectedCell.glyph || "—";

    const objs = selectedCell.objects || [];
    if (selObjectsEl) {
      if (objs.length === 0) selObjectsEl.textContent = "нет";
      else {
        const fmt = (o) => {
          if (o.type === "planet") {
            const owner = o.owner_name ? ` (${o.owner_name})` : "";
            return `${o.name || "planet"}${owner}`;
          }
          if (o.type === "fleet") {
            const owner = o.owner_name ? ` (${o.owner_name})` : "";
            return `${o.unit_type}×${o.qty}${owner}`;
          }
          return o.type;
        };
        selObjectsEl.textContent = objs.map(fmt).join(", ");
      }
    }

    const from = unit ? { x: unit.x, y: unit.y, z: unit.z } : home;
    const dist = Math.abs(selectedCell.x - from.x) + Math.abs(selectedCell.y - from.y);
    const travelTicks = Math.max(1, dist);
    const currentTick = Number.isInteger(worldState.current_tick) ? worldState.current_tick : 0;
    const arriveTick = currentTick + travelTicks;

    if (selDistanceEl) selDistanceEl.textContent = String(dist);
    if (selTravelEl) selTravelEl.textContent = `${travelTicks} тиков`;
    if (selArriveEl) selArriveEl.textContent = `тик ${arriveTick}`;

    const sameCell = selectedCell.x === from.x && selectedCell.y === from.y && selectedCell.z === from.z;
    if (flyBtn) flyBtn.disabled = isMoving || sameCell;

    if (buildPanelEl) {
      const flags = selectedCell.flags || {};
      const objs = selectedCell.objects || [];
      const canBuild = Boolean(flags.zone_build_self) && !Boolean(flags.zone_build_enemy) && Boolean(flags.is_visible);
      const b = objs.find((o) => o.type === "building");
      if (!canBuild) {
        buildPanelEl.innerHTML = "<div class='muted'>Нельзя строить: вне зоны или в зоне врага.</div>";
      } else if (b) {
        buildPanelEl.innerHTML = `Постройка: <b>${b.building_type}</b> (lvl ${b.level || 1})`;
      } else {
        buildPanelEl.innerHTML = `
          <div class="row" style="gap:8px;flex-wrap:wrap;">
            <button type="button" data-b="mine">Шахта</button>
            <button type="button" data-b="reactor">Реактор</button>
            <button type="button" data-b="crystal_farm">Кристаллы</button>
          </div>
          <div class="muted" style="margin-top:6px;">Стоимость спишется с домашней планеты.</div>
        `;
        for (const btn of buildPanelEl.querySelectorAll("button[data-b]")) {
          btn.addEventListener("click", async () => {
            const bt = btn.getAttribute("data-b");
            await placeBuilding(selectedCell.x, selectedCell.y, selectedCell.z, bt);
          });
        }
      }
    }
  };

  const placeBuilding = async (x, y, z, building_type) => {
    setStatus("Строительство...");
    try {
      const r = await fetch("/api/buildings/place", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z, building_type }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "not_enough_resources") {
          setStatus(`Не хватает ресурсов: нужно M${body.need?.metal}/C${body.need?.crystal}`, "err");
        } else {
          setStatus(`Ошибка: ${body.error || "build_failed"}`, "err");
        }
        return;
      }
      setStatus(`Построено: ${body.building?.building_type || "ok"}`, "ok");
      await refreshWindow();
      if (selectedCell) await loadSectorDetails(selectedCell.x, selectedCell.y, selectedCell.z);
      await loadWorldState();
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const loadSectorDetails = async (x, y, z) => {
    if (!planetPanelEl) return;
    try {
      const r = await fetch(`/api/world/sector?x=${x}&y=${y}&z=${z}`);
      if (!r.ok) return;
      const sector = await r.json();
      const planet = (sector.objects || []).find((o) => o.type === "planet" && o.details);
      if (!planet) {
        planetPanelEl.innerHTML = "<div class='muted'>В этой клетке нет вашей планеты.</div>";
        return;
      }
      const d = planet.details;
      const u = (d.units || []).map((it) => `${it.unit_type}×${it.qty}`).join(", ") || "нет";
      const mp = d.production ? d.production.metal_per_tick : 0;
      const cp = d.production ? d.production.crystal_per_tick : 0;
      const ep = d.production ? d.production.energy_per_tick : 0;
      const fp = d.production ? d.production.fuel_per_tick : 0;
      planetPanelEl.innerHTML = `
        <div><b>${planet.name}</b> (${sector.x},${sector.y},${sector.z})</div>
        <div>Ресурсы: metal ${d.resources.metal}, crystal ${d.resources.crystal}, energy ${d.resources.energy}, fuel ${d.resources.fuel ?? 0}</div>
        <div>Выработка (тик): +${mp}/t, +${cp}/t, +${ep}/t, +${fp}/t</div>
        <div>Юниты: ${u}</div>
        <div>Стройка (заглушка): ${d.build.active || "нет"} • очередь: ${(d.build.queue || []).length}</div>
      `;
    } catch (_e) {
      // ignore
    }
  };

  const updateAutotickUi = (state) => {
    if (!autotickToggle || !autotickText || !autotickChip) return;
    const enabled = Boolean(state && state.auto_tick_enabled);
    const interval = state && state.auto_tick_interval_seconds ? Number(state.auto_tick_interval_seconds) : null;
    const err = state && state.auto_tick_error ? String(state.auto_tick_error) : "";
    const running = Boolean(state && state.auto_tick_running);
    const lastTick = state && state.auto_tick_last_tick != null ? String(state.auto_tick_last_tick) : "—";
    const lastRun = state && state.auto_tick_last_run_at ? String(state.auto_tick_last_run_at) : "—";
    autotickToggle.checked = enabled;
    autotickText.textContent = `Автотик: ${enabled ? "ON" : "OFF"}${interval ? ` (${interval}s)` : ""} • ${running ? "running" : "stopped"}`;
    autotickChip.classList.toggle("status-ok", enabled && !err);
    autotickChip.classList.toggle("status-fail", Boolean(err));
    autotickChip.title = err ? `Ошибка: ${err}` : `last_tick=${lastTick}\nlast_run_at=${lastRun}`;
  };

  const doManualTick = async () => {
    setStatus("Тик...");
    try {
      const r = await fetch("/api/world/tick", { method: "POST" });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка тика: ${body.error || "tick_failed"}`, "err");
        return;
      }
      setStatus(`Tick ${body.current_tick}: событий ${body.events.length}`, "ok");
      await refreshWindow();
    } catch (_e) {
      setStatus("Сетевая ошибка при обработке тика", "err");
    }
  };

  const loadWorldState = async () => {
    try {
      const r = await fetch("/api/world/state");
      if (!r.ok) return;
      const body = await r.json();
      worldState = body || worldState;
      if (tickEl) tickEl.textContent = String(body.current_tick ?? 0);
      updateAutotickUi(body);
      if (body.economy) {
        if (topMetalEl) topMetalEl.textContent = String(body.economy.metal ?? "—");
        if (topCrystalEl) topCrystalEl.textContent = String(body.economy.crystal ?? "—");
        if (topEnergyEl) topEnergyEl.textContent = String(body.economy.energy ?? "—");
        if (topFuelEl) topFuelEl.textContent = String(body.economy.fuel ?? "—");
        if (topDeltaEl && body.economy.avg_10_ticks) {
          const a = body.economy.avg_10_ticks;
          topDeltaEl.textContent = `(+${a.metal}/+${a.crystal}/+${a.energy}/+${a.fuel ?? 0} за 10t)`;
        }
      }

      const fleet = body.fleet;
      if (!fleet) return;
      if (unitStatusEl) unitStatusEl.textContent = fleet.status || "idle";
      if (unitPosEl) unitPosEl.textContent = `${fleet.x}, ${fleet.y}, ${fleet.z}`;

      if (fleet.active_order) {
        const ao = fleet.active_order;
        const eta = Number.isInteger(ao.remaining_ticks) ? ao.remaining_ticks : null;
        const arrive = Number.isInteger(ao.finish_tick) ? ao.finish_tick : null;
        if (etaEl) etaEl.textContent = eta === null ? "—" : `${eta} тиков`;
        if (etaArriveEl) etaArriveEl.textContent = arrive === null ? "—" : `тик ${arrive}`;
      } else {
        if (etaEl) etaEl.textContent = "—";
        if (etaArriveEl) etaArriveEl.textContent = "—";
      }
      renderEvents(body.events);
      updateSelectedPanel();
      renderFlightOverlay();

      // Populate owned fleets selector (scout + fighter, etc)
      const fleets = Array.isArray(body.fleets) ? body.fleets : [];
      const owned = fleets.filter((f) => f && f.id);
      if (fleetSelectEl) {
        const prev = activeFleetId;
        if (!activeFleetId && owned.length > 0) activeFleetId = owned[0].id;
        // keep current selection if it still exists
        if (prev && owned.some((f) => f.id === prev)) activeFleetId = prev;
        fleetSelectEl.innerHTML = owned
          .map((f) => {
            const sel = f.id === activeFleetId ? "selected" : "";
            return `<option value="${f.id}" ${sel}>${f.unit_type}×${f.qty} @ (${f.x},${f.y},${f.z})</option>`;
          })
          .join("");
        if (unitPosEl) {
          const af = owned.find((f) => f.id === activeFleetId) || fleet;
          unitPosEl.textContent = `${af.x}, ${af.y}, ${af.z}`;
        }
        if (unitStatusEl) {
          const af = owned.find((f) => f.id === activeFleetId) || fleet;
          unitStatusEl.textContent = af.status || "idle";
        }
        if (document.getElementById("hud-unit")) {
          document.getElementById("hud-unit").textContent = owned.find((f) => f.id === activeFleetId)?.unit_type || fleet.unit_type || "—";
        }
      }
    } catch (_e) {
      // ignore
    }
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
        btn.dataset.x = String(c.x);
        btn.dataset.y = String(c.y);
        btn.dataset.z = String(c.z);

        const hasObjects = c.flags && c.flags.has_objects;
        const isCenter = c.flags && c.flags.is_center;
        const isVisible = c.flags && c.flags.is_visible;
        const fogState = c.flags && c.flags.fog_state ? String(c.flags.fog_state) : null;
        const zoneVisionSelf = Boolean(c.flags && c.flags.zone_vision_self);
        const zoneBuildSelf = Boolean(c.flags && c.flags.zone_build_self);
        const zoneBuildEnemy = Boolean(c.flags && c.flags.zone_build_enemy);
        const planetObj = (c.objects || []).find((o) => o.type === "planet");
        const anyFleetObj = (c.objects || []).find((o) => o.type === "fleet");
        const buildingObj = (c.objects || []).find((o) => o.type === "building");
        const hasAnyFleet = Boolean(anyFleetObj);
        const isEnemyFleet = anyFleetObj && playerId && anyFleetObj.owner && anyFleetObj.owner !== playerId;
        const isEnemyPlanet = planetObj && playerId && planetObj.owner && planetObj.owner !== playerId;

        if (hasObjects) btn.classList.add("cell-object");
        if (isCenter) btn.classList.add("cell-center");
        if (hasAnyFleet) btn.classList.add("cell-unit", "cell-current");
        if (zoneVisionSelf) btn.classList.add("zone-vision-self");
        if (zoneBuildEnemy) btn.classList.add("zone-build-enemy");
        if (zoneBuildSelf) btn.classList.add("zone-build-self");
        if (!isVisible) {
          if (fogState === "memory") btn.classList.add("cell-memory");
          else if (fogState === "stale") btn.classList.add("cell-stale");
          else btn.classList.add("cell-fog");
        }
        if (isEnemyFleet || isEnemyPlanet) btn.classList.add("cell-enemy");
        if ((hasAnyFleet || planetObj) && !isEnemyFleet && !isEnemyPlanet && playerId) btn.classList.add("cell-ally");
        if (c.terrain === "anomaly") btn.classList.add("cell-unknown");
        if (lastTarget && c.x === lastTarget.x && c.y === lastTarget.y && c.z === lastTarget.z) {
          btn.classList.add("cell-target", "move-target");
        }
        if (selectedCell && c.x === selectedCell.x && c.y === selectedCell.y && c.z === selectedCell.z) {
          btn.classList.add("cell-selected");
        }
        if (pendingFleetMove && c.x === pendingFleetMove.from.x && c.y === pendingFleetMove.from.y && c.z === pendingFleetMove.from.z) {
          btn.classList.add("cell-from");
        }
        if (pendingFleetMove && c.x === pendingFleetMove.to.x && c.y === pendingFleetMove.to.y && c.z === pendingFleetMove.to.z) {
          btn.classList.add("cell-to");
        }

        const terrainIcon =
          c.terrain === "asteroids"
            ? "<span class='terrain-icon'>☄</span>"
            : c.terrain === "nebula"
              ? "<span class='terrain-icon'>🌫</span>"
              : c.terrain === "ruins"
                ? "<span class='terrain-icon'>🏚</span>"
                : c.terrain === "anomaly"
                  ? "<span class='terrain-icon'>❓</span>"
                  : c.terrain === "fog" && c.glyph === "?"
                    ? "<span class='terrain-icon muted'>?</span>"
                    : "";
        const moving = worldState && worldState.fleet && worldState.fleet.status === "moving";
        const ao = worldState && worldState.fleet ? worldState.fleet.active_order : null;
        const isFromCell =
          moving && ao && c.x === ao.from_x && c.y === ao.from_y && c.z === (ao.from_z ?? 0);

        const isHomeCell = Boolean(home && c.z === 0 && c.x === home.x && c.y === home.y);
        const planetMarker = planetObj || isHomeCell
          ? `<span class="planet-icon ${isEnemyPlanet ? "enemy" : "ally"}" aria-label="Планета">🪐</span>`
          : null;

        const fleetIcon = anyFleetObj && anyFleetObj.unit_type === "fighter" ? "🚀" : "🛰";
        const fleetMarker = hasAnyFleet && !isFromCell
          ? `<span class='unit-icon ${isEnemyFleet ? "enemy" : ""}' aria-label='Флот'>${fleetIcon}</span>`
          : null;

        // Центр окна — это только рамка (cell-center), не "планета".
        const buildingMarker = buildingObj
          ? `<span class="terrain-icon" aria-label="Постройка">${buildingObj.building_type === "mine" ? "⛏" : (buildingObj.building_type === "reactor" ? "⚙" : "💎")}</span>`
          : null;

        const marker = planetMarker || fleetMarker || buildingMarker || terrainIcon;
        const markerHtml = marker ? `<div>${marker}</div>` : "<div class='marker-spacer'></div>";
        const showCoord = Boolean(hasObjects || terrainIcon);
        const coordHtml = showCoord ? `<div class='coord'>${c.x},${c.y}</div>` : "<div class='coord'></div>";

        // Клики по краям окна двигают карту. Стрелки рисуем поверх содержимого клетки.
        const winCenter = currentWindow && currentWindow.center ? currentWindow.center : viewCenter;
        const r = currentWindow && Number.isInteger(currentWindow.radius) ? currentWindow.radius : 4;
        const x0 = winCenter.x - r;
        const x1 = winCenter.x + r;
        const y0 = winCenter.y - r;
        const y1 = winCenter.y + r;
        const isLeft = c.x === x0;
        const isRight = c.x === x1;
        const isTop = c.y === y0;
        const isBottom = c.y === y1;
        const isEdge = isLeft || isRight || isTop || isBottom;
        let arrow = "";
        if (isEdge) {
          if (isLeft && isTop) arrow = "↖";
          else if (isRight && isTop) arrow = "↗";
          else if (isLeft && isBottom) arrow = "↙";
          else if (isRight && isBottom) arrow = "↘";
          else if (isLeft) arrow = "←";
          else if (isRight) arrow = "→";
          else if (isTop) arrow = "↑";
          else if (isBottom) arrow = "↓";
        }
        const arrowHtml = arrow
          ? `<div class="pan-arrow ${arrow.length > 1 ? "corner" : ""}">${arrow}</div>`
          : "";

        btn.innerHTML = `<div class="cell-inner">${arrowHtml}${markerHtml}${coordHtml}</div>`;
        btn.title = `Сектор (${c.x}, ${c.y}, z=${c.z})`;

        // Drag & drop: перетащить флот на целевую клетку без лишних кликов.
        // Перетаскивать можно только СВОЙ флот.
        const canDragFleet = Boolean(anyFleetObj && playerId && anyFleetObj.owner === playerId);
        if (canDragFleet) {
          btn.draggable = true;
          btn.classList.add("cell-draggable");
          btn.addEventListener("dragstart", (e) => {
            try {
              e.dataTransfer.setData(
                "text/plain",
                JSON.stringify({ fleet_id: anyFleetObj.id, qty: anyFleetObj.qty, from: { x: c.x, y: c.y, z: c.z } }),
              );
              e.dataTransfer.effectAllowed = "move";
            } catch (_err) {
              // ignore
            }
          });
        }

        btn.addEventListener("dragover", (e) => {
          e.preventDefault();
          btn.classList.add("cell-drop");
        });
        btn.addEventListener("dragleave", () => btn.classList.remove("cell-drop"));
        btn.addEventListener("drop", async (e) => {
          e.preventDefault();
          btn.classList.remove("cell-drop");
          try {
            const raw = e.dataTransfer.getData("text/plain");
            const data = raw ? JSON.parse(raw) : null;
            if (data && data.fleet_id) {
              // Защита от случайного "ОК" сразу после drop: кнопка OK будет включена с задержкой.
              await openFleetMoveConfirm({
                fleet_id: data.fleet_id,
                qty: data.qty || 0,
                from: data.from,
                to: { x: c.x, y: c.y, z: c.z },
                destCell: c,
                deferOkMs: 450,
              });
              return;
            }
          } catch (_err) {
            // ignore
          }
          await moveScout(c.x, c.y, c.z);
        });

        // Click still selects for panel/ETA
        btn.addEventListener("click", () => {
          if (isEdge) {
            const step = r * 2; // двигаемся "окнами" без перекрытия
            const dx = isLeft ? -step : isRight ? step : 0;
            const dy = isTop ? -step : isBottom ? step : 0;
            viewCenter = { x: winCenter.x + dx, y: winCenter.y + dy };
            refreshWindow();
            return;
          }
          selectedCell = { ...c };
          updateSelectedPanel();
          loadSectorDetails(c.x, c.y, c.z);
          renderMap();
        });
        rowEl.appendChild(btn);
      }
      mapEl.appendChild(rowEl);
    }
    renderFlightOverlay();
  };

  const getCellCenter = (x, y, z) => {
    if (!mapEl || !mapWrapEl) return null;
    const el = mapEl.querySelector(`button.cell[data-x='${x}'][data-y='${y}'][data-z='${z}']`);
    if (!el) return null;
    const r1 = el.getBoundingClientRect();
    const r2 = mapWrapEl.getBoundingClientRect();
    // координаты внутри viewport скролл-контейнера
    return { cx: r1.left - r2.left + r1.width / 2, cy: r1.top - r2.top + r1.height / 2 };
  };

  const renderFlightOverlay = () => {
    if (!flightOverlayEl || !mapEl || !mapWrapEl) return;
    // clear
    flightOverlayEl.innerHTML = "";

    const w = mapWrapEl.clientWidth;
    const h = mapWrapEl.clientHeight;
    flightOverlayEl.setAttribute("viewBox", `0 0 ${w} ${h}`);
    flightOverlayEl.setAttribute("width", String(w));
    flightOverlayEl.setAttribute("height", String(h));

    const ns = "http://www.w3.org/2000/svg";

    const fleets = worldState && Array.isArray(worldState.fleets)
      ? worldState.fleets
      : (worldState && worldState.fleet ? [worldState.fleet] : []);

    const moving = fleets.filter((f) => f && f.status === "moving" && f.active_order);
    if (!moving.length) return;

    for (const f of moving) {
      const ao = f.active_order;
      const from = getCellCenter(ao.from_x, ao.from_y, ao.from_z ?? 0);
      const to = getCellCenter(ao.target_x, ao.target_y, ao.target_z ?? 0);
      if (!from || !to) continue;

      const travelTicks = Number.isInteger(ao.travel_ticks)
        ? ao.travel_ticks
        : Math.max(1, Math.abs(ao.target_x - ao.from_x) + Math.abs(ao.target_y - ao.from_y));
      const remaining = Number.isInteger(ao.remaining_ticks) ? ao.remaining_ticks : 0;
      const done = Math.max(0, Math.min(travelTicks, travelTicks - remaining));
      const t = travelTicks === 0 ? 0 : done / travelTicks;

      const x = from.cx + (to.cx - from.cx) * t;
      const y = from.cy + (to.cy - from.cy) * t;

      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", String(from.cx));
      line.setAttribute("y1", String(from.cy));
      line.setAttribute("x2", String(to.cx));
      line.setAttribute("y2", String(to.cy));
      line.setAttribute("class", "flight-line");

      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(y));
      dot.setAttribute("r", "6");
      dot.setAttribute("class", "flight-dot");

      flightOverlayEl.appendChild(line);
      flightOverlayEl.appendChild(dot);
    }
  };

  if (mapWrapEl) {
    mapWrapEl.addEventListener("scroll", () => {
      renderFlightOverlay();
    });
  }

  // drag-pan removed

  const refreshWindow = async () => {
    const r = await fetch(`/api/world/window?radius=4&z=${currentZ}&center_x=${viewCenter.x}&center_y=${viewCenter.y}`);
    if (!r.ok) {
      setStatus("Ошибка загрузки карты", "err");
      return;
    }
    currentWindow = await r.json();
    if (currentWindow && currentWindow.center) viewCenter = { ...currentWindow.center };
    renderMap();
    await loadWorldState();
  };

  const moveScout = async (x, y, z) => {
    setStatus("Отправка...");
    try {
      const r = await fetch("/api/units/move_scout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z }),
      });
      const body = await r.json();

      if (r.status === 400) {
        const msg = body.error || body.message || "bad_request";
        setStatus(`Ошибка: ${msg}`, "err");
        return;
      }

      if (r.status === 200 && body.ok) {
        lastTarget = { x, y, z };
        await refreshWindow();
        setStatus(`Успешно: (${x},${y},${z})`, "ok");
        return;
      }

      const msg = body.error || body.message || `http_${r.status}`;
      setStatus(`Ошибка: ${msg}`, "err");
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const moveFleet = async (fleetId, x, y, z) => {
    setStatus("Отправка флота...");
    try {
      const r = await fetch("/api/fleets/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId, x, y, z }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "not_enough_fuel") {
          setStatus(`Ошибка: not_enough_fuel (нужно ${body.need}, есть ${body.have})`, "err");
          return;
        }
        if (body.error === "active_order_exists") {
          const f = worldState && worldState.fleet && worldState.fleet.id === fleetId ? worldState.fleet : null;
          const ao = f && f.active_order ? f.active_order : null;
          const hint = ao ? `Уже летит в (${ao.target_x},${ao.target_y},${ao.target_z}), осталось ${ao.remaining_ticks} тиков.` : "Флот уже в пути.";
          setStatus(`Ошибка: active_order_exists. ${hint} Можно отменить приказ.`, "err");
        } else {
          setStatus(`Ошибка: ${body.error || "fleet_move_failed"}`, "err");
        }
        return;
      }
      lastTarget = { x, y, z };
      await refreshWindow();
      setStatus(`Флот в пути: ETA ${body.travel_ticks} тиков`, "ok");
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const cancelFleetOrder = async (fleetId) => {
    setStatus("Отмена приказа...");
    try {
      const r = await fetch("/api/fleets/cancel_order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "cancel_failed"}`, "err");
        return;
      }
      setStatus("Приказ отменён", "ok");
      await refreshWindow();
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const describeDestination = (cell) => {
    if (!cell) return { label: "неизвестно", warn: "" };
    const objs = cell.objects || [];
    const hasPlanet = objs.some((o) => o.type === "planet");
    const hasFleet = objs.some((o) => o.type === "fleet");

    let label = "пусто";
    if (hasPlanet) label = "планета";
    else if (hasFleet) label = "флот";
    else if (cell.terrain === "asteroids") label = "астероиды";
    else if (cell.terrain === "nebula") label = "туманность";
    else if (cell.terrain === "ruins") label = "руины";
    else if (cell.terrain === "anomaly") label = "неизведанно/аномалия";

    let warn = "";
    if (cell.terrain === "anomaly") warn = "НЕ ЛЕТИ ТУДА: высокий риск (аномалия).";
    return { label, warn };
  };

  const openFleetMoveConfirm = async ({ fleet_id, qty, from, to, destCell, deferOkMs }) => {
    if (!overlayEl) return;
    const distance = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
    const travelTicks = Math.max(1, distance);
    const currentTick = Number.isInteger(worldState.current_tick) ? worldState.current_tick : 0;
    const arriveTick = currentTick + travelTicks;
    // MVP топливо: distance * qty (формула должна совпадать с сервером)
    const fuelCost = Math.max(0, distance) * Math.max(1, Number(qty) || 1);
    const dest = describeDestination(destCell);

    pendingFleetMove = {
      fleet_id,
      qty: Number(qty) || 0,
      from,
      to,
      distance,
      travelTicks,
      arriveTick,
      fuelCost,
      destLabel: dest.label,
      warn: dest.warn,
    };
    if (cfFromEl) cfFromEl.textContent = `${from.x},${from.y},${from.z}`;
    if (cfToEl) cfToEl.textContent = `${to.x},${to.y},${to.z}`;
    if (cfEtaEl) cfEtaEl.textContent = `${travelTicks} тиков`;
    if (cfArriveEl) cfArriveEl.textContent = `тик ${arriveTick}`;
    if (cfFuelEl) cfFuelEl.textContent = String(fuelCost);
    if (cfDestEl) cfDestEl.textContent = dest.label;
    if (cfWarnEl) cfWarnEl.textContent = dest.warn || "";

    if (cfOkBtn) {
      const ms = Number.isFinite(Number(deferOkMs)) ? Number(deferOkMs) : 0;
      if (ms > 0) {
        cfOkBtn.disabled = true;
        setTimeout(() => {
          try {
            cfOkBtn.disabled = false;
          } catch (_e) {
            // ignore
          }
        }, ms);
      } else {
        cfOkBtn.disabled = false;
      }
    }

    overlayEl.classList.remove("hidden");
    renderMap();
  };

  const closeFleetMoveConfirm = () => {
    if (!overlayEl) return;
    overlayEl.classList.add("hidden");
    pendingFleetMove = null;
    renderMap();
  };

  if (cfCancelBtn) cfCancelBtn.addEventListener("click", closeFleetMoveConfirm);
  if (overlayEl) {
    overlayEl.addEventListener("click", (e) => {
      if (e.target === overlayEl) closeFleetMoveConfirm();
    });
  }
  if (cfOkBtn) {
    cfOkBtn.addEventListener("click", async () => {
      if (!pendingFleetMove) return;
      const m = pendingFleetMove;
      closeFleetMoveConfirm();
      await moveFleet(m.fleet_id, m.to.x, m.to.y, m.to.z);
    });
  }

  // Быстрая отмена активного приказа из окна подтверждения
  if (cfCancelBtn) {
    cfCancelBtn.addEventListener("contextmenu", async (e) => {
      e.preventDefault();
      if (!pendingFleetMove) return;
      await cancelFleetOrder(pendingFleetMove.fleet_id);
      closeFleetMoveConfirm();
    });
  }

  if (flyBtn) {
    flyBtn.addEventListener("click", async () => {
      if (!selectedCell) return;
      if (!activeFleetId) {
        setStatus("Нет активного флота для движения", "err");
        return;
      }
      await moveFleet(activeFleetId, selectedCell.x, selectedCell.y, selectedCell.z);
    });
  }

  if (fleetSelectEl) {
    fleetSelectEl.addEventListener("change", () => {
      activeFleetId = fleetSelectEl.value || null;
      updateSelectedPanel();
    });
  }
  if (clearSelBtn) {
    clearSelBtn.addEventListener("click", () => {
      selectedCell = null;
      updateSelectedPanel();
      renderMap();
    });
  }

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


  if (manualTickBtn) manualTickBtn.addEventListener("click", doManualTick);

  if (autotickToggle) {
    autotickToggle.addEventListener("change", async () => {
      try {
        const r = await fetch("/api/world/autotick", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: Boolean(autotickToggle.checked) }),
        });
        const body = await r.json();
        if (!r.ok || !body.ok) {
          setStatus(`Ошибка автотика: ${body.error || "autotick_failed"}`, "err");
          await loadWorldState();
          return;
        }
        setStatus(`Автотик: ${body.auto_tick_enabled ? "ON" : "OFF"}`, "ok");
        await loadWorldState();
      } catch (_e) {
        setStatus("Ошибка: network_error", "err");
      }
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
  loadWorldState();
  updateSelectedPanel();

  if (homeBtn) {
    homeBtn.addEventListener("click", () => {
      if (!home) return;
      viewCenter = { x: home.x, y: home.y };
      refreshWindow();
    });
  }

  // При серверных автотиках интерфейс должен жить сам.
  // Обновляем state + карту раз в несколько секунд.
  setInterval(() => {
    refreshWindow();
    loadWorldState();
  }, 3000);
})();
