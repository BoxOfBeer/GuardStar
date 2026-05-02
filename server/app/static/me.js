(function () {
  const dataEl = document.getElementById("initial-data");
  if (!dataEl) return;

  const initial = JSON.parse(dataEl.textContent || "{}");
  let currentWindow = initial.window;
  let currentZ = Number.isInteger(initial.z) ? initial.z : 0;
  const home = initial.home || { x: 0, y: 0 };
  const playerId = initial.player || null;
  /** Резерв если баланс ещё не подгрузился. Реальный список типов берётся из `aliases.unit_aliases` в `/api/balance`. */
  const DEFAULT_FLEET_QTY_KEYS = ["scout", "fighter", "engineer"];
  const DEFAULT_FLEET_UNIT_LABELS = {
    scout: "Разведчик",
    fighter: "Истребитель",
    engineer: "Инженер",
    corvette: "Корвет",
    supplier: "Снабженец",
    freighter: "Фрахтовщик",
  };
  const TERRAIN_RU = {
    empty: "Пустой космос",
    planet: "Планета",
    asteroids: "Поле астероидов",
    nebula: "Туманность",
    ruins: "Руины",
    anomaly: "Аномалия",
    fog: "Туман войны",
  };
  const STATUS_RU = { idle: "ожидание", moving: "в пути" };
  const formatTerrainRu = (t) => (t && TERRAIN_RU[t]) || (t ? String(t) : "—");
  const ruOrderType = (t) => {
    if (!t) return "приказ";
    if (t === "move") return "перелёт";
    if (t === "emergency_return") return "аварийный возврат";
    return String(t);
  };
  const formatInfluenceHud = (inf) => {
    if (!inf || typeof inf !== "object") return "—";
    const controlOwnerName =
      inf.control?.owner_name != null
        ? String(inf.control.owner_name)
        : inf.home_control_owner_name != null
          ? String(inf.home_control_owner_name)
          : null;
    const controlOwnerId =
      inf.control?.owner != null
        ? String(inf.control.owner)
        : inf.home_control_owner != null
          ? String(inf.home_control_owner)
          : null;
    const yourValueRaw =
      typeof inf.control?.your_value === "number"
        ? inf.control.your_value
        : typeof inf.home_control_your_value === "number"
          ? inf.home_control_your_value
          : null;
    const topValueRaw =
      typeof inf.control?.top_value === "number"
        ? inf.control.top_value
        : typeof inf.home_control_top_value === "number"
          ? inf.home_control_top_value
          : null;
    const captureThreshold =
      typeof inf.control?.capture_threshold === "number" ? inf.control.capture_threshold : 1.0;
    const ownerShort = controlOwnerName || (controlOwnerId ? `${controlOwnerId.slice(0, 8)}…` : "нейтрал");
    const cap = 5.0;
    const yv = yourValueRaw != null ? Number(yourValueRaw) : 0;
    const tv = topValueRaw != null ? Number(topValueRaw) : 0;
    const yourValue = yv > cap ? `${cap.toFixed(1)}+` : yv.toFixed(2);
    const topValue = tv > cap ? `${cap.toFixed(1)}+` : tv.toFixed(2);
    const contested = Boolean(inf.contested ?? inf.home_contested);
    // На сервере control_value накапливается тиками и может быть ≫ 1 — это не «проценты клетки», а накопленный вес.
    const thr = captureThreshold.toFixed(1);
    const tail = contested ? " • спор зон" : "";
    if (!controlOwnerId) {
      return `накопление контроля: нейтрально • ваш вклад ${yourValue} • лидер ${topValue} • порог захвата ${thr}${tail}`;
    }
    return `накопление контроля: ${ownerShort} • ваш вклад ${yourValue} • лидер ${topValue} • порог захвата ${thr}${tail}`;
  };
  const formatGlyphRu = (terrain, g) => {
    if (g === "" || g === undefined || g === null) return "—";
    if (terrain === "empty" && (g === "." || g === "·")) return "нет (пусто)";
    return `знак «${g}»`;
  };
  const ruFleetStatus = (s) => (s && STATUS_RU[s]) || (s ? String(s) : "—");
  /** Склонение числа игровых солей (1 сол, 2–4 сола, иначе солов). */
  const solWord = (n) => {
    const v = Math.abs(Number(n)) || 0;
    const x = v % 100;
    const z = v % 10;
    if (x >= 11 && x <= 14) return "солов";
    if (z === 1) return "сол";
    if (z >= 2 && z <= 4) return "сола";
    return "солов";
  };
  let viewCenter = (currentWindow && currentWindow.center) ? { ...currentWindow.center } : { ...home };
  const MAP_VIEW_RADIUS_KEY = "gs.map.viewRadius";
  const readSavedMapRadius = () => {
    try {
      const n = parseInt(String(localStorage.getItem(MAP_VIEW_RADIUS_KEY) || ""), 10);
      if (n === 4 || n === 10) return n;
    } catch (_e) {
      /* ignore */
    }
    return null;
  };
  let viewRadius =
    readSavedMapRadius() ??
    (currentWindow && Number.isInteger(currentWindow.radius) ? currentWindow.radius : 4); // 4 => 9×9, 10 => 21×21
  let lastTarget = null;
  let selectedCell = null;
  let worldState = { current_tick: 0, current_sol: 0, fleet: null, events: [], player_id: playerId };
  // Подсказка по линии снабжения для выбранной клетки (для подсветки "обрыва" на карте).
  let supplyHint = null; // { for:{x,y,z}, inSupply:boolean, routeClear:boolean, blockedAt:{x,y} | null }

  const mapEl = document.getElementById("map-grid");
  const mapWrapEl = document.querySelector(".map-wrap");
  const mapLayerEl = document.querySelector(".map-layer");
  const flightOverlayEl = document.getElementById("flight-overlay");
  const zoneOverlayEl = document.getElementById("zone-overlay");
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
  const selInfluenceEl = document.getElementById("sel-influence");
  const selSupplyEl = document.getElementById("sel-supply");
  const hudInfluenceHomeEl = document.getElementById("hud-influence-home");
  const selDistanceEl = document.getElementById("sel-distance");
  const selTravelEl = document.getElementById("sel-travel");
  const selArriveEl = document.getElementById("sel-arrive");
  const flyBtn = document.getElementById("fly-btn");
  const buildBtn = document.getElementById("build-btn");
  const discoveryResolveBtn = document.getElementById("discovery-resolve-btn");
  const clearSelBtn = document.getElementById("clear-sel-btn");
  const eventsEl = document.getElementById("events");
  const planetModalOverlay = document.getElementById("planet-modal-overlay");
  const planetModalBody = document.getElementById("planet-modal-body");
  const planetModalTitle = document.getElementById("planet-modal-title");
  const planetModalClose = document.getElementById("planet-modal-close");
  const fleetModalOverlay = document.getElementById("fleet-modal-overlay");
  const fleetModalBody = document.getElementById("fleet-modal-body");
  const fleetModalTitle = document.getElementById("fleet-modal-title");
  const fleetModalClose = document.getElementById("fleet-modal-close");
  const fleetEditBtn = document.getElementById("fleet-edit-btn");
  const fleetLocateBtn = document.getElementById("fleet-locate-btn");
  const fleetCreateOverlay = document.getElementById("fleet-create-overlay");
  const fleetCreateBody = document.getElementById("fleet-create-body");
  const fleetCreateTitle = document.getElementById("fleet-create-title");
  const fleetCreateClose = document.getElementById("fleet-create-close");
  const fleetSubOverlay = document.getElementById("fleet-sub-overlay");
  const fleetSubTitle = document.getElementById("fleet-sub-title");
  const fleetSubBody = document.getElementById("fleet-sub-body");
  const fleetSubFoot = document.getElementById("fleet-sub-foot");
  const fleetSubClose = document.getElementById("fleet-sub-close");
  const techModalOverlay = document.getElementById("tech-modal-overlay");
  const techModalBody = document.getElementById("tech-modal-body");
  const techModalOpenBtn = document.getElementById("tech-modal-open");
  const techModalCloseBtn = document.getElementById("tech-modal-close");
  const economyModalOverlay = document.getElementById("economy-modal-overlay");
  const economyModalBody = document.getElementById("economy-modal-body");
  const economyModalOpenBtn = document.getElementById("economy-modal-open");
  const economyModalCloseBtn = document.getElementById("economy-modal-close");
  const uiSettingsBtn = document.getElementById("ui-settings-btn");
  const uiSettingsOverlay = document.getElementById("ui-settings-overlay");
  const uiSettingsClose = document.getElementById("ui-settings-close");
  const uiSettingsReset = document.getElementById("ui-settings-reset");
  const uiFontSize = document.getElementById("ui-font-size");
  const uiLineHeight = document.getElementById("ui-line-height");
  const uiFontSizeLabel = document.getElementById("ui-font-size-label");
  const uiLineHeightLabel = document.getElementById("ui-line-height-label");
  const uiBattleRadius = document.getElementById("ui-battle-radius");
  const uiBattleRadiusLabel = document.getElementById("ui-battle-radius-label");
  const uiForceAttack = document.getElementById("ui-force-attack");
  const combatPromptOverlay = document.getElementById("combat-prompt-overlay");
  const cpSummary = document.getElementById("cp-summary");
  const cpCountdown = document.getElementById("cp-countdown");
  const cpPreview = document.getElementById("cp-preview");
  const cpAttackBtn = document.getElementById("cp-attack");
  const cpDeclineBtn = document.getElementById("cp-decline");
  const topMetalEl = document.getElementById("top-metal");
  const topCrystalEl = document.getElementById("top-crystal");
  const topEnergyEl = document.getElementById("top-energy");
  const topFuelEl = document.getElementById("top-fuel");
  const topFoodEl = document.getElementById("top-food");
  const topWaterEl = document.getElementById("top-water");
  const topRpEl = document.getElementById("top-rp");
  const overlayEl = document.getElementById("confirm-overlay");
  const cfFromEl = document.getElementById("cf-from");
  const cfToEl = document.getElementById("cf-to");
  const cfEtaEl = document.getElementById("cf-eta");
  const cfArriveEl = document.getElementById("cf-arrive");
  const cfFuelEl = document.getElementById("cf-fuel");
  const cfDestEl = document.getElementById("cf-dest");
  const cfWarnEl = document.getElementById("cf-warn");
  const cfCombatEl = document.getElementById("cf-combat");
  const cfOkBtn = document.getElementById("cf-ok");
  const cfCancelBtn = document.getElementById("cf-cancel");
  const fleetSelectEl = document.getElementById("fleet-select");
  const homeBtn = document.getElementById("home-btn");

  // Панорамирование мышью отключено — используем только стрелки по краям поля.

  const UI_SETTINGS_KEY = "guardstar.ui.settings.v1";
  const applyUiSettings = (s) => {
    const root = document.documentElement;
    const fs = Number(s && s.fontSize);
    const lh = Number(s && s.lineHeight);
    if (Number.isFinite(fs)) root.style.setProperty("--ui-font-size", `${fs}px`);
    if (Number.isFinite(lh)) root.style.setProperty("--ui-line-height", String(lh));
    if (uiFontSizeLabel && Number.isFinite(fs)) uiFontSizeLabel.textContent = `${fs}px`;
    if (uiLineHeightLabel && Number.isFinite(lh)) uiLineHeightLabel.textContent = `${lh}`;
  };
  const loadUiSettings = () => {
    try {
      const raw = localStorage.getItem(UI_SETTINGS_KEY);
      const s = raw ? JSON.parse(raw) : null;
      const fontSize = Number.isFinite(Number(s && s.fontSize)) ? Number(s.fontSize) : 14;
      const lineHeight = Number.isFinite(Number(s && s.lineHeight)) ? Number(s.lineHeight) : 1.35;
      let battleFocusRadius = Number.isFinite(Number(s && s.battleFocusRadius)) ? Number(s.battleFocusRadius) : 6;
      battleFocusRadius = Math.min(10, Math.max(3, Math.round(battleFocusRadius)));
      const forceAttackGuaranteed = Boolean(s && s.forceAttackGuaranteed);
      return { fontSize, lineHeight, battleFocusRadius, forceAttackGuaranteed };
    } catch (_e) {
      return { fontSize: 14, lineHeight: 1.35, battleFocusRadius: 6, forceAttackGuaranteed: false };
    }
  };
  const saveUiSettings = (s) => {
    try {
      localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(s));
    } catch (_e) {
      // ignore
    }
  };
  const syncUiSettingsControls = (s) => {
    if (uiFontSize) uiFontSize.value = String(s.fontSize);
    if (uiLineHeight) uiLineHeight.value = String(s.lineHeight);
    if (uiBattleRadius) uiBattleRadius.value = String(s.battleFocusRadius ?? 6);
    if (uiBattleRadiusLabel && Number.isFinite(s.battleFocusRadius)) uiBattleRadiusLabel.textContent = String(s.battleFocusRadius);
    if (uiForceAttack) uiForceAttack.checked = Boolean(s.forceAttackGuaranteed);
    applyUiSettings(s);
  };

  // init UI settings early
  const initialUiSettings = loadUiSettings();
  applyUiSettings(initialUiSettings);

  let pendingFleetMove = null; // { fleet_id, from:{x,y,z}, to:{x,y,z}, qty, distance, travelTicks, arriveTick, fuelCost, destLabel, warn }
  let activeFleetId = null;
  let combatPromptOpenForOrderId = null;
  let combatPromptExpiresAtMs = null;
  let combatPromptCountdownTimer = null;

  const pickedFleetForHud = () => {
    const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
    if (activeFleetId) {
      const hit = fleets.find((f) => f && f.id === activeFleetId);
      if (hit) return hit;
    }
    return worldState && worldState.fleet ? worldState.fleet : null;
  };

  const engineerFleetsForCell = (cell) => {
    if (!cell) return [];
    const out = [];
    const seen = new Set();
    for (const o of cell.objects || []) {
      if (
        o &&
        o.type === "fleet" &&
        String(o.owner) === String(playerId) &&
        o.composition &&
        Number(o.composition.engineer || 0) > 0
      ) {
        out.push(o);
        if (o.id) seen.add(String(o.id));
      }
    }
    const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
    for (const f of fleets) {
      if (!f || !f.id || seen.has(String(f.id))) continue;
      if (
        f.x === cell.x &&
        f.y === cell.y &&
        f.z === cell.z &&
        f.composition &&
        Number(f.composition.engineer || 0) > 0
      ) {
        out.push(f);
        seen.add(String(f.id));
      }
    }
    return out;
  };

  const engineerFleetForCell = (cell) => {
    const arr = engineerFleetsForCell(cell);
    return arr.length ? arr[0] : null;
  };

  const escHtml = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");

  /** Общий кэш `/api/balance` (переиспользуется исследованиями, и составом флота). */
  const fetchBalanceCached = async () => {
    if (!window.__guardstarBalanceCache)
      window.__guardstarBalanceCache = { ts: 0, body: null, backoffUntil: 0 };
    const cache = window.__guardstarBalanceCache;
    const now = Date.now();
    if (cache.backoffUntil && now < cache.backoffUntil) return cache.body;
    let balBody = cache.body;
    if (!balBody || now - cache.ts > 30000) {
      const balResp = await fetch("/api/balance");
      balBody = await balResp.json();
      cache.ts = now;
      cache.body = balBody;
      if (!balResp.ok || !balBody || !balBody.ok) cache.backoffUntil = now + 15000;
      else cache.backoffUntil = 0;
    }
    return balBody;
  };

  const fleetLogicalKeysBalanceOnly = () => {
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok) return DEFAULT_FLEET_QTY_KEYS.slice();
    const ua = bb.aliases && bb.aliases.unit_aliases;
    if (!ua || typeof ua !== "object") return DEFAULT_FLEET_QTY_KEYS.slice();
    const keys = Object.keys(ua).filter((k) => typeof k === "string" && k.trim());
    return keys.length ? keys.sort((a, b) => a.localeCompare(b)) : DEFAULT_FLEET_QTY_KEYS.slice();
  };

  /** Строки в модалке флота: все алиасы из баланса + типы с ненулевым количеством в текущем составе. */
  const fleetQtyKeysForUi = (comp) => {
    const merged = new Set(fleetLogicalKeysBalanceOnly());
    if (comp && typeof comp === "object") {
      for (const [k, raw] of Object.entries(comp)) {
        if (!k) continue;
        if (Number(raw) > 0) merged.add(String(k));
      }
    }
    return Array.from(merged).sort((a, b) => a.localeCompare(b));
  };

  const fleetUnitLabel = (logicalKey) => {
    const k = String(logicalKey || "");
    if (!k) return k;
    if (DEFAULT_FLEET_UNIT_LABELS[k]) return DEFAULT_FLEET_UNIT_LABELS[k];
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok) return k;
    const ua = bb.aliases && bb.aliases.unit_aliases;
    const uid =
      ua && typeof ua === "object" && Object.prototype.hasOwnProperty.call(ua, k)
        ? ua[k]
        : null;
    if (!uid || typeof uid !== "string") return k;
    const units = Array.isArray(bb.units) ? bb.units : [];
    let hit = units.find((u) => u && String(u.id) === String(uid));
    if (!hit) hit = units.find((u) => u && String(u.id) === String(k));
    const nm = hit && typeof hit.name === "string" && hit.name.trim() ? hit.name.trim() : null;
    return nm || k;
  };

  const formatComposition = (com) => {
    if (!com || typeof com !== "object") return "";
    const parts = Object.entries(com).filter(([, q]) => Number(q) > 0);
    if (!parts.length) return "";
    return parts
      .map(([k, q]) => {
        const lab = fleetUnitLabel(k);
        return `${lab}×${q}`;
      })
      .join(" · ");
  };

  const buildingLabelRu = (logicalType) => {
    const k = String(logicalType || "").trim().toLowerCase();
    if (!k) return String(logicalType || "");
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok) return k;
    const ba = bb.aliases && bb.aliases.building_aliases;
    const bid =
      ba && typeof ba === "object" && Object.prototype.hasOwnProperty.call(ba, k)
        ? ba[k]
        : k;
    const buildings = Array.isArray(bb.buildings) ? bb.buildings : [];
    const hit = buildings.find((b) => b && String(b.id) === String(bid));
    return hit && hit.name ? String(hit.name) : k;
  };

  const fleetOptionLabel = (f) => {
    if (!f) return "";
    const nm = (f.name && String(f.name).trim()) || "Флот";
    const cl = formatComposition(f.composition);
    const core = cl || `${f.unit_type || "?"}×${f.qty ?? 0}`;
    return `${nm} — ${core} @ (${f.x},${f.y},${f.z})`;
  };

  const FLEET_UNIT_GLYPH = {
    scout: "🛰",
    fighter: "⚔",
    engineer: "🛠",
    supplier: "📦",
    freighter: "🚚",
    corvette: "🚀",
  };

  const resolveBalanceUnit = (logicalKey) => {
    const k = String(logicalKey || "");
    if (!k) return null;
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok) return null;
    const ua = bb.aliases && bb.aliases.unit_aliases;
    const uid =
      ua && typeof ua === "object" && Object.prototype.hasOwnProperty.call(ua, k) ? ua[k] : k;
    const units = Array.isArray(bb.units) ? bb.units : [];
    return (
      units.find((u) => u && String(u.id) === String(uid)) ||
      units.find((u) => u && String(u.id) === String(k)) ||
      null
    );
  };

  const fleetUnitGlyph = (logicalKey) => FLEET_UNIT_GLYPH[String(logicalKey)] || "⬡";

  const fleetUiRoleGroup = (logicalKey) => {
    const u = resolveBalanceUnit(logicalKey);
    const role = u && u.role ? String(u.role) : "";
    if (role === "scout") return "recon";
    if (role === "combat") return "combat";
    return "tech";
  };

  const unitBuildCostParts = (logicalKey) => {
    const u = resolveBalanceUnit(logicalKey);
    const bc = (u && u.build) || {};
    const cst = bc.cost || {};
    const out = { metal: 0, crystal: 0, energy: 0, fuel: 0 };
    for (const rk of Object.keys(out)) {
      if (typeof cst[rk] === "number") out[rk] = Math.floor(Number(cst[rk]));
    }
    return out;
  };

  const fleetCompositionNet = (cur, newd) => {
    const pay = { metal: 0, crystal: 0, energy: 0, fuel: 0 };
    const refund = { metal: 0, crystal: 0, energy: 0, fuel: 0 };
    const keys = new Set([...Object.keys(cur || {}), ...Object.keys(newd || {})]);
    for (const k of keys) {
      const oldN = Math.max(0, Math.floor(Number((cur || {})[k]) || 0));
      const newN = Math.max(0, Math.floor(Number((newd || {})[k]) || 0));
      const diff = newN - oldN;
      if (diff === 0) continue;
      const cst = unitBuildCostParts(k);
      if (diff > 0) {
        for (const rk of Object.keys(pay)) pay[rk] += (Number(cst[rk]) || 0) * diff;
      } else {
        for (const rk of Object.keys(refund))
          refund[rk] += Math.floor((Number(cst[rk]) || 0) * Math.abs(diff) * 0.5);
      }
    }
    const net = {
      metal: pay.metal - refund.metal,
      crystal: pay.crystal - refund.crystal,
      energy: pay.energy - refund.energy,
      fuel: pay.fuel - refund.fuel,
    };
    return { pay, refund, net };
  };

  const formatImpWarehouseNetHtml = (net) => {
    const parts = [];
    const one = (k, lab) => {
      const v = Math.floor(Number(net[k]) || 0);
      if (!v) return;
      if (v > 0) parts.push(`${lab}: <b>−${v}</b> со склада`);
      else parts.push(`${lab}: <b>+${-v}</b> возврат`);
    };
    one("metal", "Металл");
    one("crystal", "Кристалл");
    one("energy", "Энергия");
    one("fuel", "Топливо");
    return parts.length ? parts.join(" · ") : "Без изменений по складу домашней планеты.";
  };

  const closeFleetSubModal = () => {
    if (fleetSubOverlay) fleetSubOverlay.classList.add("hidden");
    if (fleetSubFoot) fleetSubFoot.innerHTML = "";
    if (fleetSubBody) fleetSubBody.innerHTML = "";
  };

  const openFleetSubModal = ({ title, bodyHtml, confirmLabel, onConfirm }) => {
    if (!fleetSubOverlay || !fleetSubTitle || !fleetSubBody || !fleetSubFoot) return;
    fleetSubTitle.textContent = title;
    fleetSubBody.innerHTML = bodyHtml;
    fleetSubFoot.innerHTML = `<button type="button" class="btn-primary fleet-sub-ok">${escHtml(confirmLabel)}</button><button type="button" class="btn-secondary fleet-sub-cancel">Отмена</button>`;
    const ok = fleetSubFoot.querySelector(".fleet-sub-ok");
    const cancel = fleetSubFoot.querySelector(".fleet-sub-cancel");
    if (cancel) cancel.addEventListener("click", () => closeFleetSubModal());
    if (ok) {
      ok.addEventListener("click", async () => {
        await onConfirm();
      });
    }
    fleetSubOverlay.classList.remove("hidden");
  };

  const setStatus = (text, kind) => {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.remove("ok", "err");
    if (kind) statusEl.classList.add(kind);
  };

  const detectScoutPos = () => {
    const pf = pickedFleetForHud();
    if (pf) return { x: pf.x, y: pf.y, z: pf.z };
    if (!currentWindow || !currentWindow.cells) return { x: home.x, y: home.y, z: currentZ };
    for (const row of currentWindow.cells) {
      for (const c of row.row) {
        const hasOwnedFleet = (c.objects || []).some((o) => o.type === "fleet" && o.owner === playerId);
        if (hasOwnedFleet) return { x: c.x, y: c.y, z: c.z };
      }
    }
    return { x: home.x, y: home.y, z: currentZ };
  };

  const unitLabelCombat = (k) => fleetUnitLabel(k);

  const formatFleetCombatPayloadRu = (p) => {
    if (!p || typeof p !== "object") return "";
    const lines = [];
    const bc = p.battle_calculation;
    if (bc && typeof bc === "object") {
      if (bc.how_score_works) lines.push(String(bc.how_score_works));
      const f = bc.factors || {};
      lines.push(
        `Базовые очки (до броска): атакующий ${f.attacker_base ?? "—"}, защитник ${f.defender_base ?? "—"}`
      );
      const sup = f.supply_zone_bonus || {};
      const zatk = sup.attacker != null ? sup.attacker : f.attacker_supply_zone ? 1.05 : 1;
      const zdef = sup.defender != null ? sup.defender : f.defender_home_zone ? 1.08 : 1;
      lines.push(
        `Множитель территории: атакующий ×${zatk}, защитник ×${zdef} (снабжение +5% / дом +8%)`
      );
      const ar = Array.isArray(f.attacker_research) ? f.attacker_research : [];
      const dr = Array.isArray(f.defender_research) ? f.defender_research : [];
      if (ar.length) {
        lines.push(`Исследования атакующего: ${ar.map((t) => `${t.name} (${t.summary})`).join("; ")}`);
      } else {
        lines.push("Исследования атакующего: нет влияющих на бой.");
      }
      if (dr.length) {
        lines.push(`Исследования защитника: ${dr.map((t) => `${t.name} (${t.summary})`).join("; ")}`);
      } else {
        lines.push("Исследования защитника: нет влияющих на бой.");
      }
      lines.push(
        `После территории: атакующий ≈ ${f.attacker_effective_before_roll ?? f.attacker_effective ?? "—"}, защитник ≈ ${f.defender_effective_before_roll ?? f.defender_effective ?? "—"}`
      );
      const rb = bc.rolls || {};
      if (Object.keys(rb).length) {
        lines.push(
          `Случайный множитель (0.94…1.08): атакующий ×${rb.random_factor_attacker ?? "—"}, защитник ×${rb.random_factor_defender ?? "—"}`
        );
        lines.push(
          `Очки после броска: ${rb.rolled_score_attacker ?? "—"} vs ${rb.rolled_score_defender ?? "—"} (${rb.rule || ""})`
        );
      }
      const comp = bc.composition_start || {};
      if (comp.attacker || comp.defender) {
        lines.push(`Состав атакующего до боя: ${formatComposition(comp.attacker) || "—"}`);
        lines.push(`Состав защитника до боя: ${formatComposition(comp.defender) || "—"}`);
      }
    }
    const cs = p.consequences;
    if (cs && typeof cs === "object") {
      lines.push("Последствия:");
      if (cs.your_fleet_survivors) {
        const y = cs.your_fleet_survivors;
        lines.push(
          `  Потери победителя (вы): −${y.lost_total ?? 0} кораблей` +
            (y.lost_by_type && Object.keys(y.lost_by_type).length
              ? ` (${Object.entries(y.lost_by_type)
                  .map(([k, v]) => `${unitLabelCombat(k)} −${v}`)
                  .join(", ")})`
              : "")
        );
      }
      if (cs.your_fleet_after_battle) {
        const y = cs.your_fleet_after_battle;
        lines.push(`  Потери защитника после боя: −${y.lost_total ?? 0} ед.`);
      }
      if (cs.enemy_survivors_after) {
        const y = cs.enemy_survivors_after;
        lines.push(`  Противник после боя (живые): потери −${y.lost_total ?? "?"}`);
      }
      if (cs.winner_takes_square)
        lines.push(
          `  Клетка захвачена: (${cs.winner_takes_square.x},${cs.winner_takes_square.y},${cs.winner_takes_square.z})`
        );
      if (cs.your_fleet_lost_id) lines.push("  Ваш флот уничтожен.");
      if (cs.destroyed_enemy_fleet_id || cs.enemy_fleet_removed) lines.push("  Противничий флот уничтожен.");
      if (typeof cs.your_ship_loss_fraction_applied === "number")
        lines.push(`  Доля потерь ваших кораблей (победа): ${(cs.your_ship_loss_fraction_applied * 100).toFixed(1)}%`);
      if (typeof cs.ship_loss_fraction_applied === "number")
        lines.push(`  Доля потерь при обороне: ${(cs.ship_loss_fraction_applied * 100).toFixed(1)}%`);
    }
    if (!lines.length) return "";
    return lines.map((ln) => escHtml(ln)).join("\n");
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
      .map((e) => {
        const detail =
          e.type === "fleet_combat" && e.payload
            ? `<div class="event-combat-detail muted" style="margin-top:6px;font-size:88%;white-space:pre-wrap;line-height:1.35;">${formatFleetCombatPayloadRu(e.payload)}</div>`
            : "";
        return `<div class="event"><span class="muted">Сол ${escHtml(e.tick)}</span> — ${escHtml(e.message)}${detail}</div>`;
      })
      .join("");
  };

  const cellHasPlanet = (c) => Boolean(c && Array.isArray(c.objects) && c.objects.some((o) => o && o.type === "planet"));

  const closePlanetModal = () => {
    if (planetModalOverlay) planetModalOverlay.classList.add("hidden");
  };

  const bindBuildButtons = (root, x, y, z, fleetId = null) => {
    if (!root) return;
    const resolveBuildFleetId = () => {
      const sel = root.querySelector("#sector-builder-fleet");
      if (sel && sel.value) return String(sel.value);
      return fleetId;
    };
    for (const btn of root.querySelectorAll("button[data-b]")) {
      btn.addEventListener("click", async () => {
        const bt = btn.getAttribute("data-b");
        await placeBuilding(x, y, z, bt, resolveBuildFleetId());
      });
    }
    for (const btn of root.querySelectorAll("button[data-demolish]")) {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-demolish");
        if (!id || !confirm("Снести эту постройку? Вернётся ~50% стоимости.")) return;
        await dismantleBuilding(id);
      });
    }
    for (const btn of root.querySelectorAll("button[data-bupgrade]")) {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-bupgrade");
        if (!id) return;
        await upgradeBuilding(id);
      });
    }
  };

  const bindOutpostButtons = (root, ctx) => {
    if (!root || !ctx) return;
    const resolveCtxFleetId = () => {
      const sel = root.querySelector("#sector-builder-fleet");
      if (sel && sel.value) return String(sel.value);
      return ctx.fleetId || null;
    };
    for (const btn of root.querySelectorAll("button[data-outpost]")) {
      btn.addEventListener("click", async () => {
        const outpostType = btn.getAttribute("data-outpost");
        await buildOutpost(ctx.x, ctx.y, ctx.z, outpostType, resolveCtxFleetId());
      });
    }
    for (const btn of root.querySelectorAll("button[data-outpost-upgrade]")) {
      btn.addEventListener("click", async () => {
        const outpostId = btn.getAttribute("data-outpost-upgrade");
        await upgradeOutpost(outpostId);
      });
    }
    for (const btn of root.querySelectorAll("button[data-module-install]")) {
      btn.addEventListener("click", async () => {
        const outpostId = btn.getAttribute("data-outpost-id");
        const moduleType = btn.getAttribute("data-module-install");
        await installOutpostModule(outpostId, moduleType);
      });
    }
    for (const btn of root.querySelectorAll("button[data-module-upgrade]")) {
      btn.addEventListener("click", async () => {
        const moduleId = btn.getAttribute("data-module-upgrade");
        await upgradeOutpostModule(moduleId);
      });
    }
  };

  const buildButtonsHtml = () => `
    <div class="build-grid" style="margin-top:10px;">
      <button type="button" class="build-card" data-b="mine"><span class="ic">⛏</span><span>Шахта</span></button>
      <button type="button" class="build-card" data-b="reactor"><span class="ic">⚡</span><span>Реактор</span></button>
      <button type="button" class="build-card" data-b="fuel_depot"><span class="ic">⛽</span><span>Топливник</span></button>
      <button type="button" class="build-card" data-b="crystal_farm"><span class="ic">💎</span><span>Кристаллы</span></button>
      <button type="button" class="build-card" data-b="habitat"><span class="ic">🏠</span><span>Жильё</span></button>
      <button type="button" class="build-card" data-b="basic_farm"><span class="ic">🌾</span><span>Пайок</span></button>
      <button type="button" class="build-card" data-b="basic_water"><span class="ic">💦</span><span>Опреснитель</span></button>
      <button type="button" class="build-card" data-b="research_lab"><span class="ic">🔬</span><span>Лаборатория</span></button>
      <button type="button" class="build-card" data-b="drydock_mini"><span class="ic">🛠</span><span>Мини-верфь</span></button>
      <button type="button" class="build-card" data-b="solar_array"><span class="ic">☀</span><span>Солнечная матрица</span></button>
      <button type="button" class="build-card" data-b="cargo_yard"><span class="ic">📦</span><span>Грузовая</span></button>
      <button type="button" class="build-card" data-b="sensor_mast"><span class="ic">📡</span><span>Сенсоры</span></button>
      <button type="button" class="build-card" data-b="hydro_farm"><span class="ic">🍲</span><span>Гидропоника</span></button>
      <button type="button" class="build-card" data-b="atmospheric_reclaim"><span class="ic">💧</span><span>Вода</span></button>
    </div>
  `;

  const BUILD_MENU_BUTTON_TYPES = [
    "mine",
    "reactor",
    "fuel_depot",
    "crystal_farm",
    "habitat",
    "basic_farm",
    "basic_water",
    "research_lab",
    "drydock_mini",
    "solar_array",
    "cargo_yard",
    "sensor_mast",
    "hydro_farm",
    "atmospheric_reclaim",
  ];

  let showAllBuildOptions = false;

  const TERRAIN_RU_SHORT = {
    empty: "пусто",
    asteroids: "астер.",
    ruins: "руины",
    nebula: "туман.",
    anomaly: "аном.",
  };

  const formatAllowedTerrainsShortRu = (arr) => {
    if (!Array.isArray(arr) || arr.length === 0) return "";
    const pretty = arr.map((t) => (TERRAIN_RU_SHORT[t] ? TERRAIN_RU_SHORT[t] : String(t)));
    return pretty.join("/");
  };

  const updateBuildButtonsAvailability = async (x, y, z, fleetId) => {
    try {
      if (!planetModalBody) return;
      const r = await fetch("/api/buildings/placement_checks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z, fleet_id: fleetId, building_types: BUILD_MENU_BUTTON_TYPES }),
      });
      if (!r.ok) return;
      const body = await r.json();
      if (!body || !body.ok) return;
      const results = body.results || {};
      const btns = planetModalBody.querySelectorAll("button[data-b]");
      for (const btn of btns) {
        const bt = btn.getAttribute("data-b");
        const res = results[bt];
        const showAll = Boolean(showAllBuildOptions);

        // Подпись кнопки: показываем основание + профит (из balance через сервер).
        if (!btn.getAttribute("data-label")) btn.setAttribute("data-label", btn.textContent || bt);
        const baseLabel = btn.getAttribute("data-label") || bt;
        const meta = res && res.meta ? res.meta : null;
        const terrainsRu = meta ? formatAllowedTerrainsShortRu(meta.allowed_terrains) : "";
        const effectsRu = meta && meta.effects_ru ? String(meta.effects_ru) : "";
        const extra = [terrainsRu ? `[${terrainsRu}]` : "", effectsRu && effectsRu !== "—" ? effectsRu : ""]
          .filter(Boolean)
          .join(" ");
        btn.textContent = extra ? `${baseLabel} ${extra}` : baseLabel;

        const nm = meta && meta.name ? String(meta.name) : bt;
        const desc = meta && meta.description ? String(meta.description) : "";
        const baseTipParts = [];
        baseTipParts.push(`${nm}${desc ? " — " + desc : ""}`);
        if (effectsRu && effectsRu !== "—") baseTipParts.push(`Эффект: ${effectsRu}`);
        if (terrainsRu) baseTipParts.push(`Террейн: ${terrainsRu}`);
        const baseTip = baseTipParts.filter(Boolean).join("\n");

        // По умолчанию — показываем только реально доступные варианты.
        // По галочке "Показать все варианты" — показываем весь список (с подсказками).
        if (!showAll && !(res && res.ok)) {
          btn.style.display = "none";
        } else {
          btn.style.display = "";
        }

        if (res && res.ok) {
          btn.disabled = false;
          btn.title = baseTip;
        } else {
          btn.disabled = true;
          const err = res ? res.error : "not_allowed";
          if (err === "wrong_foundation_terrain") {
            const exp = Array.isArray(res.expected) ? res.expected.join(", ") : "—";
            const got = res.terrain ? String(res.terrain) : "—";
            btn.title = [baseTip, `Нужно основание: ${exp}. Сейчас: ${got}.`].filter(Boolean).join("\n");
          } else if (err === "planet_required") {
            btn.title = [baseTip, "Можно построить только в клетке планеты."].filter(Boolean).join("\n");
          } else if (err === "tech_required") {
            const missing = Array.isArray(res.missing_techs) ? res.missing_techs.join(", ") : "—";
            btn.title = [baseTip, `Нужно исследование: ${missing}`].filter(Boolean).join("\n");
          } else if (err === "engineer_required") {
            btn.title = [baseTip, "Нужен ваш флот с инженерами в этой клетке."].filter(Boolean).join("\n");
          } else if (err === "not_enough_engineers") {
            btn.title = [baseTip, "Не хватает инженеров в этом флоте."].filter(Boolean).join("\n");
          } else if (err === "inside_enemy_control_zone") {
            btn.title = [baseTip, "Нельзя: клетка под подтверждённым вражеским контролем."].filter(Boolean).join("\n");
          } else {
            btn.title = [baseTip, `Нельзя: ${err}`].filter(Boolean).join("\n");
          }
        }
      }
    } catch (_e) {
      // ignore UI-only failures
    }
  };

  const refreshSupplyHud = async (cell) => {
    if (!selSupplyEl) return;
    if (!cell || !playerId) {
      selSupplyEl.textContent = "—";
      selSupplyEl.title = "";
      selSupplyEl.classList.remove("hud-warn");
      supplyHint = null;
      return;
    }
    try {
      const z = cell.z ?? 0;
      const r = await fetch(`/api/supply/state?x=${cell.x}&y=${cell.y}&z=${z}`);
      if (!r.ok) {
        selSupplyEl.textContent = "—";
        return;
      }
      const b = await r.json();
      if (!b || !b.ok) {
        selSupplyEl.textContent = "—";
        supplyHint = null;
        return;
      }
      const yes = Boolean(b.in_supply);
      selSupplyEl.textContent = yes ? "есть" : "нет";
      selSupplyEl.classList.toggle("hud-warn", !yes);
      const hub = b.nearest_hub;
      const hx = hub && hub.x != null ? hub.x : "—";
      const hy = hub && hub.y != null ? hub.y : "—";
      const R = b.supply_radius != null ? b.supply_radius : "—";
      const dist = b.distance != null ? b.distance : "—";
      const blk = b.route_blocked_at;
      const blkStr = blk && blk.x != null && blk.y != null ? ` обрыв на (${blk.x},${blk.y})` : "";
      selSupplyEl.title = yes
        ? `Линия снабжения: L-маршрут от хаба (${hx},${hy}), R=${R}, дистанция ${dist}.`
        : `Нет линии снабжения. Хаб (${hx},${hy}), R=${R}, дистанция ${dist}.${blkStr}`;

      const prev = supplyHint ? JSON.stringify(supplyHint) : "";
      supplyHint = {
        for: { x: cell.x, y: cell.y, z },
        inSupply: Boolean(b.in_supply),
        routeClear: Boolean(b.route_clear),
        blockedAt: blk && blk.x != null && blk.y != null ? { x: blk.x, y: blk.y } : null,
      };
      const next = JSON.stringify(supplyHint);
      if (prev !== next) renderMap();
    } catch (_e) {
      selSupplyEl.textContent = "—";
      selSupplyEl.title = "";
      selSupplyEl.classList.remove("hud-warn");
      supplyHint = null;
    }
  };

  const outpostButtonsHtml = () => `
    <div class="row" style="gap:8px;flex-wrap:wrap;margin-top:8px;">
      <button type="button" data-outpost="outpost_t1">Форпост I</button>
    </div>
  `;

  const updateSelectedPanel = () => {
    const unit = pickedFleetForHud();
    const isMoving = unit && unit.status === "moving";

    if (!selectedCell) {
      closePlanetModal();
      if (selCoordEl) selCoordEl.textContent = "—";
      if (selTerrainEl) selTerrainEl.textContent = "—";
      if (selGlyphEl) selGlyphEl.textContent = "—";
      if (selObjectsEl) selObjectsEl.textContent = "—";
      if (selDistanceEl) selDistanceEl.textContent = "—";
      if (selTravelEl) selTravelEl.textContent = "—";
      if (selArriveEl) selArriveEl.textContent = "—";
      if (selInfluenceEl) selInfluenceEl.textContent = "—";
      if (selSupplyEl) {
        selSupplyEl.textContent = "—";
        selSupplyEl.title = "";
        selSupplyEl.classList.remove("hud-warn");
      }
      if (flyBtn) flyBtn.disabled = true;
      if (buildBtn) buildBtn.disabled = true;
      if (discoveryResolveBtn) {
        discoveryResolveBtn.classList.add("hidden");
        discoveryResolveBtn.disabled = true;
      }
      return;
    }

    if (selCoordEl) selCoordEl.textContent = `${selectedCell.x}, ${selectedCell.y}, ${selectedCell.z}`;
    if (selTerrainEl) selTerrainEl.textContent = formatTerrainRu(selectedCell.terrain);
    if (selGlyphEl) {
      // Для планеты "P" как маркер не несёт пользы.
      if (selectedCell.terrain === "planet") selGlyphEl.textContent = "—";
      else selGlyphEl.textContent = formatGlyphRu(selectedCell.terrain, selectedCell.glyph);
    }

    const objs = selectedCell.objects || [];
    if (selObjectsEl) {
      if (objs.length === 0) selObjectsEl.textContent = "нет";
      else {
        const buildings = objs.filter((o) => o && o.type === "building");
        const others = objs.filter((o) => !(o && o.type === "building"));
        const fmt = (o) => {
          if (o.type === "planet") {
            const owner = o.owner_name ? ` (${o.owner_name})` : "";
            return `${o.name || "Планета"}${owner}`;
          }
          if (o.type === "fleet") {
            const owner = o.owner_name ? ` (${o.owner_name})` : "";
            const c = o.composition ? formatComposition(o.composition) : "";
            const label = c ? c : `${o.unit_type}×${o.qty}`;
            const e = Number.isFinite(Number(o.energy)) && Number.isFinite(Number(o.max_energy))
              ? ` • E ${Number(o.energy)}/${Number(o.max_energy)}`
              : "";
            return `${label}${e}${owner}`;
          }
          if (o.type === "outpost") {
            const owner = o.owner_name ? ` (${o.owner_name})` : "";
            return `${o.name || "Форпост"}${owner}`;
          }
          if (o.type === "building") {
            const bt = o.building_type ? String(o.building_type) : "постройка";
            return buildingLabelRu(bt);
          }
          return o.type || "объект";
        };
        const parts = [];
        if (others.length) parts.push(others.map(fmt).join(", "));
        if (buildings.length) {
          // На планете зданий может быть много — сворачиваем в краткую сводку.
          const counts = {};
          for (const b of buildings) {
            const bt = b && b.building_type ? String(b.building_type) : "постройка";
            const label = buildingLabelRu(bt);
            counts[label] = (counts[label] || 0) + 1;
          }
          const top = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)
            .map(([k, v]) => `${k}×${v}`)
            .join(", ");
          parts.push(`постройки×${buildings.length}${top ? ` (${top}${Object.keys(counts).length > 3 ? ", …" : ""})` : ""}`);
        }
        selObjectsEl.textContent = parts.join(" • ");
      }
    }

    if (selInfluenceEl) {
      const vis = selectedCell.flags && selectedCell.flags.is_visible;
      if (!vis) selInfluenceEl.textContent = "— (не в обзоре)";
      else selInfluenceEl.textContent = formatInfluenceHud(selectedCell.influence);
    }
    void refreshSupplyHud(selectedCell);

    const from = unit ? { x: unit.x, y: unit.y, z: unit.z } : home;
    const dist = Math.abs(selectedCell.x - from.x) + Math.abs(selectedCell.y - from.y);
    const travelTicks = Math.max(1, dist);
    const currentTick = Number.isInteger(worldState.current_sol)
      ? worldState.current_sol
      : Number.isInteger(worldState.current_tick)
        ? worldState.current_tick
        : 0;
    const arriveTick = currentTick + travelTicks;

    if (selDistanceEl) selDistanceEl.textContent = String(dist);
    if (selTravelEl) selTravelEl.textContent = `${travelTicks} ${solWord(travelTicks)}`;
    if (selArriveEl) selArriveEl.textContent = `сол ${arriveTick}`;

    const sameCell = selectedCell.x === from.x && selectedCell.y === from.y && selectedCell.z === from.z;
    if (flyBtn) flyBtn.disabled = isMoving || sameCell;
    if (buildBtn) {
      const engineerFleet = engineerFleetForCell(selectedCell);
      const hasOutpost = (selectedCell.objects || []).some((o) => o && o.type === "outpost" && String(o.owner) === String(playerId));
      const canBuildHere = Boolean(
        selectedCell &&
          selectedCell.flags &&
          selectedCell.flags.is_visible &&
          (engineerFleet || hasOutpost),
      );
      buildBtn.disabled = !canBuildHere;
      buildBtn.title = canBuildHere
        ? ""
        : 'Создайте флот с "инженерами" и приведите его в эту клетку (или стройте из своей клетки с форпостом).';
    }

    if (discoveryResolveBtn) {
      discoveryResolveBtn.classList.add("hidden");
      discoveryResolveBtn.disabled = true;
      discoveryResolveBtn.textContent = "Исследовать";
      const vis = selectedCell.flags && selectedCell.flags.is_visible;
      const tr = selectedCell.terrain;
      if (vis && (tr === "ruins" || tr === "anomaly")) {
        void (async () => {
          try {
            const r = await fetch(
              `/api/world/sector?x=${selectedCell.x}&y=${selectedCell.y}&z=${selectedCell.z ?? 0}`,
            );
            if (!r.ok) return;
            const sec = await r.json();
            const d = sec.discovery;
            if (!d) return;
            if (d.can_resolve) {
              discoveryResolveBtn.classList.remove("hidden");
              discoveryResolveBtn.disabled = false;
            } else if (d.done) {
              discoveryResolveBtn.textContent = "Уже исследовано";
              discoveryResolveBtn.classList.remove("hidden");
              discoveryResolveBtn.disabled = true;
            }
          } catch (_e) {}
        })();
      }
    }
  };

  const placeBuilding = async (x, y, z, building_type, fleetId = null) => {
    setStatus("Строительство...");
    try {
      const r = await fetch("/api/buildings/place", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z, building_type, fleet_id: fleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "not_enough_resources") {
          setStatus(`Не хватает ресурсов: нужно M${body.need?.metal}/C${body.need?.crystal}`, "err");
        } else if (body.error === "engineer_required") {
          setStatus("Для стройки вне колонии нужен ваш флот с инженерами на этой клетке", "err");
        } else if (body.error === "outpost_too_close") {
          setStatus(`Форпост слишком близко к вашему: нужно расстояние ≥ ${body.need_distance ?? "?"} (сейчас ${body.nearest ?? "?"})`, "err");
        } else if (body.error === "planet_slots_full") {
          setStatus(`На планете больше нет слотов под постройки (${body.built ?? "?"}/${body.total ?? "?"})`, "err");
        } else if (body.error === "planet_required") {
          setStatus("Эту постройку можно возводить только в клетке планеты", "err");
        } else if (body.error === "not_enough_fleet_energy") {
          setStatus(`Не хватает энергии флота для действия (нужно ${body.need ?? "?"}, есть ${body.have ?? "?"})`, "err");
        } else if (body.error === "tech_required") {
          setStatus(`Нужно исследование: ${(body.missing_techs || body.required_techs || []).join(", ")}`, "err");
          } else if (body.error === "wrong_foundation_terrain") {
            const exp = Array.isArray(body.expected) ? body.expected.join(", ") : "—";
            setStatus(`Неверное основание: требуется ${exp}, на клетке ${body.terrain || "—"}`, "err");
        } else if (body.error === "inside_enemy_control_zone") {
          setStatus("Нельзя строить в клетке с подтверждённым вражеским контролем", "err");
        } else {
          setStatus(`Ошибка: ${body.error || "build_failed"}`, "err");
        }
        return;
      }
      setStatus(`Построено: ${body.building?.building_type || "ok"}`, "ok");
      const sx = selectedCell ? selectedCell.x : null;
      const sy = selectedCell ? selectedCell.y : null;
      const sz = selectedCell ? selectedCell.z : null;
      await refreshWindow();
      if (sx != null && sy != null && sz != null && currentWindow && currentWindow.cells) {
        for (const row of currentWindow.cells) {
          for (const c of row.row) {
            if (c.x === sx && c.y === sy && c.z === sz) {
              selectedCell = { ...c };
              break;
            }
          }
        }
      }
      await loadWorldState();
      if (selectedCell && planetModalOverlay && !planetModalOverlay.classList.contains("hidden")) {
        await fillPlanetModalFromApi(selectedCell);
      }
      updateSelectedPanel();
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const refreshSelectedCellFromWindow = () => {
    const sx = selectedCell ? selectedCell.x : null;
    const sy = selectedCell ? selectedCell.y : null;
    const sz = selectedCell ? selectedCell.z : null;
    if (sx == null || sy == null || sz == null || !currentWindow || !currentWindow.cells) return;
    for (const row of currentWindow.cells) {
      for (const c of row.row) {
        if (c.x === sx && c.y === sy && c.z === sz) {
          selectedCell = { ...c };
          return;
        }
      }
    }
  };

  const handleOutpostResult = async (body, okText) => {
    if (!body || !body.ok) return;
    setStatus(okText, "ok");
    await refreshWindow();
    refreshSelectedCellFromWindow();
    await loadWorldState();
    if (selectedCell && planetModalOverlay && !planetModalOverlay.classList.contains("hidden")) {
      await fillPlanetModalFromApi(selectedCell);
    }
    updateSelectedPanel();
  };

  const buildOutpost = async (x, y, z, outpostType, fleetId = null) => {
    setStatus("Строим форпост...");
    try {
      const r = await fetch("/api/outposts/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z, outpost_type: outpostType, fleet_id: fleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "tech_required") setStatus(`Нужно исследование: ${(body.missing_techs || []).join(", ")}`, "err");
        else if (body.error === "not_enough_engineers" || body.error === "engineer_required")
          setStatus(`Нужен инженер в клетке (need=${body.need_engineers ?? 1})`, "err");
        else if (body.error === "outpost_too_close") {
          const no = body.nearest_outpost || null;
          const at = no && Number.isFinite(Number(no.x)) && Number.isFinite(Number(no.y)) ? ` (${no.x},${no.y},${no.z ?? 0})` : "";
          setStatus(`Слишком близко к вашему форпосту${at}. Нужно расстояние ≥ ${body.need_distance}, сейчас ${body.nearest}.`, "err");
          if (no && Number.isFinite(Number(no.x)) && Number.isFinite(Number(no.y))) {
            // центрируем карту на ближайшем форпосте
            viewCenter = { x: Number(no.x), y: Number(no.y) };
            if (Number.isFinite(Number(no.z))) currentZ = Number(no.z);
            await refreshWindow();
          }
        }
        else if (body.error === "not_enough_resources")
          setStatus(`Не хватает ресурсов (нужно ${JSON.stringify(body.need || {})})`, "err");
        else setStatus(`Ошибка: ${(body.error || "outpost_build_failed")} ${body.detail ? `(${body.detail})` : ""}`, "err");
        return;
      }
      await handleOutpostResult(body, `Форпост построен: ${body.outpost?.name || outpostType}`);
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const upgradeOutpost = async (outpostId) => {
    setStatus("Улучшаем форпост...");
    try {
      const r = await fetch("/api/outposts/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outpost_id: outpostId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "tech_required") setStatus(`Нужно исследование: ${(body.missing_techs || []).join(", ")}`, "err");
        else setStatus(`Ошибка: ${body.error || "outpost_upgrade_failed"}`, "err");
        return;
      }
      await handleOutpostResult(body, `Форпост улучшен: ${body.outpost?.name || "ok"}`);
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const installOutpostModule = async (outpostId, moduleType) => {
    setStatus("Установка модуля...");
    try {
      const r = await fetch("/api/outposts/modules/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outpost_id: outpostId, module_type: moduleType }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "tech_required") setStatus(`Нужно исследование: ${(body.missing_techs || []).join(", ")}`, "err");
        else if (body.error === "not_enough_engineers") setStatus("Не хватает инженеров для модуля", "err");
        else setStatus(`Ошибка: ${body.error || "module_install_failed"}`, "err");
        return;
      }
      await handleOutpostResult(body, "Модуль установлен");
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const upgradeOutpostModule = async (moduleId) => {
    setStatus("Улучшаем модуль...");
    try {
      const r = await fetch("/api/outposts/modules/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_id: moduleId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "tech_required") setStatus(`Нужно исследование: ${(body.missing_techs || []).join(", ")}`, "err");
        else setStatus(`Ошибка: ${body.error || "module_upgrade_failed"}`, "err");
        return;
      }
      await handleOutpostResult(body, "Модуль улучшен");
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const upgradeBuilding = async (building_id) => {
    setStatus("Улучшение постройки...");
    try {
      const r = await fetch("/api/buildings/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "building_upgrade_unavailable") {
          setStatus("Для этой постройки нет улучшения в балансе", "err");
        } else if (body.error === "tech_required") {
          setStatus(`Нужны исследования: ${(body.missing_techs || []).join(", ")}`, "err");
        } else if (body.error === "not_enough_resources") {
          setStatus("Не хватает ресурсов на улучшение", "err");
        } else if (body.error === "planet_type_cap") {
          setStatus("Достигнут лимит таких построек на планете", "err");
        } else setStatus(`Ошибка: ${body.error || "upgrade_failed"}`, "err");
        return;
      }
      setStatus(`Улучшено: ${body.building?.building_type || "ok"}`, "ok");
      await refreshWindow();
      await loadWorldState();
      if (selectedCell && planetModalOverlay && !planetModalOverlay.classList.contains("hidden")) {
        await fillPlanetModalFromApi(selectedCell);
      }
      updateSelectedPanel();
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const dismantleBuilding = async (building_id) => {
    setStatus("Снос постройки...");
    try {
      const r = await fetch("/api/buildings/dismantle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "dismantle_failed"}`, "err");
        return;
      }
      setStatus("Постройка снесена (50% стоимости возвращено)", "ok");
      await refreshWindow();
      await loadWorldState();
      if (selectedCell && planetModalOverlay && !planetModalOverlay.classList.contains("hidden")) {
        await fillPlanetModalFromApi(selectedCell);
      }
      updateSelectedPanel();
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const fillPlanetModalFromApi = async (cell) => {
    if (!planetModalBody) return;
    const x = cell.x;
    const y = cell.y;
    const z = cell.z ?? 0;
    const mapPlanet = (cell.objects || []).find((o) => o && o.type === "planet");
    const mapOutpost = (cell.objects || []).find((o) => o && o.type === "outpost");

    planetModalBody.innerHTML = "<div class='muted'>Загрузка…</div>";
    if (planetModalTitle) {
      planetModalTitle.textContent =
        (mapPlanet && mapPlanet.name ? String(mapPlanet.name) : null) ||
        (mapOutpost && mapOutpost.name ? String(mapOutpost.name) : null) ||
        "Сектор";
    }

    let sector = { objects: [] };
    try {
      const r = await fetch(`/api/world/sector?x=${x}&y=${y}&z=${z}`);
      if (r.ok) sector = await r.json();
    } catch (_e) {
      planetModalBody.innerHTML = "<div class='muted'>Не удалось загрузить данные сектора.</div>";
      return;
    }

    const planetOwn = (sector.objects || []).find((o) => o && o.type === "planet" && o.details);
    const outpostOwn = (sector.objects || []).find((o) => o && o.type === "outpost" && String(o.owner) === String(playerId));

    if (planetOwn && planetOwn.details) {
      await fetchBalanceCached();
      const d = planetOwn.details;
      const unitsNz = (d.units || []).filter((it) => it && Number(it.qty) > 0);
      const u = unitsNz.map((it) => `${fleetUnitLabel(it.unit_type)}×${it.qty}`).join(", ") || "нет";
      const pr = d.production || {};
      const mp = pr.metal_per_sol != null ? pr.metal_per_sol : pr.metal_per_tick || 0;
      const cp = pr.crystal_per_sol != null ? pr.crystal_per_sol : pr.crystal_per_tick || 0;
      const ep = pr.energy_per_sol != null ? pr.energy_per_sol : pr.energy_per_tick || 0;
      const fp = pr.fuel_per_sol != null ? pr.fuel_per_sol : pr.fuel_per_tick || 0;
      const fdp = pr.food_per_sol != null ? pr.food_per_sol : pr.food_per_tick || 0;
      const wp = pr.water_per_sol != null ? pr.water_per_sol : pr.water_per_tick || 0;
      const ownName = planetOwn.owner_name ? ` • ${planetOwn.owner_name}` : "";
      const cls = d.planet_class ? String(d.planet_class) : "—";
      const slotsLine =
        d.build_slots && typeof d.build_slots === "object"
          ? `Слоты: <b>${Number(d.build_slots.used || 0)}</b> / <b>${Number(d.build_slots.total || 0)}</b>`
          : "";
      const supN = Number(d.supplier_count) || 0;
      const supBase = Number(d.supply_base) || 5;
      const supPer = Number(d.supply_per_supplier) || 3;
      const supR = Number(d.supply_radius) || supBase + supPer * supN;

      const flags = cell.flags || {};
      const objs = cell.objects || [];
      const canBuild = Boolean(flags.zone_build_self) && !Boolean(flags.zone_build_enemy) && Boolean(flags.is_visible);
      const cellBuildings = objs.filter((o) => o && o.type === "building");
      const cellBuilding = cellBuildings[0] || null;
      let buildHtml = "";
      if (!canBuild) {
        buildHtml = "<div class='muted'>Стройка: нельзя в этой клетке (вне зоны, туман или зона врага).</div>";
      } else if (cellBuildings.length && cell.terrain !== "planet") {
        const b = cellBuilding;
        const bid = b && b.id ? String(b.id) : "";
        buildHtml = `<div>На клетке: <b>${escHtml(buildingLabelRu(b && b.building_type ? String(b.building_type) : "постройка"))}</b> (ур. ${Number((b && b.level) || 1) || 1}).</div>`;
        if (bid) {
          buildHtml += `<div class="row" style="gap:8px;margin-top:8px;"><button type="button" data-demolish="${escHtml(bid)}">Снести постройку</button></div>`;
        }
      } else {
        // Клетка планеты: допускаем несколько построек (слоты планеты ограничивают).
        if (cell.terrain === "planet" && cellBuildings.length) {
          const lines = cellBuildings
            .map((b) => {
              const bid = b && b.id ? String(b.id) : "";
              const nm = buildingLabelRu(b && b.building_type ? String(b.building_type) : "");
              const lvl = Number(b && b.level ? b.level : 1) || 1;
              const btnDm = bid ? `<button type="button" data-demolish="${escHtml(bid)}">Снести</button>` : "";
              const btnUp = bid ? `<button type="button" data-bupgrade="${escHtml(bid)}">Улучшить</button>` : "";
              const btn = bid ? `<span class="row" style="gap:6px;margin-left:auto;">${btnUp}${btnDm}</span>` : "";
              return `<div class="row" style="gap:8px;align-items:center;flex-wrap:wrap;"><span><b>${escHtml(nm)}</b> (ур. ${lvl})</span>${btn}</div>`;
            })
            .join("");
          buildHtml += `<div class="section-title">Постройки на планете</div>${lines}`;
        }
        buildHtml = `
          <label class="row" style="gap:8px;align-items:center;margin:6px 0 0 0;">
            <input type="checkbox" id="show-all-build" />
            <span class="muted">Показать все варианты</span>
          </label>
          ${buildButtonsHtml()}
          <div class="muted" style="margin-top:8px;">Ресурс списывается с домашней планеты (имперский склад).</div>
        `;
      }

      planetModalBody.innerHTML = `
        <div class="section-title">Основное</div>
        <div><b>${planetOwn.name || "Планета"}</b> (${sector.x}, ${sector.y}, ${sector.z})${ownName}</div>
        <div class="muted" style="margin-top:6px;">Ландшафт: ${formatTerrainRu(cell.terrain)}</div>
        <div class="section-title">Население</div>
        <div>Население: <b>${d.population != null ? escHtml(String(d.population)) : "—"}</b> / <b>${d.max_population != null ? escHtml(String(d.max_population)) : "—"}</b></div>
        ${
          d.population_vitals
            ? `<div class="muted" style="margin-top:6px;">Содержание населения: <b>${escHtml(String(d.population_vitals.food_per_sol ?? 0))}</b> еды и <b>${escHtml(String(d.population_vitals.water_per_sol ?? 0))}</b> воды за сол (списывается после выработки).</div>`
            : ""
        }
        ${slotsLine ? `<div class="muted" style="margin-top:6px;">${slotsLine} • класс: ${escHtml(cls)}</div>` : `<div class="muted" style="margin-top:6px;">класс: ${escHtml(cls)}</div>`}
        <div class="section-title">Снабжение (эта планета)</div>
        <div>Снабженцев: <b>${supN}</b></div>
        <div class="muted">Базовый радиус: <b>${supBase}</b> • бонус за снабженца: <b>+${supPer}</b> • <b>итого снабжение: ${supR} клеток</b></div>
        <div class="muted" style="margin-top:6px;font-size:88%;">Линии: от планеты L-маршрут (сначала X, затем Y); чужой флот на пути обрывает снабжение. Активный форпост вне планеты тянет еду/воду с хаба за сол (см. форпост).</div>
        <div class="row" style="gap:8px;margin-top:8px;">
          <button type="button" id="hire-supplier-btn" data-planet-id="${escHtml(String(planetOwn.id || mapPlanet?.id || ""))}">Нанять снабженца</button>
        </div>
        <div class="muted" style="margin-top:6px;font-size:88%;">Снабженец — логистическая единица планеты (не корабль на карте).</div>
        <div class="section-title">Ресурсы на планете</div>
        <div>Металл <b>${d.resources.metal}</b> • Кристалл <b>${d.resources.crystal}</b> • Энергия <b>${d.resources.energy}</b> • Топливо <b>${d.resources.fuel ?? 0}</b> • Еда <b>${d.resources.food ?? 0}</b> • Вода <b>${d.resources.water ?? 0}</b></div>
        <div class="section-title">Производство (за сол)</div>
        <div>+<b>${mp}</b> металл • +<b>${cp}</b> кристалл • +<b>${ep}</b> энергия • +<b>${fp}</b> топливо • +<b>${fdp}</b> еда • +<b>${wp}</b> вода</div>
        ${
          d.population_vitals
            ? `<div class="muted" style="margin-top:6px;font-size:88%;">Баланс еды/воды (оценка): <b>${Math.max(0, (Number(fdp) || 0) - Number(d.population_vitals.food_per_sol || 0))}</b> / <b>${Math.max(0, (Number(wp) || 0) - Number(d.population_vitals.water_per_sol || 0))}</b> в плюс. Если склад остаётся 0 — обычно уходит в содержание населения и логистику снабжения форпостов.</div>`
            : ""
        }
        ${unitsNz.length ? `<div class="section-title">Юниты на планете</div>\n        <div>${u}</div>` : ""}
        <div class="section-title">Флоты</div>
        <div class="muted" style="margin-bottom:6px;">Создать у родной планеты или у планеты с мини-верфью (drydock).</div>
        <button type="button" class="btn-create-fleet" data-planet-id="${escHtml(String(planetOwn.id || mapPlanet?.id || ""))}">Создать флот…</button>
        <div class="section-title">Стройка</div>
        <div class="muted">Активно: ${d.build && d.build.active ? d.build.active : "нет"} • очередь: ${d.build && Array.isArray(d.build.queue) ? d.build.queue.length : 0}</div>
        ${buildHtml}
      `;

      bindBuildButtons(planetModalBody, x, y, z, null);
      const showAllEl = planetModalBody.querySelector("#show-all-build");
      if (showAllEl) {
        showAllEl.checked = Boolean(showAllBuildOptions);
        showAllEl.addEventListener("change", () => {
          showAllBuildOptions = Boolean(showAllEl.checked);
          void updateBuildButtonsAvailability(x, y, z, null);
        });
      }
      await updateBuildButtonsAvailability(x, y, z, null);
      const hireSupBtn = planetModalBody.querySelector("#hire-supplier-btn");
      if (hireSupBtn) {
        hireSupBtn.addEventListener("click", async () => {
          const plid = hireSupBtn.getAttribute("data-planet-id");
          if (!plid) return;
          setStatus("Найм снабженца…");
          try {
            const r = await fetch("/api/supply/hire_supplier", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ planet_id: plid }),
            });
            const body = await r.json();
            if (!r.ok || !body.ok) {
              if (body.error === "not_enough_resources") {
                setStatus(`Не хватает ресурсов для найма`, "err");
              } else {
                setStatus(`Ошибка: ${body.error || "hire_failed"}`, "err");
              }
              return;
            }
            setStatus(`Снабжение: радиус ${body.supply_radius} клеток`, "ok");
            await loadWorldState();
            void refreshSupplyHud(selectedCell);
            await fillPlanetModalFromApi(cell);
          } catch (_e) {
            setStatus("Ошибка: network_error", "err");
          }
        });
      }
      for (const btn of planetModalBody.querySelectorAll("button.btn-create-fleet")) {
        btn.addEventListener("click", () => {
          const pid = btn.getAttribute("data-planet-id");
          if (!pid) return;
          closePlanetModal();
          void openFleetCreateModal({
            planetId: pid,
            title: planetOwn.name || "Планета",
          });
        });
      }
      return;
    }

    if (outpostOwn && outpostOwn.details) {
      const d = outpostOwn.details;
      planetModalBody.innerHTML = `
        <div class="section-title">Форпост</div>
        <div><b>${escHtml(d.name || "Форпост")}</b> (${x}, ${y}, ${z})</div>
        <div class="muted" style="margin-top:6px;">Статус: ${escHtml(d.status || "active")} • уровень: <b>${Number(d.level) || 1}</b> • старт: <b>${Number(d.started_at_tick || 0)}</b> • готов: <b>${Number(d.finish_tick || 0)}</b></div>
        <div class="section-title">Территория и обзор</div>
        <div>Влияние: <b>${Number(d.territory?.influence_strength || 0)}</b> • радиус влияния: <b>${Number(d.territory?.influence_radius || 0)}</b></div>
        <div>Радиус обзора: <b>${Number(d.vision?.radius || 0)}</b></div>
        <div class="section-title">Бой</div>
        <div>HP <b>${Number(d.combat?.hp || 0)}</b> • атака <b>${Number(d.combat?.attack || 0)}</b> • защита <b>${Number(d.combat?.defense || 0)}</b></div>
        <div class="section-title">Слоты</div>
        <div>Занято <b>${Number(d.slots?.used || 0)}</b> / <b>${Number(d.slots?.total || 0)}</b></div>
        ${
          d.supply_line
            ? `<div class="section-title">Логистика снабжения</div><div class="muted">С хаба (планета) за сол: еда <b>${Number(d.supply_line.food_per_sol || 0)}</b>, вода <b>${Number(d.supply_line.water_per_sol || 0)}</b>. При нехватке на хабе форпост отключится.</div>`
            : ""
        }
        <div class="section-title">Модули</div>
        <div class="muted">Каркас модулей уже заложен в данных и БД, но в первом проходе они ещё не активированы в UI.</div>
      `;
      return;
    }

    if (mapPlanet) {
      const owner = mapPlanet.owner_name ? String(mapPlanet.owner_name) : mapPlanet.owner ? String(mapPlanet.owner) : "—";
      planetModalBody.innerHTML = `
        <div class="section-title">Объект</div>
        <div><b>${mapPlanet.name || "Планета"}</b> (${x}, ${y}, ${z})</div>
        <div>Владелец: <b>${owner}</b></div>
        <div class="muted" style="margin-top:10px;">Детальное производство и стройка доступны только для ваших планет.</div>
      `;
      return;
    }

    const engFleets = engineerFleetsForCell(cell);
    const fleetBuilder = engFleets[0] || null;
    const buildingHere = (cell.objects || []).find((o) => o && o.type === "building");
    const outpostHere = (cell.objects || []).find((o) => o && o.type === "outpost");
    if (fleetBuilder) {
      const fleetLabel = fleetBuilder.name && String(fleetBuilder.name).trim() ? String(fleetBuilder.name).trim() : "Флот";
      const engineerQty = Number(fleetBuilder.composition?.engineer || 0);
      let engineerPickHtml = "";
      if (engFleets.length > 1) {
        engineerPickHtml = `
          <div class="muted" style="margin:10px 0 4px;font-size:90%;"><b>Инженерный флот</b> (на клетке несколько — выберите, с кого списывать инженера):</div>
          <select id="sector-builder-fleet" style="width:100%;max-width:440px;padding:6px 8px;margin-bottom:4px;">
            ${engFleets
              .map((fl) => {
                const opt = fleetOptionLabel(fl);
                const sel = String(fl.id) === String(fleetBuilder.id) ? "selected" : "";
                return `<option value="${escHtml(String(fl.id))}" ${sel}>${escHtml(opt)}</option>`;
              })
              .join("")}
          </select>`;
      }
      let buildHtml = "";
      if (outpostHere) {
        buildHtml = `<div>На клетке уже стоит <b>${escHtml(outpostHere.name || "форпост")}</b>.</div>`;
      } else if (buildingHere) {
        buildHtml = `<div>На клетке уже стоит <b>${escHtml(buildingLabelRu(buildingHere.building_type || "постройка"))}</b>.</div>`;
      } else {
        buildHtml = `
          <div class="section-title">Форпосты</div>
          ${outpostButtonsHtml()}
          <div class="muted" style="margin-top:8px;">Форпосты дают влияние, обзор, слоты модулей и базовую оборону.</div>
          <div class="section-title">Обычные постройки</div>
          ${buildButtonsHtml()}
          <div class="muted" style="margin-top:8px;">Строит выбранный флот с инженерами; ресурсы списываются с домашней планеты.</div>
        `;
      }
      planetModalBody.innerHTML = `
        <div class="section-title">Строительство в секторе</div>
        <div><b>${fleetLabel}</b> (${x}, ${y}, ${z})</div>
        ${engineerPickHtml}
        <div class="muted" style="margin-top:6px;">Инженеров в выбранном флоте: <b>${engineerQty}</b></div>
        <div class="muted" style="margin-top:6px;">Ландшафт: ${formatTerrainRu(cell.terrain)}</div>
        ${buildHtml}
      `;
      const defaultBid = fleetBuilder.id || null;
      bindBuildButtons(planetModalBody, x, y, z, defaultBid);
      bindOutpostButtons(planetModalBody, { x, y, z, fleetId: defaultBid });
      const selEng = planetModalBody.querySelector("#sector-builder-fleet");
      const runPlacementChecks = () => {
        const fid = selEng && selEng.value ? String(selEng.value) : defaultBid;
        void updateBuildButtonsAvailability(x, y, z, fid);
      };
      if (selEng) selEng.addEventListener("change", runPlacementChecks);
      await runPlacementChecks();
      return;
    }

    planetModalBody.innerHTML = "<div class='muted'>В этой клетке нет планеты. Для полевой стройки нужен ваш флот с инженерами на клетке.</div>";
  };

  const openPlanetModal = async (cell) => {
    if (!planetModalOverlay || !planetModalBody) return;
    planetModalOverlay.classList.remove("hidden");
    await fillPlanetModalFromApi(cell);
  };

  let fleetCreateContext = null;
  let fleetCreateDraft = {};

  const closeFleetCreateModal = () => {
    if (fleetCreateOverlay) fleetCreateOverlay.classList.add("hidden");
    fleetCreateContext = null;
    fleetCreateDraft = {};
  };

  const renderFleetCreateModal = () => {
    if (!fleetCreateBody || !fleetCreateContext) return;
    const nmVal = fleetCreateContext.nameDraft != null ? String(fleetCreateContext.nameDraft) : "";
    const qtyKeys = fleetLogicalKeysBalanceOnly();
    const rows = qtyKeys.map((k) => {
      const q = Number(fleetCreateDraft[k]) || 0;
      const lab = fleetUnitLabel(k);
      return `
        <div class="row fleet-qty-row" style="justify-content:space-between;align-items:center;margin-bottom:10px;gap:10px;flex-wrap:wrap;">
          <span><b>${escHtml(lab)}</b> <span class="muted">(${escHtml(k)})</span></span>
          <span style="display:inline-flex;align-items:center;gap:6px;">
            <button type="button" class="fleet-create-qty-step" data-u="${k}" data-s="-1">−</button>
            <input type="number" class="fleet-create-qty-input" data-u="${k}" min="0" max="99999" step="1" value="${q}" style="width:80px;padding:6px 8px;" />
            <button type="button" class="fleet-create-qty-step" data-u="${k}" data-s="1">+</button>
          </span>
        </div>`;
    }).join("");
    fleetCreateBody.innerHTML = `
      <div class="muted" style="margin-bottom:10px;font-size:90%;">
        Стоимость юнитов спишется с домашней планеты (как при правке флота). Флот появится на свободной клетке рядом с планетой. Время строительства не моделируется.
      </div>
      <div class="row" style="flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:center;">
        <label class="muted" style="flex:100%;margin:0;font-size:90%;"><b>Имя флота</b> (пусто — авто)</label>
        <input type="text" class="fleet-create-name" maxlength="64" value="${escHtml(nmVal)}" style="flex:1;min-width:140px;padding:6px 8px;" placeholder="Alpha (Альфа)…" />
      </div>
      ${rows}
      <div class="row" style="margin-top:14px;gap:8px;">
        <button type="button" class="fleet-create-submit">Создать</button>
        <button type="button" class="fleet-create-cancel muted">Отмена</button>
      </div>
    `;
    for (const btn of fleetCreateBody.querySelectorAll("button.fleet-create-qty-step")) {
      btn.addEventListener("click", () => {
        const u = btn.getAttribute("data-u");
        const s = Number(btn.getAttribute("data-s"));
        if (!u || !Number.isFinite(s)) return;
        const inp = fleetCreateBody.querySelector(`input.fleet-create-qty-input[data-u="${u}"]`);
        if (!inp) return;
        const v = Math.max(0, Math.floor(Number(inp.value) || 0) + s);
        inp.value = String(v);
        fleetCreateDraft[u] = v;
      });
    }
    for (const qInp of fleetCreateBody.querySelectorAll("input.fleet-create-qty-input")) {
      qInp.addEventListener("change", () => {
        const u = qInp.getAttribute("data-u");
        if (!u) return;
        fleetCreateDraft[u] = Math.max(0, Math.floor(Number(qInp.value) || 0));
        qInp.value = String(fleetCreateDraft[u]);
      });
    }
    const nmInp = fleetCreateBody.querySelector(".fleet-create-name");
    if (nmInp) {
      nmInp.addEventListener("input", () => {
        fleetCreateContext.nameDraft = nmInp.value;
      });
    }
    const sub = fleetCreateBody.querySelector(".fleet-create-submit");
    if (sub) {
      sub.addEventListener("click", async () => {
        const inp = fleetCreateBody.querySelector(".fleet-create-name");
        const nm = inp ? inp.value.trim() : "";
        const comp = {};
        for (const k of fleetLogicalKeysBalanceOnly()) {
          const el = fleetCreateBody.querySelector(`input.fleet-create-qty-input[data-u="${k}"]`);
          const n = el ? Math.max(0, Math.floor(Number(el.value) || 0)) : 0;
          fleetCreateDraft[k] = n;
          if (n > 0) comp[k] = n;
        }
        if (Object.keys(comp).length < 1) {
          setStatus("Добавьте хотя бы один корабль", "err");
          return;
        }
        setStatus("Создание флота…");
        try {
          const r = await fetch("/api/fleets/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              planet_id: fleetCreateContext.planetId,
              name: nm || undefined,
              composition: comp,
            }),
          });
          const body = await r.json();
          if (!r.ok || !body.ok) {
            setStatus(`Ошибка: ${body.error || "create_failed"}`, "err");
            return;
          }
          activeFleetId = body.fleet_id || activeFleetId;
          setStatus(`Флот создан: ${body.name || ""} @ (${body.pos?.x},${body.pos?.y})`, "ok");
          closeFleetCreateModal();
          await refreshWindow();
          await loadWorldState();
          if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
        } catch (_e) {
          setStatus("Ошибка: network_error", "err");
        }
      });
    }
    const can = fleetCreateBody.querySelector(".fleet-create-cancel");
    if (can) can.addEventListener("click", closeFleetCreateModal);
  };

  const openFleetCreateModal = async ({ planetId, title }) => {
    if (!fleetCreateOverlay || !fleetCreateBody || !planetId) return;
    await fetchBalanceCached();
    fleetCreateContext = { planetId: String(planetId), nameDraft: "" };
    fleetCreateDraft = {};
    for (const k of fleetLogicalKeysBalanceOnly()) fleetCreateDraft[k] = 0;
    if (fleetCreateTitle) fleetCreateTitle.textContent = title ? `Новый флот — ${title}` : "Новый флот";
    renderFleetCreateModal();
    fleetCreateOverlay.classList.remove("hidden");
  };

  const closeFleetModal = () => {
    closeFleetSubModal();
    if (fleetModalOverlay) fleetModalOverlay.classList.add("hidden");
  };

  /** Переопределяется ниже после `refreshWindow` (инициализирующая заглушка). */
  let focusFleetOnMap = async (_fleetId) => {};

  const saveFleetModalAll = async (fleetId, nameRaw, composition) => {
    const name = String(nameRaw ?? "").trim();
    if (!name) {
      setStatus("Введите имя флота", "err");
      return;
    }
    const total = Object.values(composition || {}).reduce(
      (s, v) => s + Math.max(0, Math.floor(Number(v) || 0)),
      0
    );
    if (total < 1) {
      setStatus("В сумме должно быть хотя бы один корабль (или расформируйте флот).", "err");
      return;
    }
    setStatus("Сохранение флота…");
    try {
      const r = await fetch("/api/fleets/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId, name, composition }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "save_failed"}`, "err");
        return;
      }
      const net = body.cost_net;
      if (net && (net.metal || net.crystal || net.energy || net.fuel)) {
        setStatus(
          `Сохранено. Изменение склада (Δ металл/кристалл/энергия/топливо): ${-net.metal}/${-net.crystal}/${-net.energy}/${-net.fuel}`,
          "ok"
        );
      } else {
        setStatus("Сохранено", "ok");
      }
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const disbandFleetApi = async (fleetId) => {
    setStatus("Расформирование…");
    try {
      const r = await fetch("/api/fleets/disband", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "disband_failed"}`, "err");
        return;
      }
      setStatus("Флот расформирован, ресурсы частично возвращены на домашнюю планету.", "ok");
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      const ownedAfter = (Array.isArray(worldState.fleets) ? worldState.fleets : []).filter((x) => x && x.id);
      activeFleetId = ownedAfter[0] ? ownedAfter[0].id : null;
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const mergeFleetsApi = async (targetFleetId, sourceFleetId) => {
    setStatus("Слияние флотов…");
    try {
      const r = await fetch("/api/fleets/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_fleet_id: targetFleetId, source_fleet_id: sourceFleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "merge_failed"}`, "err");
        return;
      }
      setStatus("Флоты объединены", "ok");
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const splitFleetApi = async (fleetId, take) => {
    setStatus("Разделение флота…");
    try {
      const r = await fetch("/api/fleets/split", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId, take }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Ошибка: ${body.error || "split_failed"}`, "err");
        return;
      }
      setStatus(`Создан новый флот (${body.new_fleet_id || ""})`, "ok");
      if (body.new_fleet_id) activeFleetId = body.new_fleet_id;
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      setStatus("Ошибка: network_error", "err");
    }
  };

  const renderFleetCompositionModal = () => {
    if (!fleetModalBody) return;
    const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
    const f = activeFleetId ? fleets.find((x) => x && x.id === activeFleetId) : null;
    if (!f || !f.id) {
      fleetModalBody.innerHTML = "<div class='muted'>Нет активного флота (выберите в списке).</div>";
      return;
    }
    const comp = f.composition && typeof f.composition === "object" ? { ...f.composition } : {};
    const qtyKeys = fleetQtyKeysForUi(comp);
    const fn = (f.name && String(f.name).trim()) || "Флот";
    if (fleetModalTitle) fleetModalTitle.textContent = `${fn} (${f.x}, ${f.y}, ${f.z})`;
    const blocked = f.status === "moving";
    const dis = blocked ? "disabled" : "";
    const others = fleets.filter((x) => x && x.id && x.id !== f.id);
    const mergeOpts =
      others.length === 0
        ? `<option value="">(нет других флотов)</option>`
        : `<option value="">— выберите флот —</option>${others
            .map((o) => {
              const on = (o.name && String(o.name).trim()) || "Флот";
              return `<option value="${escHtml(o.id)}">${escHtml(on)} (${escHtml(o.id).slice(0, 8)}…)</option>`;
            })
            .join("")}`;

    const shipCard = (k) => {
      const q = Number(comp[k]) || 0;
      const lab = fleetUnitLabel(k);
      const gl = fleetUnitGlyph(k);
      const u = resolveBalanceUnit(k);
      const cost = unitBuildCostParts(k);
      const costBits = [];
      if (cost.metal) costBits.push(`M ${cost.metal}`);
      if (cost.crystal) costBits.push(`C ${cost.crystal}`);
      if (cost.energy) costBits.push(`E ${cost.energy}`);
      if (cost.fuel) costBits.push(`F ${cost.fuel}`);
      const costLine = costBits.length ? costBits.join(" · ") : "—";
      const hp = u && u.hp != null ? u.hp : "—";
      const dmg = u && u.damage != null ? u.damage : "—";
      const spd = u && u.speed_cells_per_tick != null ? u.speed_cells_per_tick : "—";
      const fu = u && u.travel_fuel_per_cell != null ? u.travel_fuel_per_cell : "—";
      const desc =
        u && typeof u.description === "string" && u.description.trim()
          ? escHtml(u.description.trim())
          : "Корабль из баланса: стоимость набора и возврат при уменьшении совпадают с сервером при сохранении.";
      return `
        <div class="fleet-ship-card" data-unit-card="${escHtml(k)}">
          <div class="fleet-ship-card-head">
            <span class="fleet-ship-glyph" aria-hidden="true">${gl}</span>
            <div style="flex:1;min-width:0;">
              <div style="font-weight:700;">${escHtml(lab)} <span class="muted" style="font-weight:500;">(${escHtml(k)})</span></div>
              <div class="fleet-ship-meta">Цена 1 шт: ${escHtml(costLine)}</div>
              <div class="fleet-ship-meta">HP ${escHtml(String(hp))} · урон ${escHtml(String(dmg))} · клеток/сол ${escHtml(String(spd))} · топл./клетку ${escHtml(String(fu))}</div>
            </div>
          </div>
          <div class="fleet-ship-desc">${desc}</div>
          <div class="fleet-ship-qty">
            <button type="button" class="fleet-qty-step" data-u="${escHtml(k)}" data-s="-1" ${dis}>−</button>
            <input type="number" class="fleet-qty-input" data-u="${escHtml(k)}" min="0" max="99999" step="1" value="${q}" style="width:72px;padding:5px 6px;" ${blocked ? "disabled" : ""}/>
            <button type="button" class="fleet-qty-step" data-u="${escHtml(k)}" data-s="1" ${dis}>+</button>
          </div>
        </div>`;
    };

    const byRole = { recon: [], combat: [], tech: [] };
    for (const k of qtyKeys) {
      byRole[fleetUiRoleGroup(k)].push(k);
    }
    const roleSection = (keys, title) =>
      keys.length
        ? `<div class="fleet-role-title">${title}</div><div class="fleet-ship-grid">${keys.map(shipCard).join("")}</div>`
        : "";

    fleetModalBody.innerHTML = `
      <div class="row" style="flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:center;">
        <label class="muted" style="flex:100%;margin:0;font-size:90%;"><b>Имя флота</b></label>
        <input type="text" class="fleet-rename-input" maxlength="64" value="${escHtml(fn)}" style="flex:1;min-width:140px;padding:6px 8px;" />
        <button type="button" class="fleet-modal-save btn-primary" ${dis}>Сохранить</button>
        <button type="button" class="fleet-locate-this btn-secondary" title="Показать на карте и выделить">На карте</button>
      </div>
      <div class="muted" style="margin-bottom:10px;font-size:90%;">
        Набор кораблей оплачивается со склада домашней планеты по цене постройки; при уменьшении числа — возврат примерно <b>50%</b> стоимости в ресурсах.
      </div>
      ${blocked ? "<div style='margin-bottom:10px;color:#e88'><b>В пути</b> — нельзя менять состав, слияние и разделение.</div>" : ""}
      ${roleSection(byRole.recon, "Разведка")}
      ${roleSection(byRole.combat, "Боевой состав")}
      ${roleSection(byRole.tech, "Техника и логистика")}
      <div id="fleet-comp-net-preview" class="fleet-comp-net-preview"></div>
      <div class="fleet-modal-actions-muted">
        <button type="button" class="btn-secondary fleet-open-merge" ${dis}>Слить другой флот сюда…</button>
        <button type="button" class="btn-secondary fleet-open-split" ${dis}>Разделить флот…</button>
        <button type="button" class="btn-secondary fleet-open-disband" ${dis}>Расформировать этот флот…</button>
      </div>
    `;

    const readCompositionFromInputs = () => {
      const o = {};
      for (const k of qtyKeys) {
        const inp = fleetModalBody.querySelector(`input.fleet-qty-input[data-u="${k}"]`);
        o[k] = inp ? Math.max(0, Math.floor(Number(inp.value) || 0)) : 0;
      }
      return o;
    };

    const refreshNetPreview = () => {
      const el = fleetModalBody.querySelector("#fleet-comp-net-preview");
      if (!el) return;
      const next = readCompositionFromInputs();
      const { net } = fleetCompositionNet(comp, next);
      el.innerHTML = `<div><b>Склад домашней планеты</b> (оценка до сохранения)</div><div style="margin-top:6px;">${formatImpWarehouseNetHtml(net)}</div>`;
    };
    refreshNetPreview();
    fleetModalBody.oninput = (ev) => {
      if (ev.target && ev.target.classList && ev.target.classList.contains("fleet-qty-input")) refreshNetPreview();
    };

    for (const btn of fleetModalBody.querySelectorAll("button.fleet-qty-step")) {
      btn.addEventListener("click", () => {
        const u = btn.getAttribute("data-u");
        const s = Number(btn.getAttribute("data-s"));
        if (!u || !Number.isFinite(s)) return;
        const inp = fleetModalBody.querySelector(`input.fleet-qty-input[data-u="${u}"]`);
        if (!inp || inp.disabled) return;
        const v = Math.max(0, Math.floor(Number(inp.value) || 0) + s);
        inp.value = String(v);
        refreshNetPreview();
      });
    }

    const saveBtn = fleetModalBody.querySelector(".fleet-modal-save");
    const rInp = fleetModalBody.querySelector(".fleet-rename-input");
    if (saveBtn && rInp) {
      saveBtn.addEventListener("click", async () => {
        const composition = readCompositionFromInputs();
        await saveFleetModalAll(f.id, rInp.value, composition);
      });
    }

    const mergeBtn = fleetModalBody.querySelector(".fleet-open-merge");
    if (mergeBtn) {
      mergeBtn.addEventListener("click", () => {
        if (others.length === 0) {
          setStatus("Нет других флотов для слияния", "err");
          return;
        }
        openFleetSubModal({
          title: `Слить во флот «${fn}»`,
          confirmLabel: "Слить",
          bodyHtml: `<p class="muted" style="margin-top:0;">Флот-источник будет удалён, все его корабли перейдут в <b>${escHtml(fn)}</b>.</p>
            <label class="muted" style="font-size:90%;display:block;margin-bottom:6px;">Флот-источник</label>
            <select id="fleet-merge-sub-sel" style="width:100%;padding:6px 8px;">${mergeOpts}</select>`,
          onConfirm: async () => {
            const sel = fleetSubBody && fleetSubBody.querySelector("#fleet-merge-sub-sel");
            const sid = sel ? String(sel.value || "").trim() : "";
            if (!sid) {
              setStatus("Выберите флот для слияния", "err");
              return;
            }
            await mergeFleetsApi(f.id, sid);
          },
        });
      });
    }

    const disBtn = fleetModalBody.querySelector(".fleet-open-disband");
    if (disBtn) {
      disBtn.addEventListener("click", () => {
        openFleetSubModal({
          title: "Расформировать флот",
          confirmLabel: "Расформировать",
          bodyHtml: `<p class="muted" style="margin-top:0;">Флот <b>${escHtml(fn)}</b> будет удалён. Корабли списываются; на склад домашней планеты вернётся примерно <b>50%</b> их стоимости в металле, кристалле, энергии и топливе.</p>`,
          onConfirm: async () => {
            await disbandFleetApi(f.id);
          },
        });
      });
    }

    const splitBtn = fleetModalBody.querySelector(".fleet-open-split");
    if (splitBtn) {
      splitBtn.addEventListener("click", () => {
        const rows = qtyKeys
          .map((k) => {
            const lab = fleetUnitLabel(k);
            return `<div class="row fleet-split-row" style="justify-content:space-between;align-items:center;margin-bottom:8px;gap:10px;flex-wrap:wrap;">
              <span><b>${escHtml(lab)}</b> <span class="muted">(${escHtml(k)})</span></span>
              <input type="number" class="fleet-split-qty" data-u="${escHtml(k)}" min="0" max="99999" value="0" style="width:80px;padding:6px 8px;" ${blocked ? "disabled" : ""}/>
            </div>`;
          })
          .join("");
        openFleetSubModal({
          title: `Разделить «${fn}»`,
          confirmLabel: "Создать отделение",
          bodyHtml: `<p class="muted" style="margin-top:0;">Укажите, сколько кораблей каждого типа уходит в <b>новый</b> флот. Остаток остаётся здесь. Сумма по типам не должна равняться всему текущему составу.</p>${rows}`,
          onConfirm: async () => {
            const take = {};
            for (const k of qtyKeys) {
              const inp = fleetSubBody && fleetSubBody.querySelector(`input.fleet-split-qty[data-u="${k}"]`);
              take[k] = inp ? Math.max(0, Math.floor(Number(inp.value) || 0)) : 0;
            }
            await splitFleetApi(f.id, take);
          },
        });
      });
    }

    const lBtn = fleetModalBody.querySelector(".fleet-locate-this");
    if (lBtn)
      lBtn.addEventListener("click", async () => {
        await focusFleetOnMap(f.id);
        closeFleetModal();
      });
  };

  const loadWorldState = async () => {
    try {
      const r = await fetch("/api/world/state");
      if (!r.ok) return;
      const body = await r.json();
      worldState = body || worldState;
      if (body && body.player_id) worldState.player_id = body.player_id;
      await fetchBalanceCached();
      if (tickEl) tickEl.textContent = String(body.current_sol ?? body.current_tick ?? 0);
      if (body.home_planet) {
        const elP = document.getElementById("hud-pop");
        const elM = document.getElementById("hud-pop-max");
        const hp = body.home_planet;
        if (elP) elP.textContent = hp.population != null ? String(hp.population) : "—";
        if (elM) elM.textContent = hp.max_population != null ? String(hp.max_population) : "—";
      }
      if (body.economy) {
        if (topMetalEl) topMetalEl.textContent = String(body.economy.metal ?? "—");
        if (topCrystalEl) topCrystalEl.textContent = String(body.economy.crystal ?? "—");
        if (topEnergyEl) topEnergyEl.textContent = String(body.economy.energy ?? "—");
        if (topFuelEl) topFuelEl.textContent = String(body.economy.fuel ?? "—");
        if (topFoodEl) topFoodEl.textContent = String(body.economy.food ?? "—");
        if (topWaterEl) topWaterEl.textContent = String(body.economy.water ?? "—");
        if (topRpEl) {
          const rp = body.economy.research_points;
          const rpp = body.economy.research_points_per_sol;
          if (rp != null && Number.isFinite(Number(rp))) {
            const main = Math.round(Number(rp) * 100) / 100;
            const rppNum = Number(rpp);
            const extra =
              rpp != null && Number.isFinite(rppNum) && rppNum > 0
                ? ` +${Math.round(rppNum * 1000) / 1000}/сол`
                : "";
            topRpEl.textContent = `${main}${extra}`;
            topRpEl.title =
              rpp != null && Number.isFinite(rppNum) && rppNum > 0
                ? `Наука (RP): ${main}, прирост +${Math.round(rppNum * 10000) / 10000} за сол`
                : "Наука (RP)";
          } else {
            topRpEl.textContent = "—";
            topRpEl.title = "";
          }
        }
        const einf = body.economy.influence;
        if (hudInfluenceHomeEl) {
          hudInfluenceHomeEl.textContent = einf ? formatInfluenceHud(einf) : "—";
        }
      }

      const fleet = body.fleet;
      const fleets = Array.isArray(body.fleets) ? body.fleets : [];
      const owned = fleets.filter((f) => f && f.id);

      const syncHudToActive = (afFallback) => {
        const af = activeFleetId ? owned.find((f) => f.id === activeFleetId) : null;
        const u = af || afFallback || null;
        if (!u) return;
        const ao = u.active_order;
        if (unitStatusEl) {
          if (ao && ao.order_type === "emergency_return") unitStatusEl.textContent = "аварийный возврат";
          else unitStatusEl.textContent = ruFleetStatus(u.status);
        }
        if (unitPosEl) unitPosEl.textContent = `${u.x}, ${u.y}, ${u.z}`;
        const hu = document.getElementById("hud-unit");
        if (hu) {
          const nm = u.name && String(u.name).trim() ? String(u.name).trim() : "Флот";
          const cl = formatComposition(u.composition);
          hu.textContent = `${nm} · ${cl || u.unit_type || "—"}`;
        }
        if (ao && ao.pending_combat && ao.combat_prompt_expires_at) {
          if (etaEl) etaEl.textContent = "Ждём второго подтверждения боя";
          if (etaArriveEl) etaArriveEl.textContent = ao.combat_prompt_expires_at.slice(11, 19) || "—";
        } else if (ao && (ao.remaining_ticks !== undefined || ao.finish_tick !== undefined)) {
          const eta = Number.isInteger(ao.remaining_ticks) ? ao.remaining_ticks : null;
          const arrive = Number.isInteger(ao.finish_tick) ? ao.finish_tick : null;
          if (etaEl) {
            const pref = ao && ao.order_type ? `${ruOrderType(ao.order_type)}: ` : "";
            etaEl.textContent = eta === null ? "—" : `${pref}${eta} ${solWord(eta)}`;
          }
          if (etaArriveEl) etaArriveEl.textContent = arrive === null ? "—" : `сол ${arrive}`;
        } else {
          if (etaEl) etaEl.textContent = "—";
          if (etaArriveEl) etaArriveEl.textContent = "—";
        }
      };

      syncHudToActive(fleet || (owned.length ? owned[0] : null));

      renderEvents(body.events);
      updateSelectedPanel();
      renderFlightOverlay();
      openOrRefreshCombatArrivalPrompt(body);

      if (fleetSelectEl) {
        const prev = activeFleetId;
        if (!activeFleetId && owned.length > 0) activeFleetId = owned[0].id;
        if (prev && owned.some((f) => f.id === prev)) activeFleetId = prev;
        fleetSelectEl.innerHTML = owned
          .map((f) => {
            const sel = f.id === activeFleetId ? "selected" : "";
            const lbl = escHtml(fleetOptionLabel(f));
            return `<option value="${f.id}" ${sel}>${lbl}</option>`;
          })
          .join("");
        syncHudToActive(fleet || (owned.length ? owned[0] : null));
      }
    } catch (_e) {
      // ignore
    }
    if (techModalOverlay && !techModalOverlay.classList.contains("hidden") && techModalBody) {
      void loadTechModalContent();
    }
  };

  const closeTechModal = () => {
    if (techModalOverlay) techModalOverlay.classList.add("hidden");
  };

  const openTechModal = async () => {
    if (!techModalOverlay || !techModalBody) return;
    techModalOverlay.classList.remove("hidden");
    await loadTechModalContent();
  };

  const ECON_PREF_KEY = "gs.economyModal.v1";
  const readEconPrefs = () => {
    try {
      const raw = localStorage.getItem(ECON_PREF_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (_e) {
      return {};
    }
  };
  const writeEconPrefs = (patch) => {
    try {
      const cur = readEconPrefs();
      localStorage.setItem(ECON_PREF_KEY, JSON.stringify({ ...cur, ...patch }));
    } catch (_e) {
      /* ignore */
    }
  };
  const econShowExternalBuildings = () => {
    const p = readEconPrefs();
    return p.showExternalBuildings !== false;
  };

  const loadEconomyModalContent = async () => {
    if (!economyModalBody) return;
    const showExt = econShowExternalBuildings();
    try {
      const r = await fetch(`/api/economy/summary?include_external_buildings=${showExt ? 1 : 0}`);
      const body = await r.json();
      if (!r.ok || !body || !body.ok) {
        economyModalBody.innerHTML = `<div class="muted">Статистика недоступна: ${escHtml(String((body && body.error) || "failed"))}</div>`;
        return;
      }
      const tHome = body.treasury_home || {};
      const tEmp = body.treasury_empire || {};
      const net = body.net_per_sol || {};
      const netHome = body.net_home_per_sol || {};
      const prod = body.production_per_sol || {};
      const costs = body.costs_per_sol || {};
      const binfo = body.buildings || {};
      const fleets = Array.isArray(body.fleets) ? body.fleets : [];
      const fd = body.field_data || {};
      const cref = body.construction_reference || {};
      const crefB = cref.buildings_replacement_cost || {};
      const crefF = cref.fleet_ships_replacement_cost || {};

      const fmt = (n) => (Number.isFinite(Number(n)) ? String(Number(n)) : "0");
      const fmtSigned = (n) => {
        const v = Number(n) || 0;
        const s = v > 0 ? "+" : "";
        return `${s}${v}`;
      };
      const resIcons = {
        metal: "⛏",
        crystal: "💎",
        energy: "⚡",
        fuel: "⛽",
        food: "🍲",
        water: "💧",
      };
      const resKeys = ["metal", "crystal", "energy", "fuel", "food", "water"];
      const resGrid = (map, useSigned = false) => {
        const f = useSigned ? fmtSigned : fmt;
        return `<div class="econ-resource-grid">${resKeys
          .map((k) => {
            const ic = resIcons[k] || k;
            return `<span>${ic} <b>${escHtml(f(map && map[k]))}</b></span>`;
          })
          .join("")}</div>`;
      };
      const costRow = (label, map, keys) => {
        const parts = keys.map((k) => {
          const ic = resIcons[k] || k;
          return `<span>${ic} <b>${escHtml(fmt(map && map[k]))}</b></span>`;
        });
        return `<div class="econ-cost-row"><span class="econ-row-label">${escHtml(label)}</span>${parts.join("")}</div>`;
      };
      const resKeys4 = ["metal", "crystal", "energy", "fuel"];
      const resGridFour = (map) =>
        `<div class="econ-resource-grid" style="grid-template-columns:repeat(4,1fr)">${resKeys4
          .map((k) => {
            const ic = resIcons[k];
            return `<span>${ic} <b>${escHtml(fmt(map && map[k]))}</b></span>`;
          })
          .join("")}</div>`;

      const showExtChk = `<div class="econ-card">
        <label class="econ-toggle"><input type="checkbox" id="econ-show-ext" ${showExt ? "checked" : ""} />
        <span>Учитывать/показывать внешние постройки</span></label>
      </div>`;

      const fleetsHtml = fleets.length
        ? `<p class="econ-muted">Расформирование возвращает часть ресурсов на домашнюю планету.</p>
           ${fleets
             .map(
               (f) => `<div class="econ-fleet-row">
                 <span><b>${escHtml(f.name || "Флот")}</b> • кораблей: ${escHtml(String(f.ships || 0))} • (${escHtml(
                 `${f.pos && f.pos.x != null ? f.pos.x : "?"},${f.pos && f.pos.y != null ? f.pos.y : "?"},${f.pos && f.pos.z != null ? f.pos.z : 0}`
               )})</span>
                 <button type="button" class="btn-danger" data-econ-disband="${escHtml(String(f.id))}">Расформировать</button>
               </div>`
             )
             .join("")}`
        : `<p class="econ-muted">Нет активных флотов.</p>`;

      economyModalBody.innerHTML = `
        <div class="econ-modal">
          <div class="econ-lead">Текущий сол: <b>${escHtml(String(body.current_sol ?? body.current_tick ?? 0))}</b> • Наука: <b>${escHtml(
        String(body.research_points ?? 0)
      )}</b> <span class="muted">(+${escHtml(String(body.research_points_per_sol ?? 0))}/сол)</span></div>
          ${showExtChk}

          <section class="econ-section">
            <h4 class="econ-section-title">Строительство (справочно)</h4>
            <div class="econ-card">
              <p class="econ-muted">${escHtml(String(cref.note || ""))}</p>
              <div class="econ-section-title" style="margin-top:0;font-size:0.76rem;">Постройки (сумма цен по балансу, ×уровень)</div>
              ${resGridFour(crefB)}
              <div class="econ-section-title" style="margin-top:12px;">Корабли во флотах (сумма цен по балансу)</div>
              ${resGridFour(crefF)}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Склад</h4>
            <div class="econ-card">
              <p class="econ-muted">Еда/вода копятся на планетах, автоперевоза между планетами нет. Поэтому «дом» может быть 0 при положительном балансе по империи.</p>
              <div class="econ-section-title" style="margin-top:0;font-size:0.76rem;">Дом</div>
              ${resGrid(tHome)}
              <div class="econ-section-title" style="margin-top:12px;">Империя (сумма планет)</div>
              ${resGrid(tEmp)}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Баланс за сол</h4>
            <div class="econ-card">
              <div class="econ-section-title" style="margin-top:0;font-size:0.76rem;">Итог по империи</div>
              ${resGrid(net, true)}
              <p class="econ-muted" style="margin-top:10px;margin-bottom:0;">Домашняя планета (за сол)</p>
              ${resGrid(netHome, true)}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Доходы за сол</h4>
            <div class="econ-card">
              <p class="econ-muted">Сумма по всем вашим планетам (включая постройки/техи/расу/влияние).</p>
              ${resGrid(prod)}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Расходы за сол</h4>
            <div class="econ-card">
              ${costRow("Население", costs.population_vitals, ["food", "water"])}
              ${costRow("Логистика форпостов", costs.outpost_supply_logistics || {}, ["food", "water"])}
              ${costRow("Содержание форпостов", costs.outpost_upkeep, ["metal", "crystal", "energy", "fuel"])}
              ${costRow("Имперские расходы флотов", costs.fleet_empire_upkeep, ["metal", "crystal"])}
              ${costRow("Энергия флотов (upkeep)", costs.fleet_energy_upkeep, ["energy"])}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Постройки</h4>
            <div class="econ-card">
              На планетах: <b>${escHtml(String(binfo.planet_buildings ?? 0))}</b> • Внешние: <b>${escHtml(
        String(binfo.external_buildings ?? 0)
      )}</b>${binfo.external_buildings_hidden ? ` <span class="muted">(скрыто: ${escHtml(String(binfo.external_buildings_hidden))})</span>` : ""}
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Полевые данные</h4>
            <div class="econ-card">
              <p class="econ-muted">Нужно для части исследований.</p>
              <div>ruin_archives: <b>${escHtml(String(fd.ruin_archives ?? 0))}</b> • anomaly_data: <b>${escHtml(
        String(fd.anomaly_data ?? 0)
      )}</b> • research_fragments: <b>${escHtml(String(fd.research_fragments ?? 0))}</b></div>
            </div>
          </section>

          <section class="econ-section">
            <h4 class="econ-section-title">Флоты</h4>
            <div class="econ-card">${fleetsHtml}</div>
          </section>
        </div>
      `;

      const chk = economyModalBody.querySelector("#econ-show-ext");
      if (chk) {
        chk.addEventListener("change", async () => {
          writeEconPrefs({ showExternalBuildings: Boolean(chk.checked) });
          await loadEconomyModalContent();
          // Перерисуем карту, если пользователь скрывает внешние постройки.
          renderMap();
        });
      }
      for (const b of economyModalBody.querySelectorAll("button[data-econ-disband]")) {
        b.addEventListener("click", async () => {
          const fid = b.getAttribute("data-econ-disband");
          if (!fid) return;
          if (!confirm("Расформировать флот?")) return;
          await disbandFleetApi(fid);
          await loadEconomyModalContent();
        });
      }
    } catch (_e) {
      economyModalBody.innerHTML = "<div class='muted'>Ошибка загрузки статистики.</div>";
    }
  };

  const openEconomyModal = async () => {
    if (!economyModalOverlay || !economyModalBody) return;
    economyModalOverlay.classList.remove("hidden");
    await loadEconomyModalContent();
  };
  const closeEconomyModal = () => {
    if (economyModalOverlay) economyModalOverlay.classList.add("hidden");
  };

  const formatTechCost = (cost) => {
    if (!cost || typeof cost !== "object") return "—";
    const parts = [];
    if (Number.isFinite(cost.metal)) parts.push(`⛏ ${cost.metal}`);
    if (Number.isFinite(cost.crystal)) parts.push(`💎 ${cost.crystal}`);
    if (Number.isFinite(cost.energy)) parts.push(`⚡ ${cost.energy}`);
    if (Number.isFinite(cost.fuel)) parts.push(`⛽ ${cost.fuel}`);
    return parts.length ? parts.join(" · ") : "—";
  };

  const formatTechEffectsRu = (eff) => {
    if (!eff || typeof eff !== "object") return [];
    const lines = [];
    if (typeof eff.travel_fuel_multiplier === "number") {
      lines.push(`Топливо на полёт: множитель ×${eff.travel_fuel_multiplier} (чем меньше, тем дешевле).`);
    }
    if (eff.production_multiplier && typeof eff.production_multiplier === "object") {
      for (const [k, v] of Object.entries(eff.production_multiplier)) {
        lines.push(`Производство «${k}»: ×${v}`);
      }
    }
    for (const [k, v] of Object.entries(eff)) {
      if (k === "travel_fuel_multiplier" || k === "production_multiplier") continue;
      if (typeof v === "number") lines.push(`${k}: ×${v}`);
      else if (v && typeof v === "object") lines.push(`${k}: ${JSON.stringify(v)}`);
    }
    return lines;
  };

  const formatPrereqNames = (prereq, byTechId) => {
    const arr = Array.isArray(prereq) ? prereq : [];
    if (!arr.length) return "нет";
    return arr
      .map((id) => {
        const t = byTechId[id];
        return t && t.name ? `${t.name} (${id})` : String(id);
      })
      .join(", ");
  };

  const techUiPrefsKey = "gs.techModal.v1";
  const readTechUiPrefs = () => {
    try {
      const raw = localStorage.getItem(techUiPrefsKey);
      return raw ? JSON.parse(raw) : {};
    } catch (_e) {
      return {};
    }
  };
  const writeTechUiPrefs = (patch) => {
    try {
      const cur = readTechUiPrefs();
      localStorage.setItem(techUiPrefsKey, JSON.stringify({ ...cur, ...patch }));
    } catch (_e) {
      /* ignore */
    }
  };

  const loadTechModalContent = async () => {
    if (!techModalBody) return;
    try {
      if (!window.__guardstarBalanceCache)
        window.__guardstarBalanceCache = { ts: 0, body: null, backoffUntil: 0 };
      const bc = window.__guardstarBalanceCache;
      const nowTs = Date.now();
      if (bc.backoffUntil && nowTs < bc.backoffUntil) {
        techModalBody.innerHTML =
          "<div class='muted'>Баланс временно недоступен. Повторите через несколько секунд.</div>";
        return;
      }
      const balBody = await fetchBalanceCached();
      if (!balBody || !balBody.ok) {
        techModalBody.innerHTML = "<div class='muted'>Баланс недоступен.</div>";
        return;
      }

      const st = await fetch("/api/tech/state");
      const stBody = await st.json();
      if (!st.ok || !stBody.ok) {
        techModalBody.innerHTML = "<div class='muted'>Состояние исследований недоступно.</div>";
        return;
      }
      const currentTick = Number.isInteger(stBody.current_sol)
        ? stBody.current_sol
        : Number.isInteger(stBody.current_tick)
          ? stBody.current_tick
          : 0;
      const rpPlayerBal = Number(stBody.research_points) || 0;
      const rpPlayerPerSol = Number(stBody.research_points_per_sol);
      const rows = Array.isArray(stBody.techs) ? stBody.techs : [];
      const byId = {};
      for (const r of rows) byId[r.tech_id] = r;
      const doneSet = new Set(rows.filter((r) => r && r.status === "done" && r.tech_id).map((r) => String(r.tech_id)));

      const techList = Array.isArray(balBody.tech) ? balBody.tech : [];
      const byTechId = {};
      for (const t of techList) if (t && t.id) byTechId[t.id] = t;
      const enabled = techList.filter((t) => t && t.enabled !== false);

      let effectsBody = null;
      try {
        const er = await fetch("/api/effects/active");
        const eb = await er.json();
        if (er.ok && eb && eb.ok) effectsBody = eb;
      } catch (_e2) {
        effectsBody = null;
      }

      const prefs = readTechUiPrefs();
      const validTechTabs = new Set(["all", "available", "in_progress", "done"]);
      let activeTab = validTechTabs.has(prefs.tab) ? prefs.tab : "available";
      let hideDone = prefs.hideDone !== false;

      const techStatus = (t) => {
        const st0 = byId[t.id] || null;
        return st0 && st0.status ? st0.status : "none";
      };

      const techPrereqMissing = (t) => {
        const prereqArr = Array.isArray(t.prereq) ? t.prereq.filter((x) => typeof x === "string" && x.trim()) : [];
        return prereqArr.filter((id) => !doneSet.has(String(id)));
      };
      const techFieldDataMissing = (t) => {
        const fdReq = Array.isArray(t.field_data_requirements)
          ? t.field_data_requirements.filter((x) => typeof x === "string" && x.trim())
          : [];
        const effs = effectsBody && Array.isArray(effectsBody.effects) ? effectsBody.effects : [];
        const effCount = (k) => effs.filter((e) => e && e.effect_type === k && e.used_at_tick == null).length;
        return fdReq.filter((k) => effCount(k) < 1);
      };
      const techCanStart = (t) => {
        if (techStatus(t) !== "none") return false;
        return techPrereqMissing(t).length === 0 && techFieldDataMissing(t).length === 0;
      };

      const renderCardInner = (t) => {
        const st0 = byId[t.id] || null;
        const status = st0 ? st0.status : "none";
        const rem = st0 && Number.isInteger(st0.remaining_ticks) ? st0.remaining_ticks : null;
        const fdReq = Array.isArray(t.field_data_requirements)
          ? t.field_data_requirements.filter((x) => typeof x === "string" && x.trim())
          : [];
        const effs = effectsBody && Array.isArray(effectsBody.effects) ? effectsBody.effects : [];
        const effCount = (k) => effs.filter((e) => e && e.effect_type === k && e.used_at_tick == null).length;
        const missingFd = fdReq.filter((k) => effCount(k) < 1);
        const missingPrereq = techPrereqMissing(t);
        const blockedReason =
          missingPrereq.length
            ? `Нужны исследования: ${formatPrereqNames(missingPrereq, byTechId)}`
            : missingFd.length
              ? `Нужны полевые данные: ${missingFd.join(", ")}`
              : null;
        const canStart = status === "none" && !blockedReason;
        const btn =
          status === "none"
            ? `<button type="button" class="btn-primary" data-tech="${escHtml(t.id)}" ${canStart ? "" : "disabled"} title="${escHtml(blockedReason || "")}">${
                canStart ? "Старт" : "Недоступно"
              }</button>`
            : "";
        const statusLine =
          status === "in_progress"
            ? `<span class="muted">Идёт исследование, осталось <b>${rem ?? "?"}</b> ${rem != null && Number.isFinite(Number(rem)) ? solWord(rem) : "солов"}.</span>`
            : status === "done"
              ? `<span class="muted">Завершено.</span>`
              : `<span class="muted">Не начато.</span>`;
        const tickN = Number(t.time_ticks);
        const residualN = Number(t.residual_time_ticks);
        const workTicks = Number.isFinite(residualN) && residualN > 0 ? residualN : tickN;
        const dur = Number.isFinite(workTicks) && workTicks > 0 ? `${Math.round(workTicks)} ${solWord(workTicks)}` : "—";
        const costStr = formatTechCost(t.cost);
        const rpNeed = Number(t.research_points_cost);
        const payBits = [];
        if (Number.isFinite(rpNeed) && rpNeed > 0) payBits.push(`наука ${rpNeed}`);
        if (costStr && costStr !== "—") payBits.push(costStr);
        const payLine = payBits.length ? payBits.join(" · ") : "—";
        const prereqStr = formatPrereqNames(t.prereq, byTechId);
        const fdLine = fdReq.length ? `<div class="tech-item-meta" style="margin-top:8px;">Полевые данные: <b>${escHtml(fdReq.join(", "))}</b></div>` : "";
        const effLines = formatTechEffectsRu(t.effects);
        const desc =
          typeof t.description === "string" && t.description.trim()
            ? escHtml(t.description.trim())
            : effLines.length
              ? "После завершения:"
              : "Описание в балансе не задано.";
        const effBlock =
          effLines.length > 0
            ? `<ul class="tech-item-effects">${effLines.map((line) => `<li>${escHtml(line)}</li>`).join("")}</ul>`
            : "<div class='muted' style='margin-top:6px;'>Эффекты не указаны в балансе.</div>";

        return `
            <div class="tech-item-title">
              <div><b>${escHtml(t.name || t.id)}</b> <span class="muted">(${escHtml(t.id)})</span></div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">${statusLine}${btn}</div>
            </div>
            <div class="tech-item-meta">Тир ${escHtml(String(t.tier ?? "—"))} • длительность работы: <b>${escHtml(dur)}</b> • оплата при старте: ${escHtml(payLine)}</div>
            <div class="tech-item-desc">${desc}</div>
            ${effBlock}
            <div class="tech-item-meta" style="margin-top:8px;">Предпосылки: ${escHtml(prereqStr)}</div>
            ${fdLine}
        `;
      };

      const renderCard = (t) => {
        const status = techStatus(t);
        const inner = renderCardInner(t);
        if (status === "done") {
          return `
          <details class="tech-item tech-item-done">
            <summary class="tech-item-summary">${escHtml(t.name || t.id)} <span class="muted">(${escHtml(t.id)}) — завершено</span></summary>
            <div class="tech-item-details-inner">${inner}</div>
          </details>`;
        }
        const activeCls = status === "in_progress" ? " tech-item-active" : "";
        return `<div class="tech-item${activeCls}">${inner}</div>`;
      };

      const matchesSearch = (t, q) => {
        if (!q) return true;
        const id = String(t.id || "").toLowerCase();
        const nm = String(t.name || "").toLowerCase();
        return id.includes(q) || nm.includes(q);
      };

      const filterList = (qRaw) => {
        const q = (qRaw || "").trim().toLowerCase();
        return enabled.filter((t) => {
          const st = techStatus(t);
          if (!matchesSearch(t, q)) return false;
          if (activeTab === "available") return techCanStart(t);
          if (activeTab === "in_progress") return st === "in_progress";
          if (activeTab === "done") return st === "done";
          if (activeTab === "all") {
            if (hideDone && st === "done") return false;
            return true;
          }
          return true;
        });
      };

      const paint = (searchVal) => {
        const list = filterList(searchVal);
        const elList = techModalBody.querySelector("#tech-modal-list");
        if (!elList) return;
        elList.innerHTML = list.map(renderCard).join("") || "<div class='muted'>Нет технологий по фильтру.</div>";
        for (const b of elList.querySelectorAll("button[data-tech]")) {
          b.addEventListener("click", async () => {
            if (b.disabled) return;
            const tech_id = b.getAttribute("data-tech");
            setStatus("Старт исследования...");
            const r = await fetch("/api/tech/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tech_id }),
            });
            const body = await r.json();
            if (!r.ok || !body.ok) {
              setStatus(`Ошибка tech: ${body.error || "start_failed"}`, "err");
              await loadTechModalContent();
              return;
            }
            const extra = [];
            if (body.research_time_multiplier && body.research_time_multiplier < 0.999)
              extra.push(`ускорение ×${Number(body.research_time_multiplier).toFixed(2)}`);
            if (body.blueprint_cache_consumed) extra.push("кэш чертежей");
            setStatus(`Исследование запущено: ${tech_id}${extra.length ? " (" + extra.join(", ") + ")" : ""}`, "ok");
            await loadTechModalContent();
          });
        }
      };

      techModalBody.innerHTML = `
        <div class="muted" style="margin-bottom:10px;">Текущий сол: <b>${currentTick}</b> • Наука: <b>${escHtml(String(Math.round(rpPlayerBal * 100) / 100))}</b>${
        Number.isFinite(rpPlayerPerSol) && rpPlayerPerSol > 0
          ? ` <span class="muted">(+${escHtml(String(Math.round(rpPlayerPerSol * 1000) / 1000))}/сол)</span>`
          : ""
      }</div>
        <div id="tech-effects" class="tech-effects"></div>
        <div class="tech-toolbar">
          <div class="tech-tabs" role="tablist">
            <button type="button" class="tech-tab${activeTab === "available" ? " is-active" : ""}" data-tech-tab="available">Доступные</button>
            <button type="button" class="tech-tab${activeTab === "all" ? " is-active" : ""}" data-tech-tab="all">Все</button>
            <button type="button" class="tech-tab${activeTab === "in_progress" ? " is-active" : ""}" data-tech-tab="in_progress">В процессе</button>
            <button type="button" class="tech-tab${activeTab === "done" ? " is-active" : ""}" data-tech-tab="done">Завершённые</button>
          </div>
          <label class="tech-hide-done"><input type="checkbox" id="tech-hide-done" ${hideDone ? "checked" : ""}/> Скрыть завершённые</label>
          <input type="search" id="tech-search" class="tech-search" placeholder="Поиск по имени или id…" autocomplete="off" />
        </div>
        <div id="tech-modal-list" class="tech-modal-list"></div>
      `;

      const effectsEl = techModalBody.querySelector("#tech-effects");
      const renderEffects = () => {
        if (!effectsEl) return;
        const effects = effectsBody && Array.isArray(effectsBody.effects) ? effectsBody.effects : [];
        const lines = [];
        for (const e of effects) {
          if (!e || typeof e !== "object") continue;
          const t = String(e.effect_type || "");
          if (t === "bandit_ambush_cooldown") continue; // системное
          if (t === "research_speed_boost") {
            const m = e.payload && typeof e.payload.time_multiplier === "number" ? e.payload.time_multiplier : 1.0;
            const pct = Math.max(0, Math.round((1.0 - m) * 100));
            const rem = Number.isInteger(e.remaining_ticks) ? e.remaining_ticks : null;
            lines.push(`- Архив/телеметрия: исследования быстрее на ${pct}%${rem != null ? `, осталось ${rem} ${solWord(rem)}` : ""}`);
          } else if (t === "blueprint_cache") {
            lines.push("- Кэш чертежей: скидка на следующее исследование");
          } else {
            lines.push(`- ${escHtml(t)}`);
          }
        }
        effectsEl.innerHTML =
          `<div class="tech-effects-title"><b>Активные эффекты</b></div>` +
          (lines.length ? `<div class="tech-effects-list">${lines.map((x) => `<div>${escHtml(x)}</div>`).join("")}</div>` : `<div class="muted">Нет активных эффектов.</div>`);
      };
      renderEffects();

      const searchInput = techModalBody.querySelector("#tech-search");
      const hideChk = techModalBody.querySelector("#tech-hide-done");

      for (const tabBtn of techModalBody.querySelectorAll("button[data-tech-tab]")) {
        tabBtn.addEventListener("click", () => {
          activeTab = tabBtn.getAttribute("data-tech-tab") || "available";
          writeTechUiPrefs({ tab: activeTab });
          for (const b of techModalBody.querySelectorAll("button[data-tech-tab]")) b.classList.toggle("is-active", b.getAttribute("data-tech-tab") === activeTab);
          paint(searchInput ? searchInput.value : "");
        });
      }
      if (hideChk) {
        hideChk.addEventListener("change", () => {
          hideDone = Boolean(hideChk.checked);
          writeTechUiPrefs({ hideDone });
          paint(searchInput ? searchInput.value : "");
        });
      }
      if (searchInput) {
        searchInput.addEventListener("input", () => paint(searchInput.value));
      }

      paint(searchInput ? searchInput.value : "");
    } catch (_e) {
      techModalBody.innerHTML = "<div class='muted'>Ошибка загрузки исследований.</div>";
    }
  };

  const renderMap = () => {
    if (!mapEl || !currentWindow || !currentWindow.cells) return;
    const size = currentWindow.radius * 2 + 1;
    mapEl.innerHTML = "";
    mapEl.style.setProperty("--map-size", String(size));
    // Одна и та же «ширина поля»: при 21×21 ячейки ужимаются относительно 9×9 (база — --cell-size).
    const baseCell =
      Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--cell-size"), 10) || 96;
    const refCells = 9;
    const layoutCell = Math.max(22, Math.min(baseCell, Math.round((baseCell * refCells) / size)));
    mapEl.style.setProperty("--map-layout-cell", `${layoutCell}px`);

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
        const outpostObj = (c.objects || []).find((o) => o.type === "outpost");
        const showExternalBuildings = econShowExternalBuildings();
        const buildingObj = (c.objects || []).find((o) => {
          if (!o || o.type !== "building") return false;
          if (!showExternalBuildings && c.terrain !== "planet") return false;
          return true;
        });
        const hasAnyFleet = Boolean(anyFleetObj);
        const isEnemyFleet = anyFleetObj && playerId && anyFleetObj.owner && anyFleetObj.owner !== playerId;
        const isEnemyPlanet = planetObj && playerId && planetObj.owner && planetObj.owner !== playerId;

        if (hasObjects) btn.classList.add("cell-object");
        if (isCenter) btn.classList.add("cell-center");
        // Флот не должен давать рамку у клетки (только пиктограмма/свечение).
        // if (hasAnyFleet) btn.classList.add("cell-unit", "cell-current");
        if (zoneVisionSelf) btn.classList.add("zone-vision-self");
        if (zoneBuildEnemy) btn.classList.add("zone-build-enemy");
        if (zoneBuildSelf) btn.classList.add("zone-build-self");
        if (isVisible) {
          btn.classList.add("cell-visible");
        } else {
          if (fogState === "memory") btn.classList.add("cell-memory");
          else if (fogState === "stale") btn.classList.add("cell-stale");
          else btn.classList.add("cell-fog");
        }
        // Кант владельца показываем только для планет, чтобы флот не выглядел как "зона влияния".
        if (isEnemyPlanet) btn.classList.add("cell-enemy");
        if (planetObj && !isEnemyPlanet && playerId) btn.classList.add("cell-ally");
        const infl = isVisible && c.influence ? c.influence : null;
        if (infl) {
          const topPlayerId = Array.isArray(infl.top) && infl.top[0] ? String(infl.top[0].player_id || "") : null;
          const topIsSelf = topPlayerId && playerId && topPlayerId === String(playerId);
          if (infl.contested) btn.classList.add("cell-inf-contested");
          else if (infl.dominant_rel === "self" || (!infl.dominant_rel && topIsSelf)) btn.classList.add("cell-inf-own");
          else if (infl.dominant_rel === "other" || (!infl.dominant_rel && topPlayerId)) btn.classList.add("cell-inf-other");
        }
        if (c.terrain === "anomaly") btn.classList.add("cell-unknown");
        if (lastTarget && c.x === lastTarget.x && c.y === lastTarget.y && c.z === lastTarget.z) {
          btn.classList.add("cell-target", "move-target");
        }
        if (selectedCell && c.x === selectedCell.x && c.y === selectedCell.y && c.z === selectedCell.z) {
          btn.classList.add("cell-selected");
        }
        if (
          scout &&
          Number.isFinite(scout.x) &&
          Number.isFinite(scout.y) &&
          c.x === scout.x &&
          c.y === scout.y &&
          (c.z ?? 0) === (scout.z ?? 0)
        ) {
          btn.classList.add("cell-active-fleet");
        }
        const showSupplyBlocked =
          supplyHint &&
          supplyHint.for &&
          selectedCell &&
          supplyHint.for.x === selectedCell.x &&
          supplyHint.for.y === selectedCell.y &&
          (supplyHint.for.z ?? 0) === (selectedCell.z ?? 0) &&
          !supplyHint.inSupply &&
          supplyHint.blockedAt &&
          c.x === supplyHint.blockedAt.x &&
          c.y === supplyHint.blockedAt.y &&
          c.z === (selectedCell.z ?? 0);
        if (showSupplyBlocked) btn.classList.add("cell-supply-block");
        if (pendingFleetMove && c.x === pendingFleetMove.from.x && c.y === pendingFleetMove.from.y && c.z === pendingFleetMove.from.z) {
          btn.classList.add("cell-from");
        }
        if (pendingFleetMove && c.x === pendingFleetMove.to.x && c.y === pendingFleetMove.to.y && c.z === pendingFleetMove.to.z) {
          btn.classList.add("cell-to");
        }

        const terrainIcon =
          c.terrain === "planet"
            ? "<span class='terrain-icon'>🪐</span>"
            :
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
        const outpostMarker = outpostObj
          ? `<span class="terrain-icon" aria-label="Форпост">${String(outpostObj.owner) === String(playerId) ? "🏰" : "🏯"}</span>`
          : null;

        const buildingMarker = buildingObj
          ? `<span class="terrain-icon" aria-label="Постройка">${buildingObj.building_type === "mine" ? "⛏" : (buildingObj.building_type === "reactor" ? "⚙" : "💎")}</span>`
          : null;

        const marker = planetMarker || fleetMarker || outpostMarker || buildingMarker || terrainIcon;
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
        let tip = `Сектор (${c.x}, ${c.y}, z=${c.z})`;
        const danger = c.flags && c.flags.danger_level ? String(c.flags.danger_level) : null;
        if (danger) {
          const ru = danger === "high" ? "высокая" : danger === "medium" ? "средняя" : "низкая";
          tip = `${tip} • Опасность: ${ru}`;
        }
        const myFleetHere =
          playerId && anyFleetObj && anyFleetObj.owner === playerId && String(anyFleetObj.owner) === String(playerId);
        if (myFleetHere && anyFleetObj.name)
          tip = `${tip} • ${anyFleetObj.name}`;
        btn.title = tip;

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
          const myFleetObj = playerId
            ? (c.objects || []).find((o) => o && o.type === "fleet" && String(o.owner) === String(playerId))
            : null;
          if (myFleetObj && myFleetObj.id) {
            activeFleetId = String(myFleetObj.id);
            if (fleetSelectEl) fleetSelectEl.value = activeFleetId;
          }
          updateSelectedPanel();
          if (cellHasPlanet(c)) void openPlanetModal(c);
          else closePlanetModal();
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
      const isEmergency = ao && ao.order_type === "emergency_return";
      line.setAttribute("class", isEmergency ? "flight-line flight-line-emergency" : "flight-line");

      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(y));
      dot.setAttribute("r", "6");
      dot.setAttribute("class", isEmergency ? "flight-dot flight-dot-emergency" : "flight-dot");

      flightOverlayEl.appendChild(line);
      flightOverlayEl.appendChild(dot);
    }
  };

  const renderZoneOverlay = () => {
    if (!zoneOverlayEl || !mapEl || !mapLayerEl || !currentWindow || !currentWindow.cells) return;
    const size = currentWindow.radius * 2 + 1;
    const cellSize =
      Number.parseInt(getComputedStyle(mapEl).getPropertyValue("--map-layout-cell"), 10) ||
      Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--cell-size"), 10) ||
      96;

    // overlay должен совпадать с размером контента карты и скроллиться вместе с ним
    mapLayerEl.style.width = `${size * cellSize}px`;
    mapLayerEl.style.height = `${size * cellSize}px`;
    zoneOverlayEl.setAttribute("viewBox", `0 0 ${size * cellSize} ${size * cellSize}`);
    zoneOverlayEl.setAttribute("width", String(size * cellSize));
    zoneOverlayEl.setAttribute("height", String(size * cellSize));
    zoneOverlayEl.innerHTML = "";

    const ns = "http://www.w3.org/2000/svg";

    // DEBUG рамка (чтобы понять, виден ли слой вообще)
    const dbg = document.createElementNS(ns, "rect");
    dbg.setAttribute("x", "0");
    dbg.setAttribute("y", "0");
    dbg.setAttribute("width", String(size * cellSize));
    dbg.setAttribute("height", String(size * cellSize));
    dbg.setAttribute("fill", "none");
    dbg.setAttribute("stroke", "rgba(255,0,255,0.18)");
    dbg.setAttribute("stroke-width", "2");
    zoneOverlayEl.appendChild(dbg);

    // defs: wavy filter
    const defs = document.createElementNS(ns, "defs");
    defs.innerHTML = `
      <filter id="wavyLine" x="-10%" y="-10%" width="120%" height="120%">
        <feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="1" seed="2" result="noise"/>
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G"/>
      </filter>
    `;
    zoneOverlayEl.appendChild(defs);

    // Convert window cells to quick lookup
    const rows = currentWindow.cells;
    const inBuild = new Set();
    const inVision = new Set();
    const inControlSelf = new Set();
    const inControlOther = new Set();
    for (let yi = 0; yi < rows.length; yi++) {
      const row = rows[yi].row;
      for (let xi = 0; xi < row.length; xi++) {
        const c = row[xi];
        const key = `${c.x},${c.y},${c.z}`;
        if (c.flags && c.flags.zone_build_self) inBuild.add(key);
        if (c.flags && c.flags.zone_vision_self) inVision.add(key);
        const controlOwner = c.influence && c.influence.control ? c.influence.control.owner : null;
        if (controlOwner && playerId && String(controlOwner) === String(playerId)) inControlSelf.add(key);
        else if (controlOwner) inControlOther.add(key);
      }
    }

    const cellIndexKey = (x, y, z) => `${x},${y},${z}`;

    // Fallback: если сервер по какой-то причине не прислал zone_build_self,
    // восстановим зону стройки на клиенте от видимых/памятных планет игрока (радиус 3).
    // Это делает отрисовку границ устойчивой к регрессам в API.
    if (inBuild.size === 0 && playerId) {
      const myPlanets = [];
      for (let yi = 0; yi < rows.length; yi++) {
        const row = rows[yi].row;
        for (let xi = 0; xi < row.length; xi++) {
          const c = row[xi];
          const objs = Array.isArray(c.objects) ? c.objects : [];
          const p = objs.find((o) => o && o.type === "planet" && String(o.owner) === String(playerId));
          if (p) myPlanets.push({ x: c.x, y: c.y, z: c.z ?? 0 });
        }
      }
      const r = 3;
      for (const p of myPlanets) {
        for (let dy = -r; dy <= r; dy++) {
          for (let dx = -r; dx <= r; dx++) {
            if (Math.abs(dx) + Math.abs(dy) > r) continue;
            inBuild.add(cellIndexKey(p.x + dx, p.y + dy, p.z ?? 0));
          }
        }
      }
    }

    // Collect perimeter segments (axis-aligned) for a zone.
    const collectEdges = (zoneSet) => {
      const segs = [];
      for (let yi = 0; yi < rows.length; yi++) {
        const row = rows[yi].row;
        for (let xi = 0; xi < row.length; xi++) {
          const c = row[xi];
          const k = cellIndexKey(c.x, c.y, c.z);
          if (!zoneSet.has(k)) continue;

          const x0 = xi * cellSize;
          const y0 = yi * cellSize;
          const x1 = x0 + cellSize;
          const y1 = y0 + cellSize;

          const nL = cellIndexKey(c.x - 1, c.y, c.z);
          const nR = cellIndexKey(c.x + 1, c.y, c.z);
          const nU = cellIndexKey(c.x, c.y - 1, c.z);
          const nD = cellIndexKey(c.x, c.y + 1, c.z);

          if (!zoneSet.has(nL)) segs.push([x0, y0, x0, y1]);
          if (!zoneSet.has(nR)) segs.push([x1, y0, x1, y1]);
          if (!zoneSet.has(nU)) segs.push([x0, y0, x1, y0]);
          if (!zoneSet.has(nD)) segs.push([x0, y1, x1, y1]);
        }
      }
      return segs;
    };

    // Turn segments into closed loops (best-effort).
    // Важно: периметр получается как набор неориентированных рёбер, поэтому учитываем оба направления.
    const segmentsToLoops = (segs) => {
      const pkey = (x, y) => `${x},${y}`;
      const adj = new Map(); // point -> [{i, x, y, dir}]
      const used = new Set();

      const addAdj = (x1, y1, x2, y2, i, dir) => {
        const k = pkey(x1, y1);
        if (!adj.has(k)) adj.set(k, []);
        adj.get(k).push({ i, x: x2, y: y2, dir });
      };

      for (let i = 0; i < segs.length; i++) {
        const [x1, y1, x2, y2] = segs[i];
        addAdj(x1, y1, x2, y2, i, 1);
        addAdj(x2, y2, x1, y1, i, -1);
      }

      const loops = [];
      for (let i = 0; i < segs.length; i++) {
        if (used.has(i)) continue;
        const [sx, sy, ex, ey] = segs[i];
        used.add(i);

        const pts = [{ x: sx, y: sy }, { x: ex, y: ey }];
        let cx = ex;
        let cy = ey;
        let px = sx;
        let py = sy;

        for (let guard = 0; guard < 20000; guard++) {
          const options = (adj.get(pkey(cx, cy)) || []).filter((o) => !used.has(o.i));
          if (!options.length) break;

          // Prefer turning left/right rather than going straight back and forth:
          // choose option that doesn't go back to previous point if possible.
          let nxt = options.find((o) => !(o.x === px && o.y === py)) || options[0];

          used.add(nxt.i);
          pts.push({ x: nxt.x, y: nxt.y });
          px = cx;
          py = cy;
          cx = nxt.x;
          cy = nxt.y;
          if (cx === sx && cy === sy) break;
        }

        if (pts.length >= 4 && cx === sx && cy === sy) loops.push(pts);
      }
      return loops;
    };

    const loopToPathD = (pts) => {
      if (!pts || pts.length < 2) return "";
      // simplify consecutive collinear points
      const simp = [pts[0]];
      for (let i = 1; i < pts.length; i++) {
        const p = pts[i];
        const a = simp[simp.length - 1];
        const b = simp.length >= 2 ? simp[simp.length - 2] : null;
        if (b) {
          const col = (b.x === a.x && a.x === p.x) || (b.y === a.y && a.y === p.y);
          if (col) {
            simp[simp.length - 1] = p;
            continue;
          }
        }
        simp.push(p);
      }
      let d = `M ${simp[0].x} ${simp[0].y}`;
      for (let i = 1; i < simp.length; i++) d += ` L ${simp[i].x} ${simp[i].y}`;
      d += " Z";
      return d;
    };

    // Vision: без контура. Видимость и так читается по туману войны + подсветке видимых клеток.
    // Если захотим — можно вернуть мягкую заливку без “кубиков” отдельным path.

    const smoothClosedPathD = (pts, r) => {
      if (!pts || pts.length < 4) return loopToPathD(pts);
      const radius = Math.max(0, Number(r) || 0);
      if (radius <= 0) return loopToPathD(pts);

      // remove last duplicate of start for easier indexing
      const p = pts.slice(0, -1);
      const n = p.length;
      if (n < 3) return loopToPathD(pts);

      const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
      const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
      const lerp = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });

      const start = p[0];
      let d = `M ${start.x} ${start.y}`;
      for (let i = 0; i < n; i++) {
        const prev = p[(i - 1 + n) % n];
        const cur = p[i];
        const next = p[(i + 1) % n];

        const d1 = dist(prev, cur);
        const d2 = dist(cur, next);
        if (d1 === 0 || d2 === 0) continue;
        const rr = clamp(radius, 0, Math.min(d1, d2) * 0.45);

        const p1 = lerp(cur, prev, rr / d1);
        const p2 = lerp(cur, next, rr / d2);

        d += ` L ${p1.x} ${p1.y}`;
        d += ` Q ${cur.x} ${cur.y} ${p2.x} ${p2.y}`;
      }
      d += " Z";
      return d;
    };

    const drawBorder = (zoneSet, klass) => {
      const segs = collectEdges(zoneSet);
      const loops = segmentsToLoops(segs);
      const radius = Math.max(6, Math.round(cellSize * 0.22));
      if (loops.length) {
        for (const loop of loops) {
          const path = document.createElementNS(ns, "path");
          path.setAttribute("d", smoothClosedPathD(loop, radius));
          path.setAttribute("class", klass);
          zoneOverlayEl.appendChild(path);
        }
      } else if (segs.length) {
        // Fallback: рисуем сегментами, если петли не собрались (чтобы границы не “пропадали”).
        for (const [x1, y1, x2, y2] of segs) {
          const line = document.createElementNS(ns, "line");
          line.setAttribute("x1", String(x1));
          line.setAttribute("y1", String(y1));
          line.setAttribute("x2", String(x2));
          line.setAttribute("y2", String(y2));
          line.setAttribute("class", klass);
          zoneOverlayEl.appendChild(line);
        }
      }
    };

    drawBorder(inControlOther, "zone-line-other");
    drawBorder(inControlSelf, "zone-line-self");
  };

  if (mapWrapEl) {
    mapWrapEl.addEventListener("scroll", () => {
      renderFlightOverlay();
      renderZoneOverlay();
    });
  }

  // drag-pan removed

  const refreshWindow = async () => {
    const r = await fetch(`/api/world/window?radius=${viewRadius}&z=${currentZ}&center_x=${viewCenter.x}&center_y=${viewCenter.y}`);
    if (!r.ok) {
      setStatus("Ошибка загрузки карты", "err");
      return;
    }
    currentWindow = await r.json();
    if (currentWindow && currentWindow.center) viewCenter = { ...currentWindow.center };
    renderMap();
    renderZoneOverlay();
    await loadWorldState();
  };

  focusFleetOnMap = async (fleetId) => {
    const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
    const f = fleetId ? fleets.find((x) => x && x.id === fleetId) : null;
    if (!f) {
      setStatus("Флот не найден в состоянии игры (обновите сол).", "err");
      return;
    }
    activeFleetId = f.id;
    if (fleetSelectEl) fleetSelectEl.value = f.id;
    viewCenter = { x: f.x, y: f.y };
    if (Number.isFinite(f.z)) currentZ = Number(f.z);
    await refreshWindow();
    let hit = null;
    const rows = (currentWindow && currentWindow.cells) || [];
    outer: for (const row of rows) {
      for (const c of row.row || []) {
        if (c.x === f.x && c.y === f.y && c.z === f.z) {
          hit = { ...c };
          break outer;
        }
      }
    }
    selectedCell = hit || {
      x: f.x,
      y: f.y,
      z: f.z,
      objects: [],
      terrain: null,
      flags: { is_visible: true },
    };
    updateSelectedPanel();
    renderMap();
    setStatus(`Карта: ${f.name || "Флот"} (${f.x},${f.y},${f.z})`, "ok");
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
      const uiMv = loadUiSettings();
      const r = await fetch("/api/fleets/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fleet_id: fleetId,
          x,
          y,
          z,
          force_attack: Boolean(uiMv.forceAttackGuaranteed),
        }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        if (body.error === "not_enough_fuel") {
          setStatus(`Ошибка: not_enough_fuel (нужно ${body.need}, есть ${body.have})`, "err");
          return;
        }
        if (body.error === "not_enough_fleet_energy") {
          setStatus(`Ошибка: не хватает энергии флота (нужно ${body.need}, есть ${body.have})`, "err");
          return;
        }
        if (body.error === "cell_occupied_by_own_fleet") {
          setStatus("В этой клетке уже ваш флот. Два флота не могут стоять в одной клетке.", "err");
          return;
        }
        if (body.error === "active_order_exists") {
          const f = worldState && worldState.fleet && worldState.fleet.id === fleetId ? worldState.fleet : null;
          const ao = f && f.active_order ? f.active_order : null;
          const hint = ao
            ? `Уже летит в (${ao.target_x},${ao.target_y},${ao.target_z}), осталось ${ao.remaining_ticks} ${solWord(ao.remaining_ticks)}.`
            : "Флот уже в пути.";
          setStatus(`Ошибка: active_order_exists. ${hint} Можно отменить приказ.`, "err");
        } else {
          setStatus(`Ошибка: ${body.error || "fleet_move_failed"}`, "err");
        }
        return;
      }
      lastTarget = { x, y, z };
      await refreshWindow();
      setStatus(`Флот в пути: осталось ${body.travel_ticks} ${solWord(body.travel_ticks)}`, "ok");
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

  const clearCombatPromptCountdown = () => {
    if (combatPromptCountdownTimer) {
      clearInterval(combatPromptCountdownTimer);
      combatPromptCountdownTimer = null;
    }
    combatPromptExpiresAtMs = null;
  };

  const closeCombatPromptModal = () => {
    clearCombatPromptCountdown();
    combatPromptOpenForOrderId = null;
    if (combatPromptOverlay) combatPromptOverlay.classList.add("hidden");
  };

  const formatCombatPreviewText = (pr) => {
    if (!pr || !pr.combat) {
      return "В клетке цели сейчас нет вражеского флота — при «Атаковать» флот займёт клетку.";
    }
    const mine = formatComposition(pr.attacker_composition) || "—";
    const theirs = formatComposition(pr.defender_composition) || "—";
    const p = pr.p_win_attacker != null ? Math.round(Number(pr.p_win_attacker) * 100) : "—";
    const fac = pr.factors || {};
    const t = [];
    if (fac.attacker_supply_zone) t.push("атакующий в зоне снабжения (+5%)");
    if (fac.defender_home_zone) t.push("защитник у дома (+8%)");
    const terr = t.length ? t.join("; ") : "—";
    const ar = Array.isArray(fac.attacker_research) ? fac.attacker_research : [];
    const dr = Array.isArray(fac.defender_research) ? fac.defender_research : [];
    const resA = ar.length ? ar.map((x) => `${x.name} (${x.summary})`).join("; ") : "—";
    const resD = dr.length ? dr.map((x) => `${x.name} (${x.summary})`).join("; ") : "—";
    const eb = `база очков: вы ${fac.attacker_base ?? "—"}, враг ${fac.defender_base ?? "—"}; после территории ≈ ${fac.attacker_effective_before_roll ?? fac.attacker_effective ?? "—"} vs ${fac.defender_effective_before_roll ?? fac.defender_effective ?? "—"}`;
    const disc = pr.disclaimer ? `\n${pr.disclaimer}` : "";
    return `Пересчёт по текущей позиции:\n${eb}\nВаш состав: ${mine}\nВраг: ${theirs}\nТерритория: ${terr}\nВаши исследования (бой): ${resA}\nВраг: ${resD}\nПримерный шанс победы ≈ ${p}%${disc}`;
  };

  const tickCombatCountdown = () => {
    if (!cpCountdown || !combatPromptExpiresAtMs) return;
    const left = Math.max(0, Math.ceil((combatPromptExpiresAtMs - Date.now()) / 1000));
    cpCountdown.textContent = left > 0 ? `Осталось ${left} с` : "Время вышло, ждём ответ сервера…";
  };

  const openOrRefreshCombatArrivalPrompt = (state) => {
    const prompts = Array.isArray(state.pending_combat_prompts) ? state.pending_combat_prompts : [];
    const stillHere =
      combatPromptOpenForOrderId && prompts.some((p) => p && p.order_id === combatPromptOpenForOrderId);
    if (combatPromptOpenForOrderId && !stillHere) {
      closeCombatPromptModal();
    }
    if (prompts.length === 0) return;
    const prim = prompts[0];
    if (!prim || !prim.order_id) return;

    const wasId = combatPromptOpenForOrderId;
    combatPromptOpenForOrderId = prim.order_id;
    const isNewOrder = wasId !== prim.order_id;
    if (isNewOrder) {
      const tx = prim.target && Number.isFinite(Number(prim.target.x)) ? Number(prim.target.x) : 0;
      const ty = prim.target && Number.isFinite(Number(prim.target.y)) ? Number(prim.target.y) : 0;
      const br = loadUiSettings().battleFocusRadius ?? 6;
      viewCenter = { x: tx, y: ty };
      viewRadius = br;
      void refreshWindow();
    }

    if (combatPromptOverlay) combatPromptOverlay.classList.remove("hidden");
    if (cpSummary) {
      const st = prim.staging || {};
      const zx = Number.isFinite(Number(prim.target.z)) ? Number(prim.target.z) : 0;
      cpSummary.textContent = `Цель: (${prim.target.x},${prim.target.y},${zx}). Ваш флот сейчас у (${st.x},${st.y},${st.z}).`;
    }
    const exp = prim.expires_at ? Date.parse(prim.expires_at) : NaN;
    combatPromptExpiresAtMs = Number.isFinite(exp) ? exp : Date.now() + 30000;
    if (cpPreview) cpPreview.textContent = formatCombatPreviewText(prim.preview || {});
    if (!combatPromptCountdownTimer) {
      tickCombatCountdown();
      combatPromptCountdownTimer = setInterval(tickCombatCountdown, 1000);
    } else {
      tickCombatCountdown();
    }
  };

  const postCombatPromptResolve = async (attack) => {
    if (!combatPromptOpenForOrderId) return;
    const oid = combatPromptOpenForOrderId;
    try {
      const r = await fetch("/api/fleets/combat_prompt_resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order_id: oid, attack }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setStatus(`Бой: ${body.error || "ошибка"}`, "err");
        closeCombatPromptModal();
        await refreshWindow();
        return;
      }
      setStatus(attack ? "Решение применено" : "Атака отменена, флот на позиции", "ok");
      closeCombatPromptModal();
      await refreshWindow();
    } catch (_e) {
      setStatus("Сеть: combat_prompt_resolve", "err");
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
    if (playerId) {
      const enemyHere = objs.some(
        (o) => o && o.type === "fleet" && o.owner && String(o.owner) !== String(playerId)
      );
      if (enemyHere) {
        warn = warn ? `${warn} В клетке чужой флот — при прилёте будет бой.` : "В клетке чужой флот — при прилёте будет бой.";
      }
    }
    return { label, warn };
  };

  const openFleetMoveConfirm = async ({ fleet_id, qty, from, to, destCell, deferOkMs }) => {
    if (!overlayEl) return;
    const distance = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
    const travelTicks = Math.max(1, distance);
    const currentTick = Number.isInteger(worldState.current_sol)
      ? worldState.current_sol
      : Number.isInteger(worldState.current_tick)
        ? worldState.current_tick
        : 0;
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
    if (cfEtaEl) cfEtaEl.textContent = `${travelTicks} ${solWord(travelTicks)}`;
    if (cfArriveEl) cfArriveEl.textContent = `сол ${arriveTick}`;
    if (cfFuelEl) cfFuelEl.textContent = String(fuelCost);
    if (cfDestEl) cfDestEl.textContent = dest.label;
    if (cfWarnEl) cfWarnEl.textContent = dest.warn || "";
    if (cfCombatEl) {
      cfCombatEl.style.display = "none";
      cfCombatEl.textContent = "";
    }
    try {
      const r = await fetch("/api/fleets/combat_preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fleet_id,
          target_x: to.x,
          target_y: to.y,
          target_z: to.z,
        }),
      });
      const body = await r.json();
      if (r.ok && body.ok && body.combat && cfCombatEl) {
        const mine = formatComposition(body.attacker_composition) || "—";
        const theirs = formatComposition(body.defender_composition) || "—";
        const p =
          body.p_win_attacker != null ? Math.round(Number(body.p_win_attacker) * 100) : "—";
        const fac = body.factors || {};
        const terrBits = [];
        if (fac.attacker_supply_zone) terrBits.push("ваш флот в зоне снабжения (+5% к силе)");
        if (fac.defender_home_zone) terrBits.push("противник в домашней зоне (+8% к защите)");
        const terr = terrBits.length ? terrBits.join("; ") : "без бонусов по территории";
        const disc = body.disclaimer ? `\n${body.disclaimer}` : "";
        cfCombatEl.textContent =
          `При прилёте возможно нападение на вражеский флот.\n` +
          `Ваш состав: ${mine}\n` +
          `Состав врага: ${theirs}\n` +
          `Территория: ${terr}\n` +
          `Примерный шанс победы вашего флота: ≈${p}%${disc}`;
        cfCombatEl.style.display = "block";
        if (!loadUiSettings().forceAttackGuaranteed) {
          cfCombatEl.textContent +=
            "\n\nПосле прилёта откроется второе окно: подтвердите бой или откажитесь (30 с).";
        }
      }
    } catch (_e) {
      if (cfCombatEl) {
        cfCombatEl.style.display = "none";
        cfCombatEl.textContent = "";
      }
    }

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
    if (cfCombatEl) {
      cfCombatEl.style.display = "none";
      cfCombatEl.textContent = "";
    }
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
  if (buildBtn) {
    buildBtn.addEventListener("click", async () => {
      if (!selectedCell) return;
      if (buildBtn.disabled) {
        setStatus('Создайте флот с "инженерами" и приведите его в эту клетку (или стройте из своей клетки с форпостом).', "err");
        return;
      }
      await openPlanetModal(selectedCell);
    });
  }

  if (discoveryResolveBtn) {
    discoveryResolveBtn.addEventListener("click", async () => {
      if (!selectedCell) return;
      setStatus("Исследование…");
      try {
        const r = await fetch("/api/discovery/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            x: selectedCell.x,
            y: selectedCell.y,
            z: selectedCell.z ?? 0,
          }),
        });
        const body = await r.json();
        if (!r.ok || !body.ok) {
          if (body.error === "sector_not_visible") setStatus("Клетка не в зоне обзора флотов/колоний", "err");
          else if (body.error === "nothing_to_discover") setStatus("Здесь нечего исследовать", "err");
          else setStatus(`Ошибка: ${body.error || "discovery_failed"}`, "err");
          return;
        }
        if (body.already_done) setStatus("Объект уже исследован", "ok");
        else setStatus("Исследование завершено — см. журнал событий", "ok");
        await refreshWindow();
        refreshSelectedCellFromWindow();
        updateSelectedPanel();
        void loadWorldState();
      } catch (_e) {
        setStatus("Ошибка: network_error", "err");
      }
    });
  }

  if (fleetSelectEl) {
    fleetSelectEl.addEventListener("change", () => {
      activeFleetId = fleetSelectEl.value || null;
      void loadWorldState();
      updateSelectedPanel();
    });
  }
  if (fleetLocateBtn) {
    fleetLocateBtn.addEventListener("click", () => {
      if (!activeFleetId) {
        setStatus("Сначала выберите флот в списке", "err");
        return;
      }
      void focusFleetOnMap(activeFleetId);
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
  const radius4Btn = document.getElementById("radius-4");
  const radius10Btn = document.getElementById("radius-10");
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

  const syncMapRadiusButtons = () => {
    const b4 = document.getElementById("radius-4");
    const b10 = document.getElementById("radius-10");
    if (b4) b4.classList.toggle("is-active", viewRadius === 4);
    if (b10) b10.classList.toggle("is-active", viewRadius === 10);
  };

  const setRadius = async (r) => {
    const nr = Number(r);
    viewRadius = Number.isInteger(nr) ? Math.max(1, Math.min(nr, 10)) : 4;
    try {
      localStorage.setItem(MAP_VIEW_RADIUS_KEY, String(viewRadius));
    } catch (_e) {
      /* ignore */
    }
    syncMapRadiusButtons();
    await refreshWindow();
    setStatus(`Размер карты: ${viewRadius === 10 ? "21×21" : "9×9"}`, "ok");
  };
  if (radius4Btn) radius4Btn.addEventListener("click", async () => setRadius(4));
  if (radius10Btn) radius10Btn.addEventListener("click", async () => setRadius(10));

  if (planetModalClose) planetModalClose.addEventListener("click", closePlanetModal);
  if (planetModalOverlay) {
    planetModalOverlay.addEventListener("click", (e) => {
      if (e.target === planetModalOverlay) closePlanetModal();
    });
  }

  if (fleetEditBtn) {
    fleetEditBtn.addEventListener("click", () => {
      void (async () => {
        await fetchBalanceCached();
        renderFleetCompositionModal();
        if (fleetModalOverlay) fleetModalOverlay.classList.remove("hidden");
      })();
    });
  }
  if (fleetModalClose) fleetModalClose.addEventListener("click", closeFleetModal);
  if (fleetModalOverlay) {
    fleetModalOverlay.addEventListener("click", (e) => {
      if (e.target === fleetModalOverlay) closeFleetModal();
    });
  }
  if (fleetSubClose) fleetSubClose.addEventListener("click", () => closeFleetSubModal());
  if (fleetSubOverlay) {
    fleetSubOverlay.addEventListener("click", (e) => {
      if (e.target === fleetSubOverlay) closeFleetSubModal();
    });
  }
  if (fleetCreateClose) fleetCreateClose.addEventListener("click", closeFleetCreateModal);
  if (fleetCreateOverlay) {
    fleetCreateOverlay.addEventListener("click", (e) => {
      if (e.target === fleetCreateOverlay) closeFleetCreateModal();
    });
  }

  if (techModalOpenBtn) techModalOpenBtn.addEventListener("click", () => void openTechModal());
  if (techModalCloseBtn) techModalCloseBtn.addEventListener("click", closeTechModal);
  if (techModalOverlay) {
    techModalOverlay.addEventListener("click", (e) => {
      if (e.target === techModalOverlay) closeTechModal();
    });
  }
  if (economyModalOpenBtn) economyModalOpenBtn.addEventListener("click", () => void openEconomyModal());
  if (economyModalCloseBtn) economyModalCloseBtn.addEventListener("click", closeEconomyModal);
  if (economyModalOverlay) {
    economyModalOverlay.addEventListener("click", (e) => {
      if (e.target === economyModalOverlay) closeEconomyModal();
    });
  }

  if (cpAttackBtn) cpAttackBtn.addEventListener("click", () => void postCombatPromptResolve(true));
  if (cpDeclineBtn) cpDeclineBtn.addEventListener("click", () => void postCombatPromptResolve(false));
  if (combatPromptOverlay) {
    combatPromptOverlay.addEventListener("click", (e) => {
      if (e.target === combatPromptOverlay) void postCombatPromptResolve(false);
    });
  }

  const openUiSettings = () => {
    if (!uiSettingsOverlay) return;
    const s = loadUiSettings();
    syncUiSettingsControls(s);
    uiSettingsOverlay.classList.remove("hidden");
  };
  const closeUiSettings = () => {
    if (!uiSettingsOverlay) return;
    uiSettingsOverlay.classList.add("hidden");
  };
  if (uiSettingsBtn) uiSettingsBtn.addEventListener("click", openUiSettings);
  if (uiSettingsClose) uiSettingsClose.addEventListener("click", closeUiSettings);
  if (uiSettingsOverlay) {
    uiSettingsOverlay.addEventListener("click", (e) => {
      if (e.target === uiSettingsOverlay) closeUiSettings();
    });
  }
  const onSettingsChanged = () => {
    const brRaw = uiBattleRadius ? Number(uiBattleRadius.value) : 6;
    const br = Math.min(10, Math.max(3, Math.round(Number.isFinite(brRaw) ? brRaw : 6)));
    const s = {
      fontSize: uiFontSize ? Number(uiFontSize.value) : 14,
      lineHeight: uiLineHeight ? Number(uiLineHeight.value) : 1.35,
      battleFocusRadius: br,
      forceAttackGuaranteed: Boolean(uiForceAttack && uiForceAttack.checked),
    };
    applyUiSettings(s);
    saveUiSettings(s);
    if (uiBattleRadiusLabel) uiBattleRadiusLabel.textContent = String(br);
  };
  if (uiFontSize) uiFontSize.addEventListener("input", onSettingsChanged);
  if (uiLineHeight) uiLineHeight.addEventListener("input", onSettingsChanged);
  if (uiBattleRadius) uiBattleRadius.addEventListener("input", onSettingsChanged);
  if (uiForceAttack) uiForceAttack.addEventListener("change", onSettingsChanged);
  if (uiSettingsReset) {
    uiSettingsReset.addEventListener("click", () => {
      const s = { fontSize: 14, lineHeight: 1.35, battleFocusRadius: 6, forceAttackGuaranteed: false };
      saveUiSettings(s);
      syncUiSettingsControls(s);
    });
  }

  void (async () => {
    try {
      await refreshWindow();
    } catch (_e) {
      renderMap();
      renderZoneOverlay();
      void loadWorldState();
    }
    syncMapRadiusButtons();
    updateSelectedPanel();
  })();

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
    // Если открыта статистика экономики — обновляем её вместе с тиками.
    if (economyModalOverlay && !economyModalOverlay.classList.contains("hidden")) {
      void loadEconomyModalContent();
    }
  }, 3000);
})();
