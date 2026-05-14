(function () {
  const dataEl = document.getElementById("initial-data");
  if (!dataEl) return;

  const initial = JSON.parse(dataEl.textContent || "{}");
  let currentWindow = initial.window;
  let currentZ = Number.isInteger(initial.z) ? initial.z : 0;
  const home = initial.home || { x: 0, y: 0 };
  const playerId = initial.player || null;
  let playerIsGameAdmin = Boolean(initial.is_game_admin);
  let playerIsGameModerator = Boolean(initial.is_game_moderator);
  /** Резерв если баланс ещё не подгрузился. Реальный список типов берётся из `aliases.unit_aliases` в `/api/balance`. */
  const DEFAULT_FLEET_QTY_KEYS = ["scout", "fighter", "engineer"];
  const DEFAULT_FLEET_UNIT_LABELS = {
    scout: "Разведчик",
    fighter: "Истребитель",
    engineer: "Инженер",
    corvette: "Корвет",
    supplier: "Снабженец",
    freighter: "Корабль поддержки",
    frigate: "Фрегат II",
    colonizer: "Колонизационный модуль",
    colony_support: "Колониальный логист",
    scout_medium: "Разведчик ср.",
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
  const escHtml = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  const escAttr = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/\n/g, "&#10;");
  const formatTerrainRu = (t) => (t && TERRAIN_RU[t]) || (t ? String(t) : "—");
  /** Одна строка для HUD/модалок: без отдельного «маркера», только человекочитаемое содержимое клетки. */
  const formatCellContainsRu = (terrain, glyph) => {
    if (terrain === "fog" && glyph === "?") return "неизвестно";
    const label = formatTerrainRu(terrain);
    if (!label || label === "—") return "—";
    return label.charAt(0).toLowerCase() + label.slice(1);
  };
  const ruOrderType = (t) => {
    if (!t) return "приказ";
    if (t === "move") return "перелёт";
    if (t === "emergency_return") return "аварийный возврат";
    return String(t);
  };
  const formatInfluenceHud = (inf, richLinks = false) => {
    if (!inf || typeof inf !== "object") return "—";
    const controlOwnerName =
      inf.control?.owner_name != null
        ? String(inf.control.owner_name)
        : inf.home_control_owner_name != null
          ? String(inf.home_control_owner_name)
          : null;
    const controlOwnerId =
      inf.control?.owner != null
        ? String(inf.control.owner).trim()
        : inf.home_control_owner != null
          ? String(inf.home_control_owner).trim()
          : "";
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
    const thr = captureThreshold.toFixed(1);
    const tail = contested ? " • спор зон" : "";
    if (!controlOwnerId) {
      return `накопление контроля: нейтрально • ваш вклад ${yourValue} • лидер ${topValue} • порог захвата ${thr}${tail}`;
    }
    let leadLabel = ownerShort;
    if (richLinks && controlOwnerName && /^[\da-f-]{36}$/i.test(controlOwnerId)) {
      leadLabel = `<a href="/operator/${escAttr(controlOwnerId)}" class="chat-player-link sector-owner-link">${escHtml(controlOwnerName)}</a>`;
    } else {
      leadLabel = escHtml(ownerShort);
    }
    return `накопление контроля: ${leadLabel} • ваш вклад ${yourValue} • лидер ${topValue} • порог захвата ${thr}${tail}`;
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
  /** Число + «сол / сола / солов» для длительностей стройки (игровой год = один сол в UI). */
  const ruSolsCountLabel = (nRaw) => {
    const n = Math.trunc(Number(nRaw) || 0);
    if (!Number.isFinite(n)) return "0 солов";
    return `${n} ${solWord(n)}`;
  };
  /** Полуразмер окна карты в шагах гекса от центра (радиус диска); clamp 6…12. */
  const MAP_WINDOW_RADIUS_MIN = 6;
  const MAP_WINDOW_RADIUS_MAX = 12;
  const clampMapWindowRadius = (r) => {
    const x = Math.round(Number(r));
    if (!Number.isFinite(x)) return MAP_WINDOW_RADIUS_MIN;
    return Math.min(MAP_WINDOW_RADIUS_MAX, Math.max(MAP_WINDOW_RADIUS_MIN, x));
  };
  const mapWindowSideCells = (rad) => clampMapWindowRadius(rad) * 2 + 1;

  const SQRT3 = Math.sqrt(3);
  /** Вертикальное сжатие раскладки pointy-top на экране (ниже «профиль», шире поле по ширине слота). */
  const MAP_HEX_VERTICAL_COMPRESS = 0.75;

  const jsHexDistance = (q1, r1, q2, r2) => {
    const dq = q1 - q2;
    const dr = r1 - r2;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
  };

  /**
   * Стрелка панорамы: угол от центра окна к клетке в той же линейной системе, что и раскладка гекса
   * (иначе на одном ребре все клетки получали один и тот же осевой символ — см. «все ↗»).
   * Делим плоскость на 8 секторов ≈45° с центром «вправо» → … → «вверх».
   */
  const PAN_ARROW_GLYPHS_8 = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"];
  const hexPanArrow = (q, r, cq, cr) => {
    if (q === cq && r === cr) return "";
    const vcy = MAP_HEX_VERTICAL_COMPRESS;
    const vx = SQRT3 * ((q - cq) + (r - cr) / 2);
    const vy = (3 / 2) * (r - cr) * vcy;
    if (vx === 0 && vy === 0) return "";
    const ang = Math.atan2(vy, vx);
    const s = ((ang % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    const idx = Math.floor((s + Math.PI / 8) / (Math.PI / 4)) % 8;
    return PAN_ARROW_GLYPHS_8[idx];
  };

  const mapWindowGridSpan = (win) => {
    if (!win || !Array.isArray(win.cells) || !win.cells.length) {
      const r = clampMapWindowRadius(win && win.radius);
      return { w: r * 2 + 1, h: r * 2 + 1 };
    }
    let maxRow = 0;
    for (const row of win.cells) {
      const rw = Array.isArray(row.row) ? row.row.length : 0;
      if (rw > maxRow) maxRow = rw;
    }
    return { w: Math.max(1, maxRow), h: Math.max(1, win.cells.length) };
  };

  let viewCenter = (currentWindow && currentWindow.center) ? { ...currentWindow.center } : { ...home };
  const MAP_VIEW_RADIUS_KEY = "gs.map.viewRadius";
  const readSavedMapRadius = () => {
    try {
      const n = parseInt(String(localStorage.getItem(MAP_VIEW_RADIUS_KEY) || ""), 10);
      if (Number.isFinite(n) && n >= MAP_WINDOW_RADIUS_MIN && n <= MAP_WINDOW_RADIUS_MAX) return n;
      if (n === 4) return MAP_WINDOW_RADIUS_MIN;
      if (n === 10) return 8;
    } catch (_e) {
      /* ignore */
    }
    return null;
  };
  let viewRadius = clampMapWindowRadius(
    readSavedMapRadius() ??
      (currentWindow && Number.isInteger(currentWindow.radius) ? currentWindow.radius : MAP_WINDOW_RADIUS_MIN)
  );
  let lastTarget = null;
  /** Двухшаговый клик по краю окна: 1-й — выбор клетки с объектом, 2-й — сдвиг карты. */
  let lastEdgePanCellKey = null;
  let selectedCell = null;
  let worldState = { current_tick: 0, current_sol: 0, fleet: null, events: [], player_id: playerId };
  // Подсказка по линии снабжения для выбранной клетки (для подсветки "обрыва" на карте).
  let supplyHint = null; // { for:{x,y,z}, inSupply:boolean, routeClear:boolean, blockedAt:{x,y} | null }
  /** Счётчик запросов `/api/world/sector` для панели discovery — отбрасываем устаревшие ответы (анти-мерцание). */
  let discoverySectorFetchGen = 0;
  /**
   * Очередь `GET /api/world/window` — строго по одному за раз.
   * Параллельные вызовы + отбрасывание «устаревших» ответов могли выкинуть единственный успешный JSON
   * (например новый запрос упал с 401, старый успешный не применялся) → пустая карта и HUD без ошибок в консоли.
   */
  let mapWindowRefreshQueue = Promise.resolve();
  /** Последняя клетка руин/аномалии в HUD — не сбрасываем кнопку при каждом poll, если координаты те же. */
  let discoveryHudCellKey = null;
  const actionFeedbackTimers = new WeakMap();
  /** События с ui_channel=toast уже показаны тостом (по id). */
  const toastEventIdsSeen = new Set();
  const TOAST_EVENT_IDS_MAX = 120;
  /** Дедуп повторяющихся тостов по ключу из payload (например fleet_maintenance:fleet_id). */
  const toastDedupeKeyLastMs = new Map();

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
  const selBuiltWrapEl = document.getElementById("sel-built-wrap");
  const selBuiltEl = document.getElementById("sel-built");
  const selObjectsEl = document.getElementById("sel-objects");
  const selInfluenceEl = document.getElementById("sel-influence");
  const selSupplyEl = document.getElementById("sel-supply");
  const selDistanceEl = document.getElementById("sel-distance");
  const selTravelEl = document.getElementById("sel-travel");
  const selArriveEl = document.getElementById("sel-arrive");
  const flyBtn = document.getElementById("fly-btn");
  const buildBtn = document.getElementById("build-btn");
  const buildBtnHelp = document.getElementById("build-btn-help");
  const discoveryResolveBtn = document.getElementById("discovery-resolve-btn");
  const discoveryResolveLabel = document.getElementById("discovery-resolve-label");
  const discoveryResolveHelp = document.getElementById("discovery-resolve-help");
  const clearSelBtn = document.getElementById("clear-sel-btn");
  const hudActionFeedbackEl = document.getElementById("hud-action-feedback");
  const systemToastsEl = document.getElementById("system-toasts");
  const fleetModalFeedbackEl = document.getElementById("fleet-modal-feedback");
  const fleetCreateFeedbackEl = document.getElementById("fleet-create-feedback");
  const onboardingGoalsBodyEl = document.getElementById("onboarding-goals-body");
  const onboardingGoalsSectionEl = document.getElementById("onboarding-goals-section");
  const eventsEl = document.getElementById("events");
  /** `data-event-id` боя, у которого игрок раскрыл «Подробный расчёт» — восстанавливаем после каждого перерендера лога. */
  const openFleetCombatDetailIds = new Set();
  if (eventsEl) {
    eventsEl.addEventListener(
      "toggle",
      (ev) => {
        const t = ev.target;
        if (!(t instanceof HTMLDetailsElement) || !t.classList.contains("event-combat-details")) return;
        const id = t.getAttribute("data-event-id");
        if (id == null || id === "") return;
        if (t.open) openFleetCombatDetailIds.add(id);
        else openFleetCombatDetailIds.delete(id);
      },
      true,
    );
  }
  const commsPanel = document.getElementById("comms-panel");
  const commsPanelTitleEl = document.getElementById("comms-panel-title");
  const commsCollapseBtn = document.getElementById("comms-collapse-btn");
  const commsOverlay = document.getElementById("comms-overlay");
  const pageGridMmo = document.querySelector(".page-grid-mmo");
  const mapSectorCard = document.querySelector(".map-sector-card");
  const globalChatFeed = document.getElementById("global-chat-feed");
  const globalChatForm = document.getElementById("global-chat-form");
  const globalChatInput = document.getElementById("global-chat-input");
  const privateThreadsEl = document.getElementById("private-threads");
  const privateChatWrap = document.getElementById("private-chat-wrap");
  const privateChatFeed = document.getElementById("private-chat-feed");
  const privateChatForm = document.getElementById("private-chat-form");
  const privateChatPeer = document.getElementById("private-chat-peer");
  const privateChatInput = document.getElementById("private-chat-input");
  const privatePeerInput = document.getElementById("private-peer-input");
  const privatePeerOpenBtn = document.getElementById("private-peer-open");
  const privateBlockPeerBtn = document.getElementById("private-block-peer-btn");
  const privateBackThreadsBtn = document.getElementById("private-back-threads-btn");
  const privateTabBadge = document.getElementById("private-tab-badge");
  const privateSendReadReceiptCb = document.getElementById("private-send-read-receipt");
  const privateDeleteThreadBtn = document.getElementById("private-delete-thread-btn");
  const privateIntroOverlay = document.getElementById("private-intro-overlay");
  const privateIntroPeerNameEl = document.getElementById("private-intro-peer-name");
  const privateIntroYesBtn = document.getElementById("private-intro-yes");
  const privateIntroNoBtn = document.getElementById("private-intro-no");
  const chatSettingsOpenBtn = document.getElementById("chat-settings-open");
  const chatSettingsOverlay = document.getElementById("chat-settings-overlay");
  const chatSettingsClose = document.getElementById("chat-settings-close");
  const chatSettingsSave = document.getElementById("chat-settings-save");
  const chatColorSystem = document.getElementById("chat-color-system");
  const chatColorGlobal = document.getElementById("chat-color-global");
  const chatColorAlliance = document.getElementById("chat-color-alliance");
  const chatColorPrivate = document.getElementById("chat-color-private");
  const chatDisablePrivate = document.getElementById("chat-disable-private");

  const ENTRY_TUTORIAL_SUPPRESS_KEY = "gs.entryTutorial.suppress.v1";
  const entryTutorialOverlay = document.getElementById("entry-tutorial-overlay");
  const entryTutorialOk = document.getElementById("entry-tutorial-ok");
  const entryTutorialDismissNext = document.getElementById("entry-tutorial-dismiss-next");
  const entryTutorialRemindBtn = document.getElementById("entry-tutorial-remind");

  /** Вкладки подсказки (левое меню модалки). */
  const ENTRY_TUTORIAL_TAB_IDS = ["economy", "empire", "fleet", "visual", "combat", "symbols", "comms"];
  const setEntryTutorialTab = (tabId) => {
    if (!entryTutorialOverlay) return;
    const tid = ENTRY_TUTORIAL_TAB_IDS.includes(tabId) ? tabId : "economy";
    entryTutorialOverlay.querySelectorAll("[data-tutorial-tab]").forEach((btn) => {
      const bid = btn.getAttribute("data-tutorial-tab");
      const on = bid === tid;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      try {
        btn.tabIndex = on ? 0 : -1;
      } catch (_x) {
        /* ignore */
      }
    });
    entryTutorialOverlay.querySelectorAll("[data-tutorial-panel]").forEach((panel) => {
      const pid = panel.getAttribute("data-tutorial-panel");
      const on = pid === tid;
      panel.classList.toggle("hidden", !on);
      panel.classList.toggle("is-active", on);
    });
  };

  const ENTRY_TUTORIAL_WIKI_FULL_KEY = "gs.entryTutorial.wikiFull.v1";
  const entryTutorialCard = entryTutorialOverlay ? entryTutorialOverlay.querySelector(".entry-tutorial-card") : null;
  const entryTutorialWikiFull = document.getElementById("entry-tutorial-wiki-full");
  const entryTutorialWikiSearch = document.getElementById("entry-tutorial-wiki-search");
  const entryTutorialWikiSearchStatus = document.getElementById("entry-tutorial-wiki-search-status");

  const normalizeWikiSearchQuery = (raw) =>
    String(raw || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, " ");

  const readWikiFullPref = () => {
    try {
      return localStorage.getItem(ENTRY_TUTORIAL_WIKI_FULL_KEY) === "1";
    } catch (_e) {
      return false;
    }
  };

  const applyWikiFullFromCheckbox = () => {
    const on = !!(entryTutorialWikiFull && entryTutorialWikiFull.checked);
    if (entryTutorialCard) entryTutorialCard.classList.toggle("wiki-mode-full", on);
    try {
      localStorage.setItem(ENTRY_TUTORIAL_WIKI_FULL_KEY, on ? "1" : "0");
    } catch (_e) {
      /* ignore */
    }
  };

  const runEntryTutorialWikiSearch = () => {
    if (!entryTutorialOverlay) return;
    const q = normalizeWikiSearchQuery(entryTutorialWikiSearch && entryTutorialWikiSearch.value);
    const items = entryTutorialOverlay.querySelectorAll(".tutorial-wiki-item");
    let anyHit = false;
    items.forEach((li) => {
      const hay = `${li.getAttribute("data-wiki-search") || ""} ${li.textContent || ""}`
        .toLowerCase()
        .replace(/\s+/g, " ");
      const hit = !q || hay.includes(q);
      li.classList.toggle("wiki-search-hidden", !hit);
      if (hit) anyHit = true;
    });
    entryTutorialOverlay.querySelectorAll("[data-tutorial-tab]").forEach((btn) => {
      const tid = btn.getAttribute("data-tutorial-tab");
      if (!tid) return;
      const panel = entryTutorialOverlay.querySelector(`[data-tutorial-panel="${tid}"]`);
      const has = panel && panel.querySelector(".tutorial-wiki-item:not(.wiki-search-hidden)");
      btn.classList.toggle("wiki-tab-nohit", !!(q && !has));
    });
    if (entryTutorialWikiSearchStatus) {
      entryTutorialWikiSearchStatus.textContent =
        q && !anyHit ? "Ничего не найдено — попробуйте другое слово или снимите фильтр." : "";
      entryTutorialWikiSearchStatus.classList.toggle("hidden", !(q && !anyHit));
    }
    if (q) {
      const activePanel = entryTutorialOverlay.querySelector("[data-tutorial-panel].is-active");
      const vis =
        activePanel && activePanel.querySelectorAll(".tutorial-wiki-item:not(.wiki-search-hidden)").length;
      if (activePanel && !vis) {
        for (let i = 0; i < ENTRY_TUTORIAL_TAB_IDS.length; i += 1) {
          const tid = ENTRY_TUTORIAL_TAB_IDS[i];
          const cand = entryTutorialOverlay.querySelector(`[data-tutorial-panel="${tid}"]`);
          if (cand && cand.querySelector(".tutorial-wiki-item:not(.wiki-search-hidden)")) {
            setEntryTutorialTab(tid);
            break;
          }
        }
      }
    }
  };

  const focusWikiAnchor = (anchorId) => {
    if (!entryTutorialOverlay || !anchorId) return;
    const raw = String(anchorId || "").trim();
    if (!raw) return;
    if (entryTutorialWikiSearch) entryTutorialWikiSearch.value = "";
    runEntryTutorialWikiSearch();
    const target = document.getElementById(raw);
    if (!target) return;
    const panel = target.closest("[data-tutorial-panel]");
    const tabId = panel && panel.getAttribute("data-tutorial-panel");
    if (tabId) setEntryTutorialTab(tabId);
    entryTutorialOverlay.querySelectorAll(".tutorial-wiki-item.wiki-link-flash").forEach((el) => {
      el.classList.remove("wiki-link-flash");
    });
    requestAnimationFrame(() => {
      try {
        target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } catch (_e) {
        try {
          target.scrollIntoView();
        } catch (_e2) {
          /* ignore */
        }
      }
      target.classList.add("wiki-link-flash");
      window.setTimeout(() => {
        try {
          target.classList.remove("wiki-link-flash");
        } catch (_e3) {
          /* ignore */
        }
      }, 1400);
    });
  };

  if (entryTutorialOverlay) {
    entryTutorialOverlay.querySelectorAll("[data-tutorial-tab]").forEach((btn) => {
      btn.addEventListener("click", () => setEntryTutorialTab(btn.getAttribute("data-tutorial-tab") || "economy"));
    });
    setEntryTutorialTab("economy");
    if (entryTutorialWikiFull) {
      entryTutorialWikiFull.checked = readWikiFullPref();
      entryTutorialWikiFull.addEventListener("change", () => {
        applyWikiFullFromCheckbox();
        runEntryTutorialWikiSearch();
      });
    }
    applyWikiFullFromCheckbox();
    if (entryTutorialWikiSearch) {
      entryTutorialWikiSearch.addEventListener("input", () => runEntryTutorialWikiSearch());
      entryTutorialWikiSearch.addEventListener("search", () => runEntryTutorialWikiSearch());
    }
    runEntryTutorialWikiSearch();
  }

  const isEntryTutorialSuppressed = () => {
    try {
      return localStorage.getItem(ENTRY_TUTORIAL_SUPPRESS_KEY) === "1";
    } catch (_e) {
      return false;
    }
  };

  const openEntryTutorial = (wikiAnchorId = null) => {
    if (!entryTutorialOverlay) return;
    if (entryTutorialDismissNext) entryTutorialDismissNext.checked = false;
    if (wikiAnchorId) {
      if (entryTutorialWikiSearch) entryTutorialWikiSearch.value = "";
      const tEl = document.getElementById(String(wikiAnchorId).trim());
      const pEl = tEl && tEl.closest("[data-tutorial-panel]");
      setEntryTutorialTab((pEl && pEl.getAttribute("data-tutorial-panel")) || "economy");
      runEntryTutorialWikiSearch();
    } else {
      if (entryTutorialWikiSearch) entryTutorialWikiSearch.value = "";
      setEntryTutorialTab("economy");
      runEntryTutorialWikiSearch();
    }
    entryTutorialOverlay.classList.remove("hidden");
    entryTutorialOverlay.removeAttribute("aria-hidden");
    document.body.classList.add("entry-tutorial-open");
    requestAnimationFrame(() => {
      if (wikiAnchorId) {
        requestAnimationFrame(() => focusWikiAnchor(String(wikiAnchorId).trim()));
        return;
      }
      try {
        if (entryTutorialOk) entryTutorialOk.focus({ preventScroll: true });
      } catch (_e) {
        if (entryTutorialOk) entryTutorialOk.focus();
      }
    });
  };

  const closeEntryTutorialAfterOk = () => {
    if (entryTutorialDismissNext && entryTutorialDismissNext.checked) {
      try {
        localStorage.setItem(ENTRY_TUTORIAL_SUPPRESS_KEY, "1");
      } catch (_e) {
        /* ignore */
      }
    }
    if (entryTutorialOverlay) {
      entryTutorialOverlay.classList.add("hidden");
      entryTutorialOverlay.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("entry-tutorial-open");
  };

  const maybeAutoShowEntryTutorial = () => {
    if (!entryTutorialOverlay || isEntryTutorialSuppressed()) return;
    openEntryTutorial();
  };

  if (entryTutorialOk) entryTutorialOk.addEventListener("click", () => closeEntryTutorialAfterOk());
  if (entryTutorialOverlay) {
    entryTutorialOverlay.addEventListener("click", (ev) => {
      if (ev.target === entryTutorialOverlay) ev.stopPropagation();
      const a = ev.target && ev.target.closest && ev.target.closest("a.wiki-internal-link");
      if (!a || !entryTutorialOverlay.contains(a)) return;
      const href = a.getAttribute("href") || "";
      if (!href.startsWith("#")) return;
      ev.preventDefault();
      focusWikiAnchor(href.slice(1));
    });
  }
  if (entryTutorialRemindBtn) entryTutorialRemindBtn.addEventListener("click", () => openEntryTutorial());

  const COMMS_COLLAPSED_KEY = "gs.comms.collapsed.v1";
  const SYSTEM_LOG_FILTER_KEY = "gs.systemLog.filter.v1";
  const CHAT_PREFS_KEY = "gs.chat.prefs.v1";
  const commsWideMq = window.matchMedia("(min-width: 1200px)");
  const readCommsCollapsedPref = () => {
    try {
      const v = localStorage.getItem(COMMS_COLLAPSED_KEY);
      if (v === "true" || v === "1") return true;
      if (v === "false" || v === "0") return false;
    } catch (_e) {
      /* ignore */
    }
    return null;
  };
  let commsCollapsedExplicit = readCommsCollapsedPref();
  const isCommsCollapsed = () =>
    commsCollapsedExplicit === null ? !commsWideMq.matches : commsCollapsedExplicit;

  const readSystemLogFilter = () => {
    try {
      const v = (localStorage.getItem(SYSTEM_LOG_FILTER_KEY) || "all").trim();
      if (
        ["all", "combat", "economy", "supply", "research", "diplomacy"].includes(v)
      )
        return v;
    } catch (_e) {
      /* ignore */
    }
    return "all";
  };
  let systemLogFilterCategory = readSystemLogFilter();

  /** Маппинг типов событий сервера → категории чипов «Система». Неизвестные → misc (только при «Все»). */
  const EVENT_TYPE_TO_CATEGORY = {
    fleet_combat: "combat",
    combat_prompt_expired: "combat",
    combat_prompt_declined: "combat",
    combat_prompt_arrival: "combat",
    outpost_fire: "combat",
    discovery_bandit_ambush: "combat",
    supplier_hired: "supply",
    supply_radius_changed: "supply",
    fleet_maintenance_failed: "supply",
    fleet_emergency_return: "supply",
    building_placed: "economy",
    building_dismantled: "economy",
    building_upgraded: "economy",
    not_enough_resources: "economy",
    not_enough_fuel: "economy",
    fleet_merged: "economy",
    fleet_split: "economy",
    fleet_disbanded: "economy",
    fleet_composition_changed: "economy",
    fleet_renamed: "economy",
    fleet_created: "economy",
    fleet_order_created: "economy",
    fleet_order_failed: "economy",
    fleet_order_cancelled: "economy",
    fleet_arrived: "economy",
    order_done: "economy",
    fuel_spent: "economy",
    outpost_offline: "supply",
    outpost_online: "supply",
    research_points_granted: "research",
    research_lab_underfunded: "research",
    research_lab_strain_event: "research",
    tech_done: "research",
    tech_start_research_boost: "research",
    tech_start_blueprint_cache: "research",
    discovery_research_boost: "research",
    discovery_blueprint_cache: "research",
    npc_transit_completed: "economy",
    emergency_orbit_staging: "economy",
    field_building_capture_tick: "combat",
    building_captured: "combat",
    building_lost_capture: "combat",
    fleet_bombards_outpost: "combat",
    outpost_under_bombardment: "combat",
    outpost_destroyed: "combat",
    bandit_strike_spawned: "combat",
    bandit_strike_chasing: "combat",
    bandit_patrol_spawned: "combat",
    bandit_mine_placed: "combat",
    bandit_outpost_placed: "combat",
    intel_scan_success: "diplomacy",
    intel_blocked: "diplomacy",
    intel_scanned: "diplomacy",
  };
  const getEventCategory = (type) => {
    const t = type ? String(type) : "";
    return EVENT_TYPE_TO_CATEGORY[t] || "misc";
  };

  const eventIsToastChannel = (e) => {
    const pl = e && e.payload && typeof e.payload === "object" ? e.payload : null;
    return Boolean(pl && String(pl.ui_channel || "") === "toast");
  };

  const filterEventsForSystemLog = (events) => {
    const list = (Array.isArray(events) ? events : []).filter((ev) => !eventIsToastChannel(ev));
    if (systemLogFilterCategory === "all") return list;
    if (systemLogFilterCategory === "diplomacy")
      return list.filter((e) => getEventCategory(e.type) === "diplomacy");
    return list.filter((e) => getEventCategory(e.type) === systemLogFilterCategory);
  };

  /** Трёхколоночный MMO: высота коммов и HUD = высота центральной колонки с картой (`.map-sector-card`). */
  const syncMmoSidePanelHeights = () => {
    if (!pageGridMmo) return;
    if (document.querySelector(".me-play-layout") && commsWideMq.matches) {
      pageGridMmo.style.removeProperty("--mmo-sync-h");
      return;
    }
    if (!mapSectorCard || !commsWideMq.matches) {
      pageGridMmo.style.removeProperty("--mmo-sync-h");
      return;
    }
    const h = mapSectorCard.getBoundingClientRect().height;
    if (Number.isFinite(h) && h > 2) pageGridMmo.style.setProperty("--mmo-sync-h", `${Math.round(h)}px`);
  };

  const applyCommsLayout = () => {
    const collapsed = isCommsCollapsed();
    const wide = commsWideMq.matches;
    if (commsPanel) {
      commsPanel.classList.toggle("comms-panel--collapsed", collapsed);
      commsPanel.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    if (commsCollapseBtn) {
      commsCollapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      commsCollapseBtn.textContent = collapsed ? "›" : "‹";
    }
    if (pageGridMmo) pageGridMmo.classList.toggle("page-grid--comms-collapsed", collapsed && wide);
    if (commsOverlay) {
      const showOverlay = !wide && !collapsed;
      commsOverlay.classList.toggle("hidden", !showOverlay);
    }
    syncMmoSidePanelHeights();
  };

  const toggleCommsCollapsed = () => {
    const next = !isCommsCollapsed();
    commsCollapsedExplicit = next;
    try {
      localStorage.setItem(COMMS_COLLAPSED_KEY, next ? "true" : "false");
    } catch (_e) {
      /* ignore */
    }
    applyCommsLayout();
  };

  let activeCommsTab = "system";
  const syncCommsPanelTitle = () => {
    if (!commsPanelTitleEl) return;
    commsPanelTitleEl.textContent = activeCommsTab === "system" ? "События" : "Чат";
  };
  const setActiveCommsTab = (name) => {
    activeCommsTab = name;
    document.querySelectorAll(".comms-tab").forEach((btn) => {
      const t = btn.getAttribute("data-comms-tab");
      const on = t === name;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".comms-pane").forEach((pane) => {
      const id = pane.id || "";
      const map = {
        "comms-pane-system": "system",
        "comms-pane-global": "global",
        "comms-pane-alliance": "alliance",
        "comms-pane-private": "private",
      };
      const tab = map[id];
      pane.classList.toggle("hidden", tab !== name);
    });
    syncCommsPanelTitle();
  };

  const readChatPrefs = () => {
    try {
      const raw = localStorage.getItem(CHAT_PREFS_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (_e) {
      return {};
    }
  };
  const writeChatPrefs = (patch) => {
    try {
      const cur = readChatPrefs();
      localStorage.setItem(CHAT_PREFS_KEY, JSON.stringify({ ...cur, ...patch }));
    } catch (_e) {
      /* ignore */
    }
  };
  const applyChatPrefsToDom = () => {
    const p = readChatPrefs();
    const root = document.documentElement;
    const d = (k, fallback) => (p[k] && String(p[k]).trim() ? String(p[k]).trim() : fallback);
    root.style.setProperty("--chat-accent-system", d("colorSystem", "#61eaa3"));
    root.style.setProperty("--chat-accent-global", d("colorGlobal", "#7ec8e3"));
    root.style.setProperty("--chat-accent-alliance", d("colorAlliance", "#c9a227"));
    root.style.setProperty("--chat-accent-private", d("colorPrivate", "#d88fd8"));
    if (globalChatFeed) globalChatFeed.style.borderColor = "color-mix(in srgb, var(--chat-accent-global) 35%, var(--border))";
    if (privateChatFeed) privateChatFeed.style.borderColor = "color-mix(in srgb, var(--chat-accent-private) 35%, var(--border))";
    if (eventsEl) eventsEl.style.borderLeft = "3px solid var(--chat-accent-system)";
  };

  let lastGlobalChatId = 0;
  /** Синхронизация полного перезапроса истории при смене прав модерации. */
  let lastViewerChatModerate = null;
  let privatePeerActive = "";
  let lastPrivateChatId = 0;
  let pendingIntroPeerId = "";
  let privateReceiptsProgrammaticToggle = false;

  /** Согласовано с `MAX_CHAT_BODY_LEN` на сервере (`chat_service`). */
  const MAX_CHAT_BODY_CHARS = 1000;
  /** Только последние строки в DOM — без бесконечного роста ленты. */
  const MAX_CHAT_FEED_LINES = 100;

  /** Порядок сообщений как у ленты API: старые выше, новые ниже — держим низ, если игрок не листает историю вверх. */
  const CHAT_FEED_BOTTOM_SLACK_PX = 96;
  const chatFeedNearBottom = (feedEl) => {
    if (!feedEl) return true;
    return feedEl.scrollHeight - feedEl.scrollTop - feedEl.clientHeight <= CHAT_FEED_BOTTOM_SLACK_PX;
  };
  const scrollChatFeedToBottom = (feedEl, opts = {}) => {
    const force = Boolean(opts.force);
    if (!feedEl) return;
    requestAnimationFrame(() => {
      if (force) feedEl.scrollTop = feedEl.scrollHeight;
    });
  };

  const escChatTxt = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const trimChatFeedToMaxLines = (feedEl) => {
    if (!feedEl) return;
    while (feedEl.querySelectorAll(".chat-line").length > MAX_CHAT_FEED_LINES) {
      const first = feedEl.querySelector(".chat-line");
      if (first) first.remove();
      else break;
    }
  };

  /** Рендер строк чата через DOM (`textContent`) — без интерпретации HTML из сети. */
  const appendChatLines = (feedEl, messages, opts = {}) => {
    const reset = Boolean(opts.reset);
    const privateDm = Boolean(opts.privateDm);
    if (!feedEl || !Array.isArray(messages)) return;
    const stickBottom = reset || chatFeedNearBottom(feedEl);
    if (reset) feedEl.innerHTML = "";
    const readClockShort = (iso) => {
      if (!iso) return "";
      try {
        const d = new Date(String(iso));
        if (!Number.isFinite(d.getTime())) return "";
        return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
      } catch (_e) {
        return "";
      }
    };
    for (const m of messages) {
      const row = document.createElement("div");
      row.className = "chat-line";
      const mid = Number(m.id);
      row.dataset.msgId = Number.isFinite(mid) && mid > 0 ? String(Math.floor(mid)) : "0";
      const meta = document.createElement("span");
      meta.className = "chat-meta";
      const sid = String(m.sender_id || "").trim();
      const dn = String(m.display_name || "").trim();
      if (sid && /^[\da-f-]{36}$/i.test(sid)) {
        const a = document.createElement("a");
        a.href = `/operator/${sid}`;
        a.className = "chat-player-link";
        a.textContent = dn || sid || "—";
        meta.appendChild(a);
      } else {
        meta.textContent = dn || sid || "—";
      }
      row.appendChild(meta);
      row.appendChild(document.createTextNode(String(m.body ?? "")));
      if (privateDm && playerId && sid === String(playerId)) {
        const rr = m.read_receipt_at != null && String(m.read_receipt_at).trim() !== "";
        if (rr) {
          const rk = document.createElement("span");
          rk.className = "chat-private-read";
          rk.textContent = ` · прочитано ${readClockShort(m.read_receipt_at)}`;
          row.appendChild(rk);
        }
      }
      feedEl.appendChild(row);
    }
    trimChatFeedToMaxLines(feedEl);
    scrollChatFeedToBottom(feedEl, { force: stickBottom });
  };

  const appendGlobalChatLines = (feedEl, messages, { reset } = { reset: false }) => {
    if (!feedEl || !Array.isArray(messages)) return;
    const stickBottom = reset || chatFeedNearBottom(feedEl);
    if (reset) feedEl.innerHTML = "";
    const senderIsSelf = (sid) => playerId && String(sid || "") === String(playerId);
    for (const m of messages) {
      const row = document.createElement("div");
      row.className = "chat-line";
      const mid = Number(m.id);
      row.dataset.msgId = Number.isFinite(mid) && mid > 0 ? String(Math.floor(mid)) : "0";
      const main = document.createElement("span");
      main.className = "chat-line-main";
      const meta = document.createElement("span");
      meta.className = "chat-meta";
      const gsid = String(m.sender_id || "").trim();
      const gdn = String(m.display_name || "").trim();
      if (gsid && /^[\da-f-]{36}$/i.test(gsid)) {
        const ga = document.createElement("a");
        ga.href = `/operator/${gsid}`;
        ga.className = "chat-player-link";
        ga.textContent = gdn || gsid || "—";
        meta.appendChild(ga);
      } else {
        meta.textContent = gdn || gsid || "—";
      }
      const bodyEl = document.createElement("span");
      bodyEl.className = "chat-body";
      bodyEl.textContent = String(m.body ?? "");
      main.appendChild(meta);
      main.appendChild(bodyEl);
      row.appendChild(main);
      if (m.can_mod) {
        const act = document.createElement("span");
        act.className = "chat-mod-actions";
        const sid = String(m.sender_id || "");
        const midStr = row.dataset.msgId;
        if (!m.hidden) {
          const hBtn = document.createElement("button");
          hBtn.type = "button";
          hBtn.className = "chat-mod-btn";
          hBtn.textContent = "Скрыть";
          hBtn.dataset.chatMod = "hide";
          hBtn.dataset.mid = midStr;
          act.appendChild(hBtn);
        }
        const dBtn = document.createElement("button");
        dBtn.type = "button";
        dBtn.className = "chat-mod-btn chat-mod-btn-danger";
        dBtn.textContent = "Удалить";
        dBtn.dataset.chatMod = "delete";
        dBtn.dataset.mid = midStr;
        act.appendChild(dBtn);
        if (sid && !senderIsSelf(sid)) {
          const bChat = document.createElement("button");
          bChat.type = "button";
          bChat.className = "chat-mod-btn";
          bChat.textContent = "Мут чата";
          bChat.dataset.chatMod = "ban_chat";
          bChat.dataset.target = sid;
          act.appendChild(bChat);
        }
        if (playerIsGameAdmin && sid && !senderIsSelf(sid)) {
          const bAcct = document.createElement("button");
          bAcct.type = "button";
          bAcct.className = "chat-mod-btn chat-mod-btn-danger";
          bAcct.textContent = "Бан аккаунта";
          bAcct.dataset.chatMod = "ban_account";
          bAcct.dataset.target = sid;
          act.appendChild(bAcct);
        }
        row.appendChild(act);
      }
      feedEl.appendChild(row);
    }
    trimChatFeedToMaxLines(feedEl);
    scrollChatFeedToBottom(feedEl, { force: stickBottom });
  };

  const fetchGlobalChat = async () => {
    if (!globalChatFeed) return;
    try {
      const q = lastGlobalChatId > 0 ? `?since_id=${lastGlobalChatId}` : "";
      const r = await fetch(`/api/chat/global${q}`);
      const body = await r.json();
      if (!r.ok || !body || !body.ok) return;
      const canMod = Boolean(body.viewer_can_moderate);
      if (lastViewerChatModerate !== null && lastViewerChatModerate !== canMod) {
        lastGlobalChatId = 0;
        lastViewerChatModerate = canMod;
        await fetchGlobalChat();
        return;
      }
      lastViewerChatModerate = canMod;
      const msgs = Array.isArray(body.messages) ? body.messages : [];
      if (!lastGlobalChatId) {
        if (msgs.length) {
          appendGlobalChatLines(globalChatFeed, msgs, { reset: true });
          lastGlobalChatId = msgs.reduce((a, m) => Math.max(a, Number(m.id) || 0), 0);
        } else {
          globalChatFeed.innerHTML = "<div class='muted'>Пока пусто — напишите первым.</div>";
        }
        return;
      }
      if (msgs.length) {
        appendGlobalChatLines(globalChatFeed, msgs, { reset: false });
        lastGlobalChatId = msgs.reduce((a, m) => Math.max(a, Number(m.id) || 0), lastGlobalChatId);
      }
    } catch (_e) {
      /* ignore */
    }
  };

  if (globalChatFeed && !globalChatFeed.dataset.chatModBound) {
    globalChatFeed.dataset.chatModBound = "1";
    globalChatFeed.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button[data-chat-mod]") : null;
      if (!btn || !globalChatFeed.contains(btn)) return;
      ev.preventDefault();
      const act = btn.getAttribute("data-chat-mod");
      const mid = (btn.getAttribute("data-mid") || "").trim();
      const target = (btn.getAttribute("data-target") || "").trim();
      void (async () => {
        try {
          if (act === "hide") {
            if (!mid) return;
            const r = await fetch(`/api/chat/global/${encodeURIComponent(mid)}/hide`, { method: "POST" });
            const b = await r.json().catch(() => ({}));
            if (!r.ok || !b.ok) {
              setStatus(b.error ? `Чат: ${b.error}` : "Не удалось скрыть сообщение", "err");
              return;
            }
          } else if (act === "delete") {
            if (!mid) return;
            const r = await fetch(`/api/chat/global/${encodeURIComponent(mid)}`, { method: "DELETE" });
            const b = await r.json().catch(() => ({}));
            if (!r.ok || !b.ok) {
              setStatus(b.error ? `Чат: ${b.error}` : "Не удалось удалить сообщение", "err");
              return;
            }
          } else if (act === "ban_chat") {
            if (!target) return;
            const raw = window.prompt(
              "Мут в общем чате: сколько часов? (для снятия мута введите 0 — только администратор)",
              "24"
            );
            if (raw === null) return;
            let hours = Math.floor(Number(String(raw).trim()));
            if (!Number.isFinite(hours)) hours = 24;
            const r = await fetch("/api/chat/moderation/chat-ban", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ player_id: target, hours }),
            });
            const b = await r.json().catch(() => ({}));
            if (!r.ok || !b.ok) {
              setStatus(b.error ? `Чат: ${b.error}` : "Не удалось применить мут", "err");
              return;
            }
            setStatus(hours <= 0 ? "Мут общего чата снят" : `Мут общего чата: ${hours} ч`, "ok");
          } else if (act === "ban_account") {
            if (!target) return;
            if (
              !window.confirm(
                "Отключить вход в игру для этого игрока (аккаунт)? Восстановление — через админку или повторное действие."
              )
            )
              return;
            const r = await fetch("/api/chat/moderation/account-ban", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ player_id: target, disable: true }),
            });
            const b = await r.json().catch(() => ({}));
            if (!r.ok || !b.ok) {
              setStatus(b.error ? `Чат: ${b.error}` : "Не удалось отключить аккаунт", "err");
              return;
            }
            setStatus("Аккаунт отключён", "ok");
          } else {
            return;
          }
          lastGlobalChatId = 0;
          await fetchGlobalChat();
        } catch (_e) {
          setStatus("Ошибка сети (модерация чата)", "err");
        }
      })();
    });
  }

  const formatPrivateThreadTs = (iso) => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (!Number.isFinite(d.getTime())) return "";
      return d.toLocaleString(undefined, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_e) {
      return "";
    }
  };

  const updatePrivateTabBadge = (newContacts, unread) => {
    if (!privateTabBadge) return;
    const nc = Number(newContacts) || 0;
    const nu = Number(unread) || 0;
    if (nc <= 0 && nu <= 0) {
      privateTabBadge.textContent = "";
      privateTabBadge.classList.add("hidden");
      privateTabBadge.setAttribute("aria-hidden", "true");
      return;
    }
    privateTabBadge.textContent = `${nc}/${nu}`;
    privateTabBadge.classList.remove("hidden");
    privateTabBadge.setAttribute("aria-hidden", "false");
  };

  const refreshPrivateBadge = async () => {
    try {
      const r = await fetch("/api/chat/private/badge");
      const body = await r.json();
      if (!r.ok || !body || !body.ok) return;
      updatePrivateTabBadge(body.new_contacts ?? 0, body.unread_messages ?? 0);
    } catch (_e) {
      /* ignore */
    }
  };

  const activatePrivateChatUi = async (pid, sendReceiptsChecked) => {
    const peer = String(pid || "").trim();
    if (!peer) return;
    privatePeerActive = peer;
    pendingIntroPeerId = "";
    lastPrivateChatId = 0;
    if (privateChatPeer) privateChatPeer.value = peer;
    if (privateChatWrap) privateChatWrap.classList.remove("hidden");
    if (privateThreadsEl) privateThreadsEl.classList.add("hidden");
    if (privateSendReadReceiptCb) {
      privateReceiptsProgrammaticToggle = true;
      privateSendReadReceiptCb.checked = Boolean(sendReceiptsChecked);
      queueMicrotask(() => {
        privateReceiptsProgrammaticToggle = false;
      });
    }
    if (privateChatFeed) privateChatFeed.innerHTML = "<div class='muted'>Загрузка…</div>";
    await fetchPrivateChat();
    void refreshPrivateBadge();
  };

  const completePrivateIntro = async (sendReceipts) => {
    const pid = pendingIntroPeerId;
    if (!pid) return;
    if (privateIntroOverlay) privateIntroOverlay.classList.add("hidden");
    try {
      const r = await fetch("/api/chat/private/thread/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peer_id: pid, send_read_receipts: Boolean(sendReceipts) }),
      });
      const body = await r.json();
      if (!r.ok || !body || !body.ok) {
        pendingIntroPeerId = "";
        if (statusEl)
          statusEl.textContent = `ЛС: ${(body && body.error) || "не удалось открыть диалог"}`;
        return;
      }
      await activatePrivateChatUi(pid, sendReceipts);
    } catch (_e) {
      pendingIntroPeerId = "";
      if (statusEl) statusEl.textContent = "ЛС: сеть";
    }
  };

  const openPrivatePeer = async (peerId) => {
    const pid = String(peerId || "").trim();
    if (!pid) return;
    try {
      const r = await fetch(`/api/chat/private/thread/meta?peer_id=${encodeURIComponent(pid)}`);
      const meta = await r.json();
      if (!r.ok || !meta || !meta.ok) {
        if (statusEl) statusEl.textContent = `ЛС: ${(meta && meta.error) || "контакт недоступен"}`;
        return;
      }
      if (meta.needs_intro) {
        pendingIntroPeerId = pid;
        if (privateIntroPeerNameEl)
          privateIntroPeerNameEl.textContent = String(meta.peer_display_name || pid);
        if (privateIntroOverlay) privateIntroOverlay.classList.remove("hidden");
        return;
      }
      await activatePrivateChatUi(pid, Boolean(meta.send_read_receipts));
    } catch (_e) {
      if (statusEl) statusEl.textContent = "ЛС: сеть";
    }
  };

  const fetchPrivateChat = async () => {
    if (!privateChatFeed || !privatePeerActive) return;
    try {
      const q =
        lastPrivateChatId > 0
          ? `?peer_id=${encodeURIComponent(privatePeerActive)}&since_id=${lastPrivateChatId}`
          : `?peer_id=${encodeURIComponent(privatePeerActive)}`;
      const r = await fetch(`/api/chat/private${q}`);
      const body = await r.json();
      if (!r.ok || !body || !body.ok) {
        if (body && body.error === "blocked_peer")
          privateChatFeed.innerHTML = "<div class='muted'>Переписка скрыта (игнор).</div>";
        return;
      }
      const msgs = Array.isArray(body.messages) ? body.messages : [];
      if (!lastPrivateChatId) {
        if (msgs.length) {
          appendChatLines(privateChatFeed, msgs, { reset: true, privateDm: true });
          lastPrivateChatId = msgs.reduce((a, m) => Math.max(a, Number(m.id) || 0), 0);
        } else {
          privateChatFeed.innerHTML = "<div class='muted'>Нет сообщений. Напишите первым.</div>";
        }
        void refreshPrivateBadge();
        return;
      }
      if (msgs.length) {
        appendChatLines(privateChatFeed, msgs, { reset: false, privateDm: true });
        lastPrivateChatId = msgs.reduce((a, m) => Math.max(a, Number(m.id) || 0), lastPrivateChatId);
      }
      void refreshPrivateBadge();
    } catch (_e) {
      /* ignore */
    }
  };

  const loadPrivateThreads = async () => {
    if (!privateThreadsEl) return;
    try {
      const r = await fetch("/api/chat/private/threads");
      const body = await r.json();
      if (!r.ok || !body || !body.ok) {
        privateThreadsEl.innerHTML = "<div class='muted'>Не удалось загрузить диалоги.</div>";
        return;
      }
      updatePrivateTabBadge(body.badge_new_contacts ?? 0, body.badge_unread ?? 0);
      const threads = Array.isArray(body.threads) ? body.threads : [];
      if (!threads.length) {
        privateThreadsEl.innerHTML =
          "<div class='muted'>Нет переписок. Укажите идентификатор оператора выше или дождитесь сообщения.</div>";
        return;
      }
      privateThreadsEl.innerHTML = threads
        .map((t) => {
          const un = Number(t.unread_incoming) || 0;
          const unreadSpan =
            un > 0 ? `<span class="private-thread-unread">${escChatTxt(String(un))}</span>` : "";
          const ts = formatPrivateThreadTs(t.last_message_at);
          const tsLine = ts
            ? `<span class="private-thread-last-at">${escChatTxt(ts)}</span>`
            : "";
          return `<button type="button" class="btn-secondary private-thread-btn" data-peer="${escChatTxt(t.peer_id)}"><b>${escChatTxt(t.display_name)}</b>${unreadSpan}<span class="muted"> · ${escChatTxt(t.last_preview || "")}</span>${tsLine}</button>`;
        })
        .join("");
      privateThreadsEl.querySelectorAll(".private-thread-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const pid = btn.getAttribute("data-peer");
          if (pid) void openPrivatePeer(pid);
        });
      });
    } catch (_e) {
      privateThreadsEl.innerHTML = "<div class='muted'>Ошибка сети.</div>";
    }
  };

  const closePrivatePeerView = () => {
    privatePeerActive = "";
    pendingIntroPeerId = "";
    lastPrivateChatId = 0;
    if (privateIntroOverlay) privateIntroOverlay.classList.add("hidden");
    if (privateChatPeer) privateChatPeer.value = "";
    if (privateChatWrap) privateChatWrap.classList.add("hidden");
    if (privateThreadsEl) privateThreadsEl.classList.remove("hidden");
    void loadPrivateThreads();
  };

  const patchPrivateReceiptPrefs = async (peer, val) => {
    try {
      const r = await fetch("/api/chat/private/thread/prefs", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peer_id: peer, send_read_receipts: Boolean(val) }),
      });
      const body = await r.json();
      if (!r.ok || !body || !body.ok) {
        if (statusEl) statusEl.textContent = `ЛС: ${(body && body.error) || "не удалось сохранить"}`;
        return;
      }
      void fetchPrivateChat();
      void refreshPrivateBadge();
    } catch (_e) {
      if (statusEl) statusEl.textContent = "ЛС: сеть";
    }
  };
  const planetModalOverlay = document.getElementById("planet-modal-overlay");
  const planetModalBody = document.getElementById("planet-modal-body");
  /** Кэш последнего ответа `placement_checks` для пересчёта строки стоимости при смене количества (планета). */
  let lastBuildPlacementResults = null;
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
  /** Активный «маршрут» из правой колонки: фильтрует центр только по недостающим зависимостям. */
  let techModalPathGuide = null; // null | { targetId: string, prereqIds: string[] }
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
  const uiMapModeTactical = document.getElementById("ui-map-mode-tactical");
  const uiMapModeGraphic = document.getElementById("ui-map-mode-graphic");
  const uiMapGraphicHint = document.getElementById("ui-map-graphic-hint");
  const uiMapShowCoords = document.getElementById("ui-map-show-coords");
  const uiAdminFogWrap = document.getElementById("ui-admin-fog-wrap");
  const uiRevealFogAdmin = document.getElementById("ui-reveal-fog-admin");
  const uiAdminGotoX = document.getElementById("ui-admin-goto-x");
  const uiAdminGotoY = document.getElementById("ui-admin-goto-y");
  const uiAdminGotoZ = document.getElementById("ui-admin-goto-z");
  const uiAdminGotoBtn = document.getElementById("ui-admin-goto-btn");
  const mapWindowSizeLabel = document.getElementById("map-window-size-label");
  const uiMapWindowMinus = document.getElementById("ui-map-window-minus");
  const uiMapWindowPlus = document.getElementById("ui-map-window-plus");
  const uiMapWindowLabel = document.getElementById("ui-map-window-label");
  const uiMapPreset13 = document.getElementById("ui-map-preset-13");
  const uiMapPreset17 = document.getElementById("ui-map-preset-17");
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
  const topRpChipEl = document.getElementById("top-rp-chip");
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
      const mapMode = s && s.mapMode === "graphic" ? "graphic" : "tactical";
      const mapShowCoords = !(s && s.mapShowCoords === false);
      const revealFogAdmin = Boolean(s && s.revealFogAdmin);
      return {
        fontSize,
        lineHeight,
        battleFocusRadius,
        forceAttackGuaranteed,
        mapMode,
        mapShowCoords,
        revealFogAdmin,
      };
    } catch (_e) {
      return {
        fontSize: 14,
        lineHeight: 1.35,
        battleFocusRadius: 6,
        forceAttackGuaranteed: false,
        mapMode: "tactical",
        mapShowCoords: true,
        revealFogAdmin: false,
      };
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
    const mm = s.mapMode === "graphic" ? "graphic" : "tactical";
    if (uiMapModeTactical) uiMapModeTactical.checked = mm === "tactical";
    if (uiMapModeGraphic) uiMapModeGraphic.checked = mm === "graphic";
    if (uiMapShowCoords) uiMapShowCoords.checked = s.mapShowCoords !== false;
    if (uiRevealFogAdmin) uiRevealFogAdmin.checked = Boolean(s.revealFogAdmin);
    if (uiMapGraphicHint) uiMapGraphicHint.classList.toggle("hidden", mm !== "graphic");
    applyUiSettings(s);
  };

  // init UI settings early
  const initialUiSettings = loadUiSettings();
  applyUiSettings(initialUiSettings);
  if (uiAdminFogWrap) uiAdminFogWrap.classList.toggle("hidden", !playerIsGameAdmin);

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
    if (!keys.length) return DEFAULT_FLEET_QTY_KEYS.slice();
    const byId = new Map();
    if (Array.isArray(bb.units)) {
      for (const u of bb.units) {
        if (u && typeof u.id === "string") byId.set(String(u.id), u);
      }
    }
    return keys
      .filter((k) => {
        const uid = ua[k];
        if (typeof uid !== "string") return true;
        const u = byId.get(String(uid));
        if (u && u.fleet_composition_allowed === false) return false;
        return true;
      })
      .sort((a, b) => a.localeCompare(b));
  };

  /** Строки в модалке флота: все алиасы из баланса + типы с ненулевым количеством в текущем составе. */
  const fleetQtyKeysForUi = (comp) => {
    const merged = new Set(fleetLogicalKeysBalanceOnly());
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (comp && typeof comp === "object" && bb && bb.ok) {
      const ua = bb.aliases && bb.aliases.unit_aliases;
      const byId = new Map();
      if (Array.isArray(bb.units)) {
        for (const u of bb.units) {
          if (u && typeof u.id === "string") byId.set(String(u.id), u);
        }
      }
      for (const [k, raw] of Object.entries(comp)) {
        if (!k || Number(raw) <= 0) continue;
        const ks = String(k).trim();
        if (!ks) continue;
        const uid =
          ua && typeof ua === "object" && typeof ua[ks] === "string" ? ua[ks] : null;
        const u = uid ? byId.get(String(uid)) : null;
        if (u && u.fleet_composition_allowed === false) continue;
        merged.add(ks);
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

  /** Для сообщений статуса: имя постройки по балансу, без технического ключа если есть русское название. */
  const buildingStatusCaptionRu = (logicalType, fallback = "постройка") => {
    const raw = logicalType != null && String(logicalType).trim() ? String(logicalType).trim() : "";
    return raw ? buildingLabelRu(raw) : fallback;
  };

  /** Свои / чужие / без владельца — для строки «Построено» в HUD клетки. */
  const builtHudAffiliation = (ownerId) => {
    const oid = ownerId != null && ownerId !== "" ? String(ownerId).trim() : "";
    if (!oid) return "neutral";
    if (playerId && String(playerId) === oid) return "own";
    return "enemy";
  };

  /** HTML фрагмент: постройки и форпосты, сгруппированы по принадлежности и цвету. */
  const formatBuiltHudHtml = (objs) => {
    const built = objs.filter((o) => o && (o.type === "building" || o.type === "outpost"));
    if (!built.length) return "";
    const byAff = {
      own: new Map(),
      enemy: new Map(),
      neutral: new Map(),
    };
    for (const o of built) {
      const aff = builtHudAffiliation(o.owner);
      let label;
      if (o.type === "outpost") {
        label = o.name && String(o.name).trim() ? String(o.name).trim() : "Форпост";
      } else {
        label = buildingLabelRu(o.building_type ? String(o.building_type) : "постройка");
        const lv = Number(o.level);
        if (Number.isFinite(lv) && lv > 1) label = `${label} ур.${lv}`;
      }
      const m = byAff[aff];
      m.set(label, (m.get(label) || 0) + 1);
    }
    const cls = { own: "hud-built--own", enemy: "hud-built--enemy", neutral: "hud-built--neutral" };
    const order = ["own", "neutral", "enemy"];
    const chunks = [];
    for (const aff of order) {
      const m = byAff[aff];
      if (!m.size) continue;
      const bits = [];
      for (const [lbl, n] of Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0], "ru"))) {
        bits.push(n > 1 ? `${escHtml(lbl)}×${escHtml(String(n))}` : escHtml(lbl));
      }
      chunks.push(`<span class="${cls[aff]}">${bits.join(", ")}</span>`);
    }
    return chunks.join(" · ");
  };

  /** Подписи техов из `/api/balance` для ошибок `tech_required`. */
  const techIdsToRuCsv = (ids) => {
    const arr = Array.isArray(ids) ? ids.filter((x) => x != null && String(x).trim()) : [];
    if (!arr.length) return "";
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    const list = bb && bb.ok && Array.isArray(bb.tech) ? bb.tech : [];
    const byId = new Map(list.filter((t) => t && t.id).map((t) => [String(t.id), t]));
    return arr
      .map((id) => {
        const t = byId.get(String(id));
        return t && t.name ? String(t.name) : String(id);
      })
      .join(", ");
  };

  const resolveBuildingCanonId = (logicalType) => {
    const k = String(logicalType || "").trim().toLowerCase();
    if (!k) return "";
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok) return k;
    const ba = bb.aliases && bb.aliases.building_aliases;
    if (ba && typeof ba === "object" && Object.prototype.hasOwnProperty.call(ba, k)) return String(ba[k]);
    return k;
  };

  const resolveBuildingDef = (logicalType) => {
    const bid = resolveBuildingCanonId(logicalType);
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok || !bid) return null;
    const buildings = Array.isArray(bb.buildings) ? bb.buildings : [];
    return buildings.find((b) => b && String(b.id) === String(bid)) || null;
  };

  const ONBOARDING_MILESTONES_KEY = "guardstar.onboarding.milestones.v1";
  const readOnboardingMilestones = () => {
    try {
      const raw = localStorage.getItem(ONBOARDING_MILESTONES_KEY);
      const o = raw ? JSON.parse(raw) : {};
      return o && typeof o === "object" ? o : {};
    } catch {
      return {};
    }
  };
  const mergeOnboardingMilestones = (patch) => {
    if (!patch || typeof patch !== "object") return;
    try {
      const cur = readOnboardingMilestones();
      const next = { ...cur, ...patch };
      localStorage.setItem(ONBOARDING_MILESTONES_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    renderOnboardingGoals();
  };

  const onboardingAtHomeColony = (x, y, z) => {
    const hp = worldState.home_planet;
    if (!hp || !hp.pos) return false;
    return Number(x) === Number(hp.pos.x) && Number(y) === Number(hp.pos.y) && Number(z) === Number(hp.pos.z ?? 0);
  };

  const recordColonyBuildMilestone = (buildingTypeRaw, x, y, z) => {
    if (!onboardingAtHomeColony(x, y, z)) return;
    const k = String(buildingTypeRaw || "").trim().toLowerCase();
    if (!k) return;
    const canon = String(resolveBuildingCanonId(k) || k).toLowerCase();
    const food = new Set(["basic_farm", "hydro_farm"]);
    const energy = new Set(["reactor", "solar_array"]);
    const patch = {};
    if (food.has(canon) || food.has(k)) patch.colonyFood = true;
    if (energy.has(canon) || energy.has(k)) patch.colonyEnergy = true;
    if (Object.keys(patch).length) mergeOnboardingMilestones(patch);
  };

  /** Римский суффикс тира постройки (I, II…) для строки модалки. */
  const buildingTierRoman = (tier) => {
    const n = Number(tier) || 0;
    if (n < 1) return "";
    const map = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII"];
    return n < map.length ? map[n] : `${n}`;
  };

  /** Категория для группировки «еда / вода / прочее» по эффектам производства из баланса. */
  const buildingSurfaceProduceCat = (def) => {
    if (!def || typeof def !== "object") return "other";
    const eff = def.effects && typeof def.effects === "object" ? def.effects : null;
    if (!eff) return "other";
    const prod = eff.production_per_tick_add || eff.production_per_sol_add || null;
    if (!prod || typeof prod !== "object") return "other";
    const food = Number(prod.food) || 0;
    const water = Number(prod.water) || 0;
    if (food > 0 && water <= 0) return "food";
    if (water > 0 && food <= 0) return "water";
    return "other";
  };

  const buildingSurfaceGroupTitle = (def) => {
    if (!def || typeof def !== "object") return "Постройка";
    const base = typeof def.name === "string" && def.name.trim() ? def.name.trim() : "Постройка";
    const tr = Number(def.tier ?? 0) || 0;
    const r = buildingTierRoman(tr);
    return tr >= 1 && r ? `${base} ${r}` : base;
  };

  /** Есть ли в `/api/balance` цепочка upgrade→to с существующим зданием-целью (как на сервере). */
  const buildingHasBalanceUpgrade = (logicalType) => {
    const def = resolveBuildingDef(logicalType);
    if (!def || typeof def !== "object") return false;
    const up = def.upgrade;
    if (!up || typeof up !== "object") return false;
    const to = String(up.to || "").trim().toLowerCase();
    if (!to) return false;
    const targetCanon = resolveBuildingCanonId(to);
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok || !targetCanon) return false;
    const buildings = Array.isArray(bb.buildings) ? bb.buildings : [];
    return buildings.some((bd) => bd && String(bd.id).toLowerCase() === String(targetCanon).toLowerCase());
  };

  /** Объект `upgrade.cost` из баланса (или null, если апгрейда нет; пустой объект, если `cost` в JSON не задан). */
  const buildingUpgradeCostObj = (logicalType) => {
    const def = resolveBuildingDef(logicalType);
    if (!def || typeof def !== "object") return null;
    const up = def.upgrade;
    if (!up || typeof up !== "object") return null;
    const c = up.cost;
    if (!c || typeof c !== "object") return {};
    return c;
  };

  /** Объект `build.cost` из баланса (или null). */
  const buildingBuildCostObj = (logicalType) => {
    const def = resolveBuildingDef(logicalType);
    if (!def || typeof def !== "object") return null;
    const b = def.build;
    if (!b || typeof b !== "object") return null;
    const c = b.cost;
    if (!c || typeof c !== "object") return null;
    return c;
  };

  /** Снимок склада дома для сравнения со стоимостью постройки (поле / модалка). */
  const economySnapshotForBuildCosts = () => {
    const e = worldState && worldState.economy;
    if (!e || typeof e !== "object") return {};
    return {
      metal: Number(e.metal) || 0,
      crystal: Number(e.crystal) || 0,
      energy: Number(e.energy) || 0,
      fuel: Number(e.fuel) || 0,
      food: Number(e.food) || 0,
      water: Number(e.water) || 0,
    };
  };

  /** HTML строки «Со склада дома…» с подсветкой нехватки (span.build-cost-miss). `labelPrefix` без двоеточия. */
  const formatBuildCardCostLineInnerHtml = (need, have, labelPrefix = "Со склада дома") => {
    if (!need || typeof need !== "object") return "";
    const keys = [
      ["metal", "⛏"],
      ["crystal", "💎"],
      ["energy", "⚡"],
      ["fuel", "⛽"],
      ["food", "🍲"],
      ["water", "💧"],
    ];
    const parts = [];
    for (const [k, g] of keys) {
      const n = Number(need[k]);
      if (!Number.isFinite(n) || n <= 0) continue;
      const h = Number(have && have[k]);
      const miss = Number.isFinite(h) && h < n;
      parts.push(`<span class="${miss ? "build-cost-miss" : "build-cost-ok"}">${g}${Math.trunc(n)}</span>`);
    }
    if (!parts.length) return "";
    const lab = labelPrefix && String(labelPrefix).trim() ? String(labelPrefix).trim() : "Со склада дома";
    return `${lab}: ${parts.join(" ")}`;
  };

  /** Перерисовать строки стоимости карточек строительства по кэшу placement_checks и текущему полю количества. */
  const repaintBuildCardCostLines = () => {
    if (!planetModalBody || !lastBuildPlacementResults || typeof lastBuildPlacementResults !== "object") return;
    const results = lastBuildPlacementResults;
    planetModalBody.querySelectorAll(".build-card[data-b]").forEach((card) => {
      const costLine = card.querySelector(".build-card-cost-line");
      if (!costLine) return;
      const bt = card.getAttribute("data-b");
      if (!bt) return;
      const res = results[bt];
      const valEl = card.querySelector(".build-qty-val");
      const sectorField = card.classList.contains("build-card--sector-field");
      const qty = sectorField
        ? 1
        : Math.max(
            1,
            Math.min(
              100,
              valEl && valEl.tagName === "INPUT" ? parseInt(String(valEl.value || "").trim(), 10) || 1 : 1,
            ),
          );
      const baseNeed = buildingBuildCostObj(bt) || {};
      const need = scaleResourceCostObj(baseNeed, qty) || {};
      let haveSnap = economySnapshotForBuildCosts();
      if (res && res.error === "not_enough_resources" && res.have && typeof res.have === "object") {
        haveSnap = res.have;
      }
      const label = qty > 1 && !sectorField ? `Со склада дома (×${qty})` : "Со склада дома";
      const inner = formatBuildCardCostLineInnerHtml(need, haveSnap, label);
      const tickHtml = (() => {
        if (!res || !res.ok || !res.build || typeof res.build !== "object") return "";
        const tt = Number(res.build.time_ticks);
        if (!Number.isFinite(tt) || tt <= 0) return "";
        const rt = res.build.ready_at_tick_preview;
        const ct = res.build.current_tick;
        let sub = `Стройка: <b>${ruSolsCountLabel(tt)}</b> до ввода в строй.`;
        if (rt != null && ct != null) {
          sub += ` Готовность: <b>сол ${escHtml(String(rt))}</b> (сейчас <b>сол ${escHtml(String(ct))}</b>).`;
        }
        return `<div class="muted build-card-build-time" style="font-size:80%;margin-top:4px;line-height:1.3;">${sub}</div>`;
      })();
      costLine.innerHTML = (inner || '<span class="muted">—</span>') + tickHtml;
    });
  };

  /** Компактная строка ресурсов для UI (эмодзи + целое число, только ненулевые). */
  const formatResourceDictCompactRu = (cost) => {
    if (!cost || typeof cost !== "object") return "";
    const keys = [
      ["metal", "⛏"],
      ["crystal", "💎"],
      ["energy", "⚡"],
      ["fuel", "⛽"],
      ["food", "🍲"],
      ["water", "💧"],
    ];
    const parts = [];
    for (const [k, g] of keys) {
      const n = Number(cost[k]);
      if (!Number.isFinite(n) || n <= 0) continue;
      parts.push(`${g}${Math.trunc(n)}`);
    }
    return parts.join(" ");
  };

  /** Суммарная стоимость = базовый `upgrade.cost` × целое число шагов. */
  const scaleResourceCostObj = (cost, mul) => {
    if (!cost || typeof cost !== "object") return null;
    const m = Math.max(0, Math.trunc(Number(mul)) || 0);
    if (m <= 0) return {};
    const out = {};
    for (const k of Object.keys(cost)) {
      const v = Number(cost[k]);
      if (Number.isFinite(v) && v > 0) out[k] = v * m;
    }
    return out;
  };

  const readPlanetBuiltQtyFromCard = (card) => {
    if (!card) return 1;
    const valEl = card.querySelector(".planet-built-qty-val");
    const max = Math.max(1, parseInt(card.getAttribute("data-built-max"), 10) || 1);
    const raw = valEl && (valEl.tagName === "INPUT" ? valEl.value : valEl.textContent);
    return Math.max(1, Math.min(max, parseInt(String(raw != null ? raw : "").trim(), 10) || 1));
  };

  const syncPlanetBuiltUpgradeCostLine = (card) => {
    const wrap = card && card.querySelector(".planet-built-cost-wrap");
    if (!wrap) return;
    const enc = wrap.getAttribute("data-per-upgrade-cost");
    if (!enc) return;
    let base;
    try {
      base = JSON.parse(decodeURIComponent(enc));
    } catch {
      return;
    }
    const qty = readPlanetBuiltQtyFromCard(card);
    const scaled = scaleResourceCostObj(base, qty) || {};
    const icons = formatResourceDictCompactRu(scaled);
    const mulEl = wrap.querySelector(".planet-built-cost-mul");
    const iconsEl = wrap.querySelector(".planet-built-cost-icons");
    if (mulEl) mulEl.textContent = String(qty);
    if (iconsEl) iconsEl.textContent = icons || "—";
    const stepStr = formatResourceDictCompactRu(base);
    const sumStr = formatResourceDictCompactRu(scaled);
    const upBtn = card.querySelector(".planet-built-upgrade");
    if (upBtn && !upBtn.disabled) {
      upBtn.title =
        qty <= 1
          ? `Улучшить по очереди (склад дома). За один шаг: ${stepStr || "—"}`
          : `Улучшить подряд ${qty} построек (склад дома). Суммарно: ${sumStr || "—"} (по ${stepStr || "—"} за шаг)`;
    }
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
    frigate: "🛸",
    colonizer: "🌍",
    colony_support: "🔗",
    scout_medium: "🛰",
  };

  /** Доминантный тип флота на карте (поле `unit_type`): бойные — спрайт истребителя, остальные — разведка. */
  const fleetMapGraphicIsCombatDominant = (unitType) => {
    const u = String(unitType || "").trim().toLowerCase();
    return u === "fighter" || u === "corvette" || u === "frigate";
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

  /** Краткая «цель / роль» корпуса для раскрывающегося блока в модалке флота. */
  const fleetUnitRolePurposeRu = (logicalKey) => {
    const k = String(logicalKey || "");
    if (k === "colonizer") {
      return "Колония: основание новой колонии на подходящей планете (не полевая база).";
    }
    if (k === "colony_support") {
      return "Экспансия: полевая стройка и логистика; колонию на планете не открывает.";
    }
    if (k === "supplier") {
      return "Империя: влияет на радиус снабжения со столицы; в бою почти не защищает.";
    }
    if (k === "freighter") {
      return "Флот: запас энергии на борту и экономия топлива на перелёт; без оружия.";
    }
    const g = fleetUiRoleGroup(logicalKey);
    if (g === "recon") return "Разведка: скорость и сбор сведений, слабый бой.";
    if (g === "combat") return "Бой: урон и стойкость в столкновениях.";
    return "Техника и логистика: строительство и вспомогательные задачи.";
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

  const showActionFeedback = (target, message, kind = "info") => {
    if (!target || !message) return;
    const prev = actionFeedbackTimers.get(target);
    if (prev) clearTimeout(prev);
    target.textContent = message;
    target.classList.remove("hud-action-feedback--ok", "hud-action-feedback--err", "hud-action-feedback--info");
    if (kind === "ok") target.classList.add("hud-action-feedback--ok");
    else if (kind === "err") target.classList.add("hud-action-feedback--err");
    else target.classList.add("hud-action-feedback--info");
    target.hidden = false;
    const ms = 8000 + Math.floor(Math.random() * 4001);
    const id = setTimeout(() => {
      actionFeedbackTimers.delete(target);
      target.textContent = "";
      target.hidden = true;
      target.classList.remove("hud-action-feedback--ok", "hud-action-feedback--err", "hud-action-feedback--info");
    }, ms);
    actionFeedbackTimers.set(target, id);
  };

  const showFleetActionMessage = (message, kind = "info") => {
    setStatus(message, kind);
    const inCreate = fleetCreateOverlay && !fleetCreateOverlay.classList.contains("hidden");
    const inFleet = fleetModalOverlay && !fleetModalOverlay.classList.contains("hidden");
    if (inCreate && fleetCreateFeedbackEl) showActionFeedback(fleetCreateFeedbackEl, message, kind);
    else if (inFleet && fleetModalFeedbackEl) showActionFeedback(fleetModalFeedbackEl, message, kind);
    else if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, message, kind);
  };

  const planetModalFeedbackEl = () =>
    planetModalBody && planetModalBody.querySelector("#planet-modal-action-feedback");

  const pushSystemToast = (message) => {
    if (!systemToastsEl || !message) return;
    while (systemToastsEl.querySelectorAll(".system-toast").length >= 5) {
      const first = systemToastsEl.querySelector(".system-toast");
      if (first) first.remove();
      else break;
    }
    const row = document.createElement("div");
    row.className = "system-toast";
    row.textContent = message;
    systemToastsEl.appendChild(row);
    setTimeout(() => {
      try {
        row.remove();
      } catch (_e) {
        /* ignore */
      }
    }, 14000);
  };

  const syncSystemToastsFromEvents = (events) => {
    if (!systemToastsEl || !Array.isArray(events)) return;
    const now = Date.now();
    for (const e of events) {
      if (!e || eventIsToastChannel(e) !== true) continue;
      const eid = e.id != null ? Number(e.id) : null;
      if (eid != null && Number.isFinite(eid)) {
        if (toastEventIdsSeen.has(eid)) continue;
        toastEventIdsSeen.add(eid);
        while (toastEventIdsSeen.size > TOAST_EVENT_IDS_MAX) {
          const it = toastEventIdsSeen.values().next();
          if (it.done) break;
          toastEventIdsSeen.delete(it.value);
        }
      }
      const pl = e.payload && typeof e.payload === "object" ? e.payload : {};
      const dk = pl.ui_dedupe_key != null ? String(pl.ui_dedupe_key) : "";
      if (dk) {
        const prev = toastDedupeKeyLastMs.get(dk) || 0;
        if (now - prev < 45000) continue;
        toastDedupeKeyLastMs.set(dk, now);
      }
      const msg = typeof e.message === "string" && e.message.trim() ? e.message.trim() : "Системное уведомление";
      pushSystemToast(msg);
    }
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

  /** Текст для сворачиваемого блока «Подробный расчёт» (формулы, шаги, состав). */
  const formatFleetCombatDetailsRu = (p) => {
    if (!p || typeof p !== "object") return "";
    const lines = [];
    const bc = p.battle_calculation;
    if (bc && typeof bc === "object") {
      if (bc.how_score_works) lines.push(String(bc.how_score_works));
      const f = bc.factors || {};
      lines.push(
        `Базовые очки (до броска): атакующий ${f.attacker_base ?? "—"}, защитник ${f.defender_base ?? "—"}`,
      );
      const sup = f.supply_zone_bonus || {};
      const zatk = sup.attacker != null ? sup.attacker : f.attacker_supply_zone ? 1.05 : 1;
      const zdef = sup.defender != null ? sup.defender : f.defender_home_zone ? 1.08 : 1;
      lines.push(`Множитель территории: атакующий ×${zatk}, защитник ×${zdef} (снабжение +5% / дом +8%)`);
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
        `После территории: атакующий ≈ ${f.attacker_effective_before_roll ?? f.attacker_effective ?? "—"}, защитник ≈ ${f.defender_effective_before_roll ?? f.defender_effective ?? "—"}`,
      );
      const rb = bc.rolls || {};
      if (Object.keys(rb).length) {
        lines.push(
          `Случайный множитель (0.94…1.08): атакующий ×${rb.random_factor_attacker ?? "—"}, защитник ×${rb.random_factor_defender ?? "—"}`,
        );
        lines.push(
          `Очки после броска: ${rb.rolled_score_attacker ?? "—"} vs ${rb.rolled_score_defender ?? "—"} (${rb.rule || ""})`,
        );
      }
      const comp = bc.composition_start || {};
      if (comp.attacker || comp.defender) {
        lines.push(`Состав атакующего до боя: ${formatComposition(comp.attacker) || "—"}`);
        lines.push(`Состав защитника до боя: ${formatComposition(comp.defender) || "—"}`);
      }
    }
    const cs = p.consequences && typeof p.consequences === "object" ? p.consequences : null;
    if (cs) {
      const yFrac = cs.your_ship_loss_fraction_applied;
      const dFrac = cs.ship_loss_fraction_applied;
      const defFrac = cs.defender_ship_loss_fraction_applied;
      const extra = [];
      if (typeof yFrac === "number")
        extra.push(`Доля потерь победителя (расчёт): ${(yFrac * 100).toFixed(1)}%.`);
      if (typeof defFrac === "number")
        extra.push(`Доля потерь защитника (расчёт): ${(defFrac * 100).toFixed(1)}%.`);
      if (typeof dFrac === "number")
        extra.push(`Доля потерь при обороне (расчёт): ${(dFrac * 100).toFixed(1)}%.`);
      if (extra.length) {
        lines.push("");
        lines.push("Доли потерь по формулам (справочно):");
        for (const x of extra) lines.push(x);
      }
    }
    if (!lines.length) return "";
    return lines.map((ln) => escHtml(ln)).join("\n");
  };

  /** Сумма чисел в объектe состава (before/after). */
  const sumFleetCompositionTotals = (m) =>
    Object.values(m && typeof m === "object" ? m : {}).reduce((s, x) => s + Number(x || 0), 0);

  /**
   * Потери → исход столкновения → территория (клетка последней).
   * Процент в строке потерь считается от фактических before/after, не от loss_frac модели боя.
   */
  const formatFleetCombatConsequencesRu = (cs) => {
    const lossLines = [];
    const lossDetailLines = [];
    const outcomeTailLines = [];

    if (cs && typeof cs === "object" && cs.your_fleet_survivors) {
      const y = cs.your_fleet_survivors;
      const lostN = Number(y.lost_total ?? 0);
      if (lostN > 0) {
        const tb = sumFleetCompositionTotals(y.before);
        const pctFromRoster = tb > 0 ? Math.round((lostN / tb) * 100) : null;
        let main = `Потери: −${lostN} кораблей`;
        if (pctFromRoster != null) main += ` (${pctFromRoster}%)`;
        lossLines.push(main);
        if (y.lost_by_type && Object.keys(y.lost_by_type).length) {
          lossDetailLines.push(
            Object.entries(y.lost_by_type)
              .map(([k, v]) => `${unitLabelCombat(k)} −${v}`)
              .join(", "),
          );
        }
      }
    }
    if (cs && typeof cs === "object" && cs.your_fleet_after_battle) {
      const y = cs.your_fleet_after_battle;
      const lostNw = Number(y.lost_total ?? 0);
      const tb = sumFleetCompositionTotals(y.before);
      const pctFromRoster =
        tb > 0 && lostNw > 0 ? Math.round((lostNw / tb) * 100) : null;
      let ln = `Потери после боя: −${lostNw} ед.`;
      if (pctFromRoster != null) ln += ` (${pctFromRoster}%)`;
      if (!lossLines.length) lossLines.push(ln);
    }

    if (cs && typeof cs === "object") {
      if (cs.destroyed_enemy_fleet_id || cs.enemy_fleet_removed)
        outcomeTailLines.push("Флот противника уничтожен.");
      if (cs.your_fleet_lost_id) outcomeTailLines.push("Ваш флот уничтожен.");
      if (cs.enemy_survivors_after) {
        const y = cs.enemy_survivors_after;
        outcomeTailLines.push(`Противник уцелел: списано −${y.lost_total ?? "?"} ед.`);
      }
      if (cs.winner_takes_square) {
        const w = cs.winner_takes_square;
        outcomeTailLines.push(`Клетка захвачена: (${w.x}, ${w.y}, ${w.z})`);
      }
    }
    return { lossLines, lossDetailLines, outcomeTailLines };
  };

  /** Первая строка карточки боя в ленте (без заголовка «Сол», он снаружи). */
  const formatFleetCombatHeadHtml = (ps) => {
    if (!ps || typeof ps !== "object") return "";
    const title = String(ps.title || "").trim();
    const compact =
      (ps.scores_compact != null && String(ps.scores_compact).trim()) ||
      String(ps.scores_rolled || "")
        .replace(/\s+vs\s+/gi, ":")
        .replace(/\s+/g, "");
    const scoreFrag =
      compact && compact.length
        ? ` <span class="event-fleet-combat-score">(${escHtml(compact)})</span>`
        : "";
    const match = String(ps.matchup_line || "").trim();
    const matchupFrag = match
      ? `<div class="event-fleet-combat-matchup muted">${escHtml(match)}</div>`
      : "";
    return `<div class="event-fleet-combat-head"><strong>${escHtml(title)}</strong>${scoreFrag}${matchupFrag}</div>`;
  };

  /** Системное событие боя: сверху смысл и итог, формулы — только внутри «Подробный расчёт». */
  const formatFleetCombatBlockHtml = (p, eventNumericId) => {
    if (!p || typeof p !== "object") return "";
    const ps = p.player_story && typeof p.player_story === "object" ? p.player_story : null;
    const bc = p.battle_calculation && typeof p.battle_calculation === "object" ? p.battle_calculation : null;
    const cs = p.consequences && typeof p.consequences === "object" ? p.consequences : null;
    const { lossLines, lossDetailLines, outcomeTailLines } = formatFleetCombatConsequencesRu(cs);
    const detailsInner = formatFleetCombatDetailsRu(p);
    const parts = [];

    if (ps) {
      parts.push('<div class="event-combat-summary">');
      const tk = String(ps.battle_type_label || "").trim();
      if (tk) parts.push(`<div class="event-combat-kind muted">${escHtml(tk)}</div>`);
      if (ps.effective_before_roll)
        parts.push(
          `<div class="event-combat-eff muted">Сопоставление сил перед исходом: ${escHtml(String(ps.effective_before_roll))}</div>`,
        );
      for (const ln of lossLines) parts.push(`<div class="event-combat-losses">${escHtml(ln)}</div>`);
      for (const ln of lossDetailLines)
        parts.push(`<div class="event-combat-loss-detail muted">${escHtml(ln)}</div>`);
      for (const ln of outcomeTailLines) parts.push(`<div class="event-combat-tail">${escHtml(ln)}</div>`);
      const bullets = Array.isArray(ps.cause_bullets) ? ps.cause_bullets : [];
      if (bullets.length) {
        parts.push('<div class="event-combat-causes"><span class="muted">Причина:</span><ul>');
        for (const b of bullets) parts.push(`<li>${escHtml(String(b))}</li>`);
        parts.push("</ul></div>");
      }
      parts.push("</div>");
    } else {
      for (const ln of lossLines) parts.push(`<div class="event-combat-fallback">${escHtml(ln)}</div>`);
      for (const ln of lossDetailLines)
        parts.push(`<div class="event-combat-fallback muted">${escHtml(ln)}</div>`);
      for (const ln of outcomeTailLines) parts.push(`<div class="event-combat-fallback muted">${escHtml(ln)}</div>`);
    }

    if (detailsInner || bc) {
      const eid =
        eventNumericId != null && String(eventNumericId).trim() !== ""
          ? ` data-event-id="${escHtml(String(eventNumericId))}"`
          : "";
      parts.push(`<details class="event-combat-details"${eid}>`);
      parts.push(`<summary class="event-combat-details-sum">${escHtml("Подробности боя")}</summary>`);
      if (detailsInner)
        parts.push(`<div class="event-combat-details-body muted">${detailsInner}</div>`);
      else parts.push('<div class="event-combat-details-body muted">Нет сохранённых шагов расчёта.</div>');
      parts.push("</details>");
    }
    return parts.join("");
  };

  const extractFleetNameFromMessage = (msg) => {
    const m = String(msg || "").match(/«([^»]+)»/);
    return m ? m[1].trim() : "";
  };

  /** Системное напоминание о втором подтверждении боя — выше заметность, чем рядовой лог. */
  const formatCombatPromptArrivalRowHtml = (e) => {
    const pl = e && e.payload && typeof e.payload === "object" ? e.payload : {};
    const tg = pl.target && typeof pl.target === "object" ? pl.target : {};
    const nameRaw = typeof pl.enemy_fleet_name === "string" ? pl.enemy_fleet_name.trim() : "";
    const name = nameRaw || extractFleetNameFromMessage(e.message);
    const hasXYZ = tg.x != null && tg.y != null;
    const cord = hasXYZ ? ` (${tg.x}, ${tg.y}, ${tg.z != null ? tg.z : 0})` : "";
    const foe = name ? `«${name}»` : "противник";
    const line1 = `Бой: враг ${foe}${cord}`;
    return `<div class="event event-combat-prompt" data-event-variant="prompt">
          <span class="muted">Сол ${escHtml(e.tick)}</span> —
          <span class="event-combat-prompt-title">⚠ ${escHtml(line1)}</span>
          <div class="event-combat-prompt-sub muted">${escHtml("Подтвердите бой в течение 30 с")}</div>
        </div>`;
  };

  /** Системные события мира — только `#events` (вкладка «Система»). Общий чат — отдельный поток `/api/chat/global`, сюда не подмешивается. */
  const renderEvents = (events) => {
    if (!eventsEl) return;
    const raw = Array.isArray(events) ? events : [];
    const list = filterEventsForSystemLog(raw);
    if (raw.length === 0) {
      eventsEl.innerHTML = "<div class='muted'>Пока нет событий.</div>";
      return;
    }
    if (list.length === 0) {
      eventsEl.innerHTML =
        "<div class='muted'>Нет событий в выбранной категории. Переключите фильтр или откройте «Все».</div>";
      return;
    }
    // Свежие события — сверху
    eventsEl.innerHTML = [...list]
      .reverse()
      .map((e) => {
        const ps =
          e.type === "fleet_combat" &&
          e.payload &&
          e.payload.player_story &&
          typeof e.payload.player_story === "object"
            ? e.payload.player_story
            : null;

        if (e.type === "combat_prompt_arrival") return formatCombatPromptArrivalRowHtml(e);

        const warfarePriorityTypes = new Set([
          "field_building_capture_tick",
          "building_captured",
          "building_lost_capture",
          "fleet_bombards_outpost",
          "outpost_under_bombardment",
          "outpost_destroyed",
          "bandit_strike_spawned",
          "bandit_strike_chasing",
          "bandit_patrol_spawned",
        ]);
        if (warfarePriorityTypes.has(String(e.type))) {
          return `<div class="event event-warfare-priority" data-event-variant="warfare">
            <span class="event-warfare-priority-badge" title="Важное">!</span>
            <span class="muted">Сол ${escHtml(e.tick)}</span> —
            <span class="event-warfare-priority-msg">${escHtml(e.message)}</span>
          </div>`;
        }

        if (e.type === "fleet_combat" && e.payload && ps) {
          const head = formatFleetCombatHeadHtml(ps);
          const body = `<div class="event-combat-wrap">${formatFleetCombatBlockHtml(e.payload, e.id)}</div>`;
          return `<div class="event event-fleet-combat" data-event-variant="combat-result">
              <span class="muted">Сол ${escHtml(e.tick)}</span> —
              ${head}
              ${body}
            </div>`;
        }

        const detail =
          e.type === "fleet_combat" && e.payload
            ? `<div class="event-combat-wrap">${formatFleetCombatBlockHtml(e.payload, e.id)}</div>`
            : "";
        return `<div class="event"><span class="muted">Сол ${escHtml(e.tick)}</span> — ${escHtml(e.message)}${detail}</div>`;
      })
      .join("");
    for (const det of eventsEl.querySelectorAll(
      "details.event-combat-details[data-event-id]",
    )) {
      const sid = det.getAttribute("data-event-id");
      if (sid != null && openFleetCombatDetailIds.has(sid)) det.open = true;
    }
  };

  const cellHasPlanet = (c) => Boolean(c && Array.isArray(c.objects) && c.objects.some((o) => o && o.type === "planet"));

  const cellHasOwnOutpost = (c) =>
    Boolean(
      playerId &&
        c &&
        Array.isArray(c.objects) &&
        c.objects.some(
          (o) => o && o.type === "outpost" && String(o.owner) === String(playerId),
        ),
    );

  /** Клетка не «пустой космос без метки» — по краю окна сначала выбираем, не панорамируя. */
  const mapCellHasMeaningfulContent = (c) => {
    if (!c) return false;
    if (c.flags && c.flags.has_objects) return true;
    const objs = Array.isArray(c.objects) ? c.objects : [];
    if (objs.length > 0) return true;
    const t = c.terrain;
    if (t && t !== "empty" && t !== "fog") return true;
    const g = c.glyph;
    if (g != null && String(g).trim() && ![".", "·"].includes(String(g).trim())) return true;
    return false;
  };

  const applyMapCellSelection = (c) => {
    selectedCell = { ...c };
    const myFleetObj = playerId
      ? (c.objects || []).find((o) => o && o.type === "fleet" && String(o.owner) === String(playerId))
      : null;
    if (myFleetObj && myFleetObj.id) {
      activeFleetId = String(myFleetObj.id);
      if (fleetSelectEl) fleetSelectEl.value = activeFleetId;
    }
    updateSelectedPanel();
    if (cellHasPlanet(c) || cellHasOwnOutpost(c)) void openPlanetModal(c);
    else closePlanetModal();
    renderMap();
  };

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
    const descElBuild = root.querySelector("#planet-build-type-desc");
    const descElSurface = root.querySelector("#planet-surface-build-desc");
    const descElField = root.querySelector("#planet-field-build-desc");
    const showBuildDesc = (text, fromEl) => {
      let el = descElBuild;
      if (fromEl && fromEl.closest && fromEl.closest("#planet-field-built-wrap")) el = descElField || el;
      else if (fromEl && fromEl.closest && fromEl.closest(".planet-built-groups")) el = descElSurface || el;
      if (!el) return;
      const t = text && String(text).trim() ? String(text).trim() : "";
      if (!t) {
        el.textContent = "";
        el.classList.add("hidden");
        return;
      }
      el.textContent = t;
      el.classList.remove("hidden");
    };
    root.querySelectorAll(".build-card-name-btn").forEach((nameBtn) => {
      nameBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const fromAttr = nameBtn.getAttribute("data-build-desc");
        const desc =
          (fromAttr && String(fromAttr).trim()) ||
          (nameBtn.title && String(nameBtn.title).trim()) ||
          (nameBtn.textContent && String(nameBtn.textContent).trim()) ||
          "";
        showBuildDesc(desc, nameBtn);
      });
    });
    root.querySelectorAll(".build-qty-step").forEach((stepBtn) => {
      stepBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (stepBtn.disabled) return;
        const card = stepBtn.closest(".build-card[data-b]");
        if (!card) return;
        const valEl = card.querySelector(".build-qty-val");
        const d = Number(stepBtn.getAttribute("data-d"));
        const cur = Math.max(1, Math.min(100, parseInt(valEl && (valEl.value != null ? valEl.value : valEl.textContent), 10) || 1));
        const next = Math.max(1, Math.min(100, cur + (Number.isFinite(d) ? d : 0)));
        if (valEl) {
          if (valEl.tagName === "INPUT") valEl.value = String(next);
          else valEl.textContent = String(next);
        }
        repaintBuildCardCostLines();
      });
    });
    const clampBuildQtyInput = (inp) => {
      if (!inp || inp.tagName !== "INPUT") return;
      const raw = String(inp.value || "").trim();
      let v = parseInt(raw, 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (v > 100) v = 100;
      inp.value = String(v);
      repaintBuildCardCostLines();
    };
    root.querySelectorAll(".build-qty-val").forEach((el) => {
      if (el.tagName !== "INPUT") return;
      el.addEventListener("input", () => repaintBuildCardCostLines());
      el.addEventListener("blur", () => clampBuildQtyInput(el));
      el.addEventListener("change", () => clampBuildQtyInput(el));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          el.blur();
        }
      });
    });
    root.querySelectorAll(".build-card-build").forEach((goBtn) => {
      goBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (goBtn.disabled) return;
        const card = goBtn.closest(".build-card[data-b]");
        if (!card) return;
        const bt = card.getAttribute("data-b");
        if (!bt) return;
        const valEl = card.querySelector(".build-qty-val");
        let n = 1;
        if (valEl) {
          if (valEl.tagName === "INPUT") clampBuildQtyInput(valEl);
          const raw = valEl.tagName === "INPUT" ? valEl.value : valEl.textContent;
          n = Math.max(1, Math.min(100, parseInt(raw, 10) || 1));
        }
        await placeBuildingBatch(x, y, z, bt, n, resolveBuildFleetId());
      });
    });
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
    const surfaceGroupIdsFromBtn = (btn) => {
      const wrap = btn && btn.closest("[data-surface-group-ids]");
      if (!wrap) return [];
      const raw = wrap.getAttribute("data-surface-group-ids") || "";
      return raw.split(",").map((s) => String(s).trim()).filter(Boolean);
    };
    const clampPlanetBuiltQtyInput = (inp) => {
      if (!inp || inp.tagName !== "INPUT") return;
      const card = inp.closest(".planet-built-card");
      const max = Math.max(1, parseInt(card && card.getAttribute("data-built-max"), 10) || 1);
      let v = parseInt(String(inp.value || "").trim(), 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (v > max) v = max;
      inp.value = String(v);
      if (card) syncPlanetBuiltUpgradeCostLine(card);
    };
    const builtQtyClamp = (card, delta) => {
      const valEl = card.querySelector(".planet-built-qty-val");
      const max = Math.max(1, parseInt(card.getAttribute("data-built-max"), 10) || 1);
      const cur = readPlanetBuiltQtyFromCard(card);
      const next = Math.max(1, Math.min(max, cur + (Number.isFinite(delta) ? delta : 0)));
      if (valEl) {
        if (valEl.tagName === "INPUT") valEl.value = String(next);
        else valEl.textContent = String(next);
      }
      syncPlanetBuiltUpgradeCostLine(card);
    };
    root.querySelectorAll(".planet-built-name-btn").forEach((nameBtn) => {
      nameBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const fromAttr = nameBtn.getAttribute("data-built-desc");
        const desc =
          (fromAttr && String(fromAttr).trim()) ||
          (nameBtn.title && String(nameBtn.title).trim()) ||
          (nameBtn.textContent && String(nameBtn.textContent).trim()) ||
          "";
        showBuildDesc(desc, nameBtn);
      });
    });
    root.querySelectorAll(".planet-built-step").forEach((stepBtn) => {
      stepBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (stepBtn.disabled) return;
        const card = stepBtn.closest(".planet-built-card");
        if (!card) return;
        const d = Number(stepBtn.getAttribute("data-built-step"));
        builtQtyClamp(card, Number.isFinite(d) ? d : 0);
      });
    });
    root.querySelectorAll(".planet-built-qty-val").forEach((el) => {
      if (el.tagName !== "INPUT") return;
      el.addEventListener("input", () => {
        const card = el.closest(".planet-built-card");
        if (card) syncPlanetBuiltUpgradeCostLine(card);
      });
      el.addEventListener("blur", () => clampPlanetBuiltQtyInput(el));
      el.addEventListener("change", () => clampPlanetBuiltQtyInput(el));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          el.blur();
        }
      });
    });
    root.querySelectorAll(".planet-built-upgrade").forEach((upBtn) => {
      upBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (upBtn.disabled) return;
        const row = upBtn.closest(".planet-built-actions");
        const card = upBtn.closest(".planet-built-card");
        if (!row || !card) return;
        const ids = surfaceGroupIdsFromBtn(row);
        const valEl = card.querySelector(".planet-built-qty-val");
        if (valEl && valEl.tagName === "INPUT") clampPlanetBuiltQtyInput(valEl);
        const n = Math.max(1, Math.min(ids.length, readPlanetBuiltQtyFromCard(card)));
        if (!ids.length) return;
        if (
          n > 1 &&
          !confirm(
            `Улучшить по очереди ${n} построек? У каждого шага списание ресурсов с домашней планеты; при ошибке цикл остановится.`,
          )
        )
          return;
        for (let i = 0; i < n; i++) {
          const id = ids[i];
          if (!id) break;
          setStatus(`Улучшение: ${i + 1} / ${n}…`);
          const ok = await upgradeBuilding(id, { skipUiRefresh: i + 1 < n });
          if (!ok) {
            await refreshPlanetAfterBuildingAction();
            return;
          }
        }
        setStatus(`Готово: улучшено ${n}`, "ok");
        await refreshPlanetAfterBuildingAction();
      });
    });
    root.querySelectorAll(".planet-built-dismantle").forEach((dmBtn) => {
      dmBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const row = dmBtn.closest(".planet-built-actions");
        const card = dmBtn.closest(".planet-built-card");
        if (!row || !card) return;
        const ids = surfaceGroupIdsFromBtn(row);
        const valEl = card.querySelector(".planet-built-qty-val");
        if (valEl && valEl.tagName === "INPUT") clampPlanetBuiltQtyInput(valEl);
        const n = Math.max(1, Math.min(ids.length, readPlanetBuiltQtyFromCard(card)));
        if (!ids.length) return;
        if (
          !confirm(
            `Утилизировать ${n} построек по очереди? Вернётся ~50% стоимости каждой на домашнюю планету.`,
          )
        )
          return;
        for (let i = 0; i < n; i++) {
          const id = ids[i];
          if (!id) break;
          setStatus(`Снос: ${i + 1} / ${n}…`);
          const ok = await dismantleBuilding(id, { skipUiRefresh: i + 1 < n });
          if (!ok) {
            await refreshPlanetAfterBuildingAction();
            return;
          }
        }
        setStatus(`Готово: утилизировано ${n}`, "ok");
        await refreshPlanetAfterBuildingAction();
      });
    });
    root.querySelectorAll(".planet-built-card").forEach((c) => syncPlanetBuiltUpgradeCostLine(c));
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
    for (const btn of root.querySelectorAll("button[data-module-dismantle]")) {
      btn.addEventListener("click", async () => {
        const moduleId = btn.getAttribute("data-module-dismantle");
        if (!moduleId) return;
        await dismantleOutpostModule(moduleId);
      });
    }
  };

  /** Строки карточек строительства: тип, эмодзи, подпись до ответа `placement_checks`. */
  const BUILD_CARD_UI_ROWS = [
    ["mine", "⛏", "Шахта"],
    ["reactor", "⚡", "Реактор"],
    ["fuel_depot", "⛽", "Топливник"],
    ["crystal_farm", "💎", "Кристаллы"],
    ["habitat", "🏠", "Жильё"],
    ["basic_farm", "🌾", "Ферма"],
    ["basic_water", "💦", "Опреснитель"],
    ["research_lab", "🔬", "Лаборатория"],
    ["drydock_mini", "🛠", "Мини-верфь"],
    ["solar_array", "☀", "Солнечная матрица"],
    ["cargo_yard", "📦", "Грузовая"],
    ["sensor_mast", "📡", "Сенсоры"],
    ["hydro_farm", "🍲", "Гидропоника"],
    ["atmospheric_reclaim", "💧", "Конденсатор"],
  ];

  const BUILD_MENU_BUTTON_TYPES = BUILD_CARD_UI_ROWS.map((r) => r[0]);

  const buildingTypeGlyph = (logicalType) => {
    const k = String(resolveBuildingCanonId(logicalType) || logicalType || "").toLowerCase();
    const row = BUILD_CARD_UI_ROWS.find((r) => String(r[0]).toLowerCase() === k);
    return row ? row[1] : "▣";
  };

  const buildingEffectsSummaryRuFromDef = (def) => {
    if (!def || typeof def !== "object") return "—";
    const eff = def.effects && typeof def.effects === "object" ? def.effects : null;
    const prod =
      eff && eff.production_per_sol_add && typeof eff.production_per_sol_add === "object"
        ? eff.production_per_sol_add
        : eff && eff.production_per_tick_add && typeof eff.production_per_tick_add === "object"
          ? eff.production_per_tick_add
          : {};
    const parts = [];
    const add = (key, ru) => {
      const v = Number(prod[key]) || 0;
      if (v === 0) return;
      const sign = v > 0 ? "+" : "";
      parts.push(`${sign}${Math.trunc(v)} ${ru}/сол`);
    };
    add("metal", "металл");
    add("crystal", "кристаллы");
    add("energy", "энергия");
    add("fuel", "топливо");
    add("food", "еда");
    add("water", "вода");
    const maxPop = eff && Number(eff.max_population_add);
    if (Number.isFinite(maxPop) && maxPop !== 0) {
      const sign = maxPop > 0 ? "+" : "";
      parts.push(`${sign}${Math.trunc(maxPop)} насел.`);
    }
    return parts.length ? parts.join(", ") : "—";
  };

  /** Карточка группы одинаковых зданий на планете: имя, эффект, ± количество, «Улучшить» / «Утилизировать». */
  const planetSurfaceGroupRowHtml = (g) => {
    const def = resolveBuildingDef(g.bt) || {};
    const nm = g.grpTitle || buildingSurfaceGroupTitle(def);
    const desc =
      typeof def.description === "string" && def.description.trim() ? def.description.trim() : "";
    const effectsLine = buildingEffectsSummaryRuFromDef(def);
    const glyph = buildingTypeGlyph(g.bt);
    const cnt = g.ids.length;
    if (!cnt) return "";
    const csvEsc = escAttr(g.ids.join(","));
    const hasUp = buildingHasBalanceUpgrade(g.bt);
    const tipFull = [nm, desc && desc !== nm ? desc : "", effectsLine && effectsLine !== "—" ? `Эффект: ${effectsLine}` : ""]
      .filter(Boolean)
      .join("\n");
    const descClick = desc && desc.length ? desc : tipFull;
    const upDis = !hasUp;
    const oneOnly = cnt <= 1;
    const stepDis = oneOnly ? " disabled" : "";
    const upCost = buildingUpgradeCostObj(g.bt);
    const costIcons = formatResourceDictCompactRu(upCost);
    const costEnc =
      !upDis && upCost && typeof upCost === "object"
        ? encodeURIComponent(JSON.stringify(upCost))
        : "";
    const costWrap =
      costEnc !== ""
        ? `<span class="planet-built-cost-wrap" data-per-upgrade-cost="${costEnc}"> · апгрейд ×<span class="planet-built-cost-mul">1</span>: <span class="planet-built-cost-icons">${costIcons || "—"}</span></span>`
        : "";
    const upTitle = upDis
      ? "В балансе нет следующего уровня для этой постройки"
      : costIcons
        ? `Улучшить по очереди (склад дома). За один шаг: ${costIcons}`
        : "Улучшить выбранное число построек по очереди (склад дома)";
    return `<div class="planet-built-card" data-built-max="${cnt}">
      <span class="ic" aria-hidden="true">${glyph}</span>
      <div class="planet-built-main">
        <div class="planet-built-top">
          <button type="button" class="planet-built-name-btn" title="${escAttr(tipFull)}" data-built-desc="${escAttr(descClick)}">${escHtml(nm)}</button>
          <span class="planet-built-meta muted">${escHtml(effectsLine)}</span>
          <div class="planet-built-submeta muted" aria-live="polite">В группе (эта клетка): <b>${cnt}</b>${costWrap}</div>
        </div>
        <div class="planet-built-actions" data-surface-group-ids="${csvEsc}">
          <button type="button" class="planet-built-step" data-built-step="-1"${stepDis} aria-label="Меньше">−</button>
          <input type="number" class="planet-built-qty-val" name="planet_built_qty" min="1" max="${cnt}" step="1" value="1" inputmode="numeric" pattern="[0-9]*" title="Сколько построек затронуть подряд (1–${cnt})" aria-label="Число построек для действия" />
          <button type="button" class="planet-built-step" data-built-step="1"${stepDis} aria-label="Больше">+</button>
          <button type="button" class="btn-primary planet-built-upgrade"${upDis ? " disabled" : ""} title="${escAttr(upTitle)}">Улучшить</button>
          <button type="button" class="btn-secondary planet-built-dismantle" title="Снести выбранное число построек (~50% стоимости на дом за каждую)">Утилизировать</button>
        </div>
      </div>
    </div>`;
  };

  /** Одна постройка вне тайла планеты — та же карточка, количество фиксировано. */
  const planetBuiltSingleOffColonyHtml = (b) => {
    const bid = b && b.id ? String(b.id) : "";
    const bt = b && b.building_type ? String(b.building_type) : "";
    if (!bid) return "";
    const bl = Number(b?.level) || 1;
    const blPart = bl > 1 ? ` <span class="muted">(ур. ${bl})</span>` : "";
    const def = resolveBuildingDef(bt) || {};
    const nm = buildingLabelRu(bt);
    const desc =
      typeof def.description === "string" && def.description.trim() ? def.description.trim() : "";
    const effectsLine = buildingEffectsSummaryRuFromDef(def);
    const glyph = buildingTypeGlyph(bt);
    const blTxt = bl > 1 ? ` (ур. ${bl})` : "";
    const tipFull = [`${nm}${blTxt}`, desc, effectsLine && effectsLine !== "—" ? `Эффект: ${effectsLine}` : ""]
      .filter(Boolean)
      .join("\n");
    const descClick = desc || tipFull;
    const hasUp = buildingHasBalanceUpgrade(bt);
    const upDis = !hasUp;
    const csvEsc = escAttr(bid);
    const upCost = buildingUpgradeCostObj(bt);
    const costIcons = formatResourceDictCompactRu(upCost);
    const costEnc =
      !upDis && upCost && typeof upCost === "object"
        ? encodeURIComponent(JSON.stringify(upCost))
        : "";
    const costWrap =
      costEnc !== ""
        ? `<span class="planet-built-cost-wrap" data-per-upgrade-cost="${costEnc}"> · апгрейд ×<span class="planet-built-cost-mul">1</span>: <span class="planet-built-cost-icons">${costIcons || "—"}</span></span>`
        : "";
    const upTitle = upDis
      ? "В балансе нет следующего уровня для этой постройки"
      : costIcons
        ? `Улучшить постройку (склад дома). Стоимость: ${costIcons}`
        : "Улучшить постройку (склад дома)";
    return `<div class="planet-built-card planet-built-card--single" data-built-max="1">
      <span class="ic" aria-hidden="true">${glyph}</span>
      <div class="planet-built-main">
        <div class="planet-built-top">
          <button type="button" class="planet-built-name-btn" title="${escAttr(tipFull)}" data-built-desc="${escAttr(descClick)}">${escHtml(nm)}${blPart}</button>
          <span class="planet-built-meta muted">${escHtml(effectsLine)}</span>
          <div class="planet-built-submeta muted" aria-live="polite">На клетке: <b>1</b>${costWrap}</div>
        </div>
        <div class="planet-built-actions" data-surface-group-ids="${csvEsc}">
          <button type="button" class="planet-built-step" data-built-step="-1" disabled aria-label="Меньше">−</button>
          <input type="number" class="planet-built-qty-val" name="planet_built_qty" min="1" max="1" step="1" value="1" inputmode="numeric" pattern="[0-9]*" title="Одна постройка на клетке" aria-label="Число построек для действия" />
          <button type="button" class="planet-built-step" data-built-step="1" disabled aria-label="Больше">+</button>
          <button type="button" class="btn-primary planet-built-upgrade"${upDis ? " disabled" : ""} title="${escAttr(upTitle)}">Улучшить</button>
          <button type="button" class="btn-secondary planet-built-dismantle" title="Снести постройку (~50% стоимости на дом)">Утилизировать</button>
        </div>
      </div>
    </div>`;
  };

  const buildCardRowHtml = (bt, glyph, shortLabel, opts = {}) => {
    const sectorField = Boolean(opts.sectorField);
    if (sectorField) {
      return `
    <div class="build-card build-card--sector-field" data-b="${escAttr(String(bt))}">
      <span class="ic" aria-hidden="true">${glyph}</span>
      <div class="build-card-main">
        <div class="build-card-top">
          <button type="button" class="build-card-name-btn" title="">${escHtml(shortLabel)}</button>
          <span class="build-card-meta muted"></span>
        </div>
        <div class="build-card-cost-line muted" aria-live="polite"></div>
        <div class="build-card-actions">
          <button type="button" class="btn-primary build-card-build">Построить</button>
        </div>
      </div>
    </div>`;
    }
    return `
    <div class="build-card" data-b="${escAttr(String(bt))}">
      <span class="ic" aria-hidden="true">${glyph}</span>
      <div class="build-card-main">
        <div class="build-card-top">
          <button type="button" class="build-card-name-btn" title="">${escHtml(shortLabel)}</button>
          <span class="build-card-meta muted"></span>
        </div>
        <div class="build-card-cost-line muted" aria-live="polite"></div>
        <div class="build-card-actions">
          <button type="button" class="build-qty-step" data-d="-1" aria-label="Меньше">−</button>
          <input type="number" class="build-qty-val" name="build_qty" min="1" max="100" step="1" value="1" inputmode="numeric" pattern="[0-9]*" title="Число построек за один запрос (1–100)" aria-label="Число построек" />
          <button type="button" class="build-qty-step" data-d="1" aria-label="Больше">+</button>
          <button type="button" class="btn-primary build-card-build">Построить</button>
        </div>
      </div>
    </div>`;
  };

  const buildButtonsHtml = (opts = {}) => {
    const sectorField = Boolean(opts.sectorField);
    const cards = BUILD_CARD_UI_ROWS.map(([bt, gl, lab]) => buildCardRowHtml(bt, gl, lab, { sectorField })).join("");
    const footer = sectorField
      ? `<div class="planet-build-bulk-row muted" style="margin-top:12px;font-size:90%;">На клетке вне тайла колонии — одна постройка за раз; ресурсы со склада дома (нехватка подсвечена красным).</div>`
      : `<div class="planet-build-bulk-row muted" style="margin-top:12px;font-size:90%;">Число построек за один запрос: «−» / «+», затем «Построить» (до 100, склад дома).</div>`;
    return `
    <div class="build-grid" style="margin-top:10px;">${cards}</div>
    <div id="planet-build-type-desc" class="planet-build-type-desc muted hidden" role="status" aria-live="polite"></div>
    ${footer}
  `;
  };

  /** Типы форпостов в меню полевой стройки — синхронизировать с кнопками `data-outpost`. */
  const OUTPOST_BUILD_MENU_TYPES = ["outpost_t1"];

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

  /** Потребность vs склад дома — тултипы, статус и баннер в модалке. */
  const formatCostVsHaveRuTip = (need, have) => {
    const keys = ["metal", "crystal", "energy", "fuel", "food", "water"];
    const ru = {
      metal: "металл",
      crystal: "кристаллы",
      energy: "энергия",
      fuel: "топливо",
      food: "еда",
      water: "вода",
    };
    const parts = [];
    for (const k of keys) {
      const n = Number(need && need[k]);
      if (!Number.isFinite(n) || n <= 0) continue;
      const h = Number(have && have[k]);
      const hv = Number.isFinite(h) ? h : "?";
      parts.push(`${ru[k] || k}: нужно ${n}, на складе ${hv}`);
    }
    return parts.length ? parts.join("; ") : "Недостаточно ресурсов на складе домашней планеты.";
  };

  /** Человекочитаемое описание ошибки API (без сырых ключей в основном тексте). */
  const formatApiFailure = (body, opts = {}) => {
    if (!body || typeof body !== "object") return "Нет ответа сервера или неверный формат данных.";
    const err = body.error != null ? String(body.error) : "";
    const detail = typeof body.detail === "string" && body.detail.trim() ? body.detail.trim() : "";

    const fmtNum = (v) => {
      const x = Number(v);
      if (!Number.isFinite(x)) return "?";
      if (Math.abs(x - Math.round(x)) < 1e-6) return String(Math.round(x));
      return String(Math.round(x * 100) / 100);
    };

    const needHaveRp = () => {
      const need = body.need;
      const have = body.have;
      return `Недостаточно очков исследований. Нужно: ${fmtNum(need)}, есть: ${fmtNum(have)}`;
    };

    const needHavePair = (needKey, haveKey, ruNeed, ruHave) => {
      const n = body[needKey];
      const h = body[haveKey];
      return `Нужно ${ruNeed}: ${fmtNum(n)}, есть ${ruHave}: ${fmtNum(h)}`;
    };

    const resourcesLine = () => {
      const tip = formatCostVsHaveRuTip(body.need || {}, body.have || {});
      return tip ? `Не хватает ресурсов: ${tip.replace(/; /g, ", ")}` : "Не хватает ресурсов на складе домашней планеты.";
    };

    if (err === "not_enough_research_points") return needHaveRp();
    if (err === "not_enough_resources") return resourcesLine();
    if (err === "not_enough_fuel") return needHavePair("need", "have", "топливо для прыжка", "топливо");
    if (err === "not_enough_fleet_energy") return needHavePair("need", "have", "энергии флота", "энергии");
    if (err === "tech_prereq_missing") {
      const csv = techIdsToRuCsv(body.missing || []);
      return csv ? `Сначала изучите: ${csv}` : "Не выполнены зависимости технологий.";
    }
    if (err === "tech_field_data_missing") {
      const m = Array.isArray(body.missing) ? body.missing.filter(Boolean).map(String) : [];
      return m.length
        ? `Нужны полевые данные: ${m.join(", ")}. Исследуйте руины и аномалии флотом на клетке.`
        : "Нужны полевые данные для этой технологии.";
    }
    if (err === "tech_queue_full")
      return "Уже есть исследование в работе — дождитесь завершения (панель задач в окне исследований).";
    if (err === "tech_already_started") return "Эта технология уже изучена или изучается.";
    if (err === "tech_disabled") return "Технология отключена в конфигурации сервера.";
    if (err === "unknown_tech") return "Неизвестная технология.";
    if (err === "engineer_required" || err === "not_enough_engineers") {
      const ne = body.need_engineers;
      return ne != null && Number.isFinite(Number(ne))
        ? `Для действия на этой клетке нужен ваш флот с инженерами (требуется инженеров: ${fmtNum(ne)}).`
        : "Для действия на этой клетке нужен ваш флот с инженерами (или стройка с клетки своей планеты).";
    }
    if (err === "outpost_too_close") {
      const no = body.nearest_outpost || null;
      const at =
        no && Number.isFinite(Number(no.x)) && Number.isFinite(Number(no.y))
          ? ` (ближайший форпост ${no.x},${no.y},${no.z ?? 0})`
          : "";
      return `Слишком близко к вашему форпосту${at}. Нужно расстояние ≥ ${body.need_distance ?? "?"}, сейчас ${body.nearest ?? "?"}.`;
    }
    if (err === "planet_slots_full") {
      const u = body.built_surface ?? body.built;
      return `На тайле колонии заняты все слоты поверхности (${u ?? "?"}/${body.total ?? "?"}).`;
    }
    if (err === "planet_required") return "Эту постройку можно возводить только в клетке планеты.";
    if (err === "tech_required") {
      const csv = techIdsToRuCsv(body.missing_techs || body.required_techs || []);
      return csv ? `Нужны исследования: ${csv}` : "Не выполнены требования по технологиям.";
    }
    if (err === "wrong_foundation_terrain") {
      const exp = Array.isArray(body.expected) ? body.expected.join(", ") : "—";
      return `Неверное основание: требуется ${exp}, на клетке ${body.terrain || "—"}.`;
    }
    if (err === "inside_enemy_control_zone") return "В клетке с подтверждённым вражеским контролем действие недоступно.";
    if (err === "building_upgrade_unavailable") return "Для этой постройки нет следующего уровня в балансе.";
    if (err === "planet_type_cap") return "Достигнут лимит таких построек на планете.";
    if (err === "module_work_queue_full")
      return "Уже идёт монтаж или улучшение модуля в империи — дождитесь завершения.";
    if (err === "module_busy") return "Этот слот модуля занят или недоступен.";
    if (err === "cell_occupied_by_own_fleet")
      return "В клетке уже стоит другой ваш флот — два флота не могут занимать одну клетку.";
    if (err === "active_order_exists") {
      const h = opts.activeOrderHint && String(opts.activeOrderHint).trim();
      return h
        ? `Флот уже выполняет приказ. ${h} Отмените приказ или дождитесь прибытия.`
        : "Флот уже выполняет приказ — отмените его или дождитесь завершения.";
    }
    if (err === "sector_not_visible") return "Клетка не в зоне обзора ваших флотов и колоний.";
    if (err === "nothing_to_discover") return "Здесь нечего исследовать.";
    if (err === "fleet_required") return "Приведите свой флот на эту клетку, чтобы исследовать руины или аномалию.";
    if (err === "invalid_payload") return "Некорректные данные запроса.";
    if (err === "not_authenticated") return "Сессия истекла — войдите снова.";

    if (detail) return `Операция не выполнена. ${detail}`;
    if (err) return "Операция не выполнена. Попробуйте позже или откройте «Империя» для баланса.";
    return "Операция не выполнена.";
  };

  const refreshPlanetBuildPlacementBanner = (results) => {
    const el = planetModalBody && planetModalBody.querySelector("#planet-build-placement-summary");
    if (!el || !results || typeof results !== "object") return;
    let shortfall = false;
    let slotsFull = false;
    let cellBusy = false;
    for (const bt of BUILD_MENU_BUTTON_TYPES) {
      const res = results[bt];
      if (!res || res.ok) continue;
      if (res.error === "not_enough_resources") shortfall = true;
      if (res.error === "planet_slots_full") slotsFull = true;
      if (res.error === "cell_already_built") cellBusy = true;
    }
    const bits = [];
    if (slotsFull) {
      bits.push(
        `<span class="hud-warn">Поверхность колонии заполнена.</span> Свободных слотов на этом тайле больше нет; полевые постройки на других клетках считаются отдельно.`,
      );
    }
    if (cellBusy) {
      bits.push(
        `<span class="hud-warn">На клетке уже стоит постройка.</span> Вне тайла колонии допускается одна постройка на клетку.`,
      );
    }
    if (shortfall) {
      bits.push(
        `<span class="hud-warn">Не хватает ресурсов на складе дома</span> для части вариантов ниже. Наведите на карточку или имя типа — там «нужно / есть». Включите «Показать все варианты», если список скрыт.`,
      );
    }
    el.innerHTML = bits.join("<br />");
    el.classList.toggle("planet-build-placement-summary--warn", bits.length > 0);
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
      const cards = planetModalBody.querySelectorAll(".build-card[data-b]");
      for (const card of cards) {
        const bt = card.getAttribute("data-b");
        const res = results[bt];
        const showAll = Boolean(showAllBuildOptions);
        const nameBtn = card.querySelector(".build-card-name-btn");
        const metaEl = card.querySelector(".build-card-meta");
        const valEl = card.querySelector(".build-qty-val");
        const buildBtn = card.querySelector(".build-card-build");
        const stepBtns = card.querySelectorAll(".build-qty-step");
        const costLine = card.querySelector(".build-card-cost-line");

        const meta = res && res.meta ? res.meta : null;
        const terrainsRu = meta ? formatAllowedTerrainsShortRu(meta.allowed_terrains) : "";
        const effectsRu = meta && meta.effects_ru ? String(meta.effects_ru) : "";
        const extra = [terrainsRu ? `[${terrainsRu}]` : "", effectsRu && effectsRu !== "—" ? effectsRu : ""]
          .filter(Boolean)
          .join(" ");
        if (metaEl) metaEl.textContent = extra;

        const nm = meta && meta.name ? String(meta.name) : bt;
        const desc = meta && meta.description ? String(meta.description) : "";
        const baseTipParts = [];
        baseTipParts.push(`${nm}${desc ? " — " + desc : ""}`);
        if (effectsRu && effectsRu !== "—") baseTipParts.push(`Эффект: ${effectsRu}`);
        if (terrainsRu) baseTipParts.push(`Террейн: ${terrainsRu}`);
        const baseTip = baseTipParts.filter(Boolean).join("\n");

        if (!showAll && !(res && res.ok)) {
          card.style.display = "none";
        } else {
          card.style.display = "";
        }

        let fullTitle = baseTip;
        if (!(res && res.ok)) {
          const err = res ? res.error : "not_allowed";
          if (err === "wrong_foundation_terrain") {
            const exp = Array.isArray(res.expected) ? res.expected.join(", ") : "—";
            const got = res.terrain ? String(res.terrain) : "—";
            fullTitle = [baseTip, `Нужно основание: ${exp}. Сейчас: ${got}.`].filter(Boolean).join("\n");
          } else if (err === "planet_required") {
            fullTitle = [baseTip, "Можно построить только в клетке планеты."].filter(Boolean).join("\n");
          } else if (err === "tech_required") {
            const missing = Array.isArray(res.missing_techs) ? res.missing_techs.join(", ") : "—";
            fullTitle = [baseTip, `Нужно исследование: ${missing}`].filter(Boolean).join("\n");
          } else if (err === "engineer_required") {
            fullTitle = [baseTip, "Нужен ваш флот с инженерами в этой клетке."].filter(Boolean).join("\n");
          } else if (err === "not_enough_engineers") {
            fullTitle = [baseTip, "Не хватает инженеров в этом флоте."].filter(Boolean).join("\n");
          } else if (err === "inside_enemy_control_zone") {
            fullTitle = [baseTip, "Нельзя: клетка под подтверждённым вражеским контролем."].filter(Boolean).join("\n");
          } else if (err === "not_enough_resources") {
            const tip = formatCostVsHaveRuTip(res.need, res.have);
            fullTitle = [baseTip, tip].filter(Boolean).join("\n");
          } else if (err === "planet_slots_full") {
            fullTitle = [
              baseTip,
              `Слоты поверхности колонии заняты (${res.built_surface ?? res.built ?? "?"}/${res.total ?? "?"}).`,
            ]
              .filter(Boolean)
              .join("\n");
          } else if (err === "cell_already_built") {
            fullTitle = [
              baseTip,
              "На этой клетке уже есть постройка (вне тайла колонии допускается одна постройка на клетку).",
            ]
              .filter(Boolean)
              .join("\n");
          } else if (err === "no_home_planet" || err === "no_resources") {
            fullTitle = [baseTip, "Нет домашней планеты или склада ресурсов для списания."].filter(Boolean).join("\n");
          } else {
            fullTitle = [baseTip, `Нельзя: ${err}`].filter(Boolean).join("\n");
          }
        } else if (res && res.ok && res.build && typeof res.build === "object") {
          const tt = Number(res.build.time_ticks);
          if (Number.isFinite(tt) && tt > 0) {
            const rtp = res.build.ready_at_tick_preview;
            const ct0 = res.build.current_tick;
            const seg = [`Стройка: ${ruSolsCountLabel(tt)} до ввода в строй.`];
            if (rtp != null && ct0 != null) {
              seg.push(`Готовность: сол ${rtp} (сейчас сол ${ct0}).`);
            }
            fullTitle = [fullTitle, seg.join(" ")].filter(Boolean).join("\n");
          }
        }

        card.title = fullTitle;
        if (nameBtn) {
          nameBtn.textContent = nm;
          nameBtn.title = fullTitle;
          const descClick = desc && String(desc).trim() ? String(desc).trim() : fullTitle;
          nameBtn.setAttribute("data-build-desc", descClick);
        }
        const can = res && res.ok;
        if (buildBtn) buildBtn.disabled = !can;
        for (const sb of stepBtns) sb.disabled = !can;
        if (valEl && valEl.tagName === "INPUT") valEl.disabled = !can;
        card.classList.toggle("build-card--cannot", !can);
      }
      lastBuildPlacementResults = results;
      repaintBuildCardCostLines();
      refreshPlanetBuildPlacementBanner(results);
    } catch (_e) {
      // ignore UI-only failures
    }
  };

  const refreshOutpostBuildPlacementBanner = (results) => {
    const el = planetModalBody && planetModalBody.querySelector("#outpost-build-placement-summary");
    if (!el || !results || typeof results !== "object") return;
    let shortfall = false;
    let tooClose = false;
    let noEng = false;
    let tech = false;
    let cellOut = false;
    let cellBld = false;
    for (const ot of OUTPOST_BUILD_MENU_TYPES) {
      const res = results[ot];
      if (!res || res.ok) continue;
      if (res.error === "not_enough_resources") shortfall = true;
      if (res.error === "outpost_too_close") tooClose = true;
      if (res.error === "engineer_required" || res.error === "not_enough_engineers") noEng = true;
      if (res.error === "tech_required") tech = true;
      if (res.error === "cell_already_has_outpost") cellOut = true;
      if (res.error === "cell_already_built") cellBld = true;
    }
    const bits = [];
    if (cellOut) bits.push(`<span class="hud-warn">На клетке уже есть активный форпост.</span>`);
    if (cellBld)
      bits.push(
        `<span class="hud-warn">На клетке уже стоит постройка.</span> Форпост на эту же клетку не ставится.`,
      );
    if (tooClose)
      bits.push(
        `<span class="hud-warn">Слишком близко к вашему другому форпосту.</span> Расшифровка — в подсказке на кнопке «Форпост».`,
      );
    if (noEng)
      bits.push(`<span class="hud-warn">Нужен инженер</span> на выбранном флоте в этой клетке (−1 при постройке).`);
    if (tech) bits.push(`<span class="hud-warn">Не хватает исследований</span> для этого типа форпоста (см. подсказку на кнопке).`);
    if (shortfall)
      bits.push(
        `<span class="hud-warn">Не хватает ресурсов на складе дома</span> для форпоста. Наведите на кнопку — «нужно / есть».`,
      );
    el.innerHTML = bits.join("<br />");
    el.classList.toggle("planet-build-placement-summary--warn", bits.length > 0);
  };

  const updateOutpostBuildButtonsAvailability = async (x, y, z, fleetId) => {
    try {
      if (!planetModalBody) return;
      if (!OUTPOST_BUILD_MENU_TYPES.length) return;
      const r = await fetch("/api/outposts/build_checks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          x,
          y,
          z,
          fleet_id: fleetId,
          outpost_types: OUTPOST_BUILD_MENU_TYPES,
        }),
      });
      if (!r.ok) return;
      const body = await r.json();
      if (!body || !body.ok) return;
      const results = body.results || {};
      const btns = planetModalBody.querySelectorAll("button[data-outpost]");
      for (const btn of btns) {
        const ot = btn.getAttribute("data-outpost");
        const res = results[ot];
        if (!btn.getAttribute("data-label")) btn.setAttribute("data-label", btn.textContent || ot || "");
        const baseLabel = btn.getAttribute("data-label") || ot || "Форпост";
        btn.textContent = baseLabel;

        const tipOk =
          "Построить форпост. Ресурсы списываются с домашней планеты, с выбранного флота — один инженер.";
        if (res && res.ok) {
          btn.disabled = false;
          btn.title = tipOk;
        } else {
          btn.disabled = true;
          const err = res ? res.error : "not_allowed";
          if (err === "tech_required") {
            const missing = Array.isArray(res.missing_techs) ? res.missing_techs.join(", ") : "—";
            btn.title = `Нужны исследования: ${missing}`;
          } else if (err === "engineer_required") {
            btn.title = "Нужен ваш инженерный флот в этой клетке (выберите флот выше).";
          } else if (err === "not_enough_engineers") {
            btn.title = "В выбранном флоте нет инженеров.";
          } else if (err === "outpost_too_close") {
            btn.title = `Слишком близко к вашему форпосту: нужно расстояние ≥ ${res.need_distance ?? "?"}, сейчас ${res.nearest ?? "?"}.`;
          } else if (err === "not_enough_resources") {
            btn.title = formatCostVsHaveRuTip(res.need, res.have);
          } else if (err === "cell_already_has_outpost") {
            btn.title = "На клетке уже стоит активный форпост.";
          } else if (err === "cell_already_built") {
            btn.title = "На клетке уже есть постройка — форпост сюда не ставится.";
          } else if (err === "no_home_planet" || err === "no_resources") {
            btn.title = "Нет домашней планеты или склада для списания.";
          } else {
            btn.title = `Нельзя: ${err}`;
          }
        }
      }
      refreshOutpostBuildPlacementBanner(results);
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

  const OUTPOST_COST_RES_RU = {
    metal: "металл",
    crystal: "кристалл",
    energy: "энергия",
    fuel: "топливо",
    food: "еда",
    water: "вода",
  };

  const formatBalanceCostRuPlain = (cost) => {
    if (!cost || typeof cost !== "object") return "";
    const parts = [];
    for (const k of ["metal", "crystal", "energy", "fuel", "food", "water"]) {
      const v = Number(cost[k]);
      if (Number.isFinite(v) && v > 0) {
        parts.push(`${OUTPOST_COST_RES_RU[k] || k} ${v}`);
      }
    }
    return parts.join(", ");
  };

  const formatUpkeepDeltaPlain = (d) => {
    if (!d || typeof d !== "object") return "";
    const parts = [];
    for (const k of ["metal", "crystal", "energy", "fuel"]) {
      const v = Number(d[k]);
      if (!Number.isFinite(v) || v === 0) continue;
      const lab = OUTPOST_COST_RES_RU[k] || k;
      parts.push(`${lab} ${v > 0 ? "+" : ""}${v}`);
    }
    return parts.join(", ");
  };

  const formatOutpostEffectsSummaryPlain = (eff) => {
    if (!eff || typeof eff !== "object") return "";
    const parts = [];
    const vis = eff.vision;
    if (vis && typeof vis === "object" && Number(vis.radius_add)) {
      parts.push(`обзор +${Number(vis.radius_add)}`);
    }
    const cm = eff.combat;
    if (cm && typeof cm === "object") {
      if (Number(cm.hp_add)) parts.push(`HP +${Number(cm.hp_add)}`);
      if (Number(cm.attack_add)) parts.push(`атака +${Number(cm.attack_add)}`);
      if (Number(cm.defense_add)) parts.push(`защита +${Number(cm.defense_add)}`);
    }
    const upk = eff.upkeep;
    if (upk && typeof upk === "object") {
      for (const [key, delta] of Object.entries(upk)) {
        if (key.endsWith("_add") && Number(delta)) {
          const nk = key.replace(/_add$/, "");
          parts.push(`${OUTPOST_COST_RES_RU[nk] || nk} ${Number(delta) > 0 ? "+" : ""}${delta}/сол`);
        }
      }
    }
    const rf = eff.refuel;
    if (rf && typeof rf === "object" && rf.travel_fuel_discount_pct != null) {
      parts.push(`скидка топлива полёта ${Number(rf.travel_fuel_discount_pct)}%`);
    }
    const sup = eff.supply;
    if (sup && typeof sup === "object" && sup.supply_per_supplier_add != null) {
      parts.push(`снабжение +${sup.supply_per_supplier_add} на снабженца`);
    }
    return parts.join(" · ");
  };

  const rootInstallableOutpostModules = (list) => {
    if (!Array.isArray(list)) return [];
    const toTargets = new Set(
      list.filter((m) => m && m.upgrade && m.upgrade.to).map((m) => String(m.upgrade.to)),
    );
    return list.filter((m) => m && m.id && !toTargets.has(String(m.id)));
  };

  const formatBalanceCostRuHtml = (cost) => {
    if (!cost || typeof cost !== "object") return "";
    const parts = [];
    for (const k of ["metal", "crystal", "energy", "fuel", "food", "water"]) {
      const v = Number(cost[k]);
      if (Number.isFinite(v) && v > 0) {
        const label = OUTPOST_COST_RES_RU[k] || k;
        parts.push(`${label} <b>${v}</b>`);
      }
    }
    return parts.join(" • ");
  };

  /** Расходы форпоста из `outposts` в `/api/balance` + списание инженера (как на сервере). */
  const outpostBuildCostBlockHtml = async (outpostType) => {
    await fetchBalanceCached();
    const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
    if (!bb || !bb.ok || !Array.isArray(bb.outposts)) return "";
    const o = bb.outposts.find((it) => it && String(it.id) === String(outpostType));
    if (!o || typeof o !== "object") return "";
    const cost = o.build && typeof o.build === "object" ? o.build.cost : null;
    const resLine = formatBalanceCostRuHtml(cost);
    const nm = o.name ? String(o.name) : String(outpostType);
    if (!resLine) return "";
    return `
      <div class="muted" style="margin-top:6px;font-size:88%;line-height:1.35;">
        <b>${escHtml(nm)}</b> — со склада домашней планеты: ${resLine}.
      </div>
      <div class="muted" style="margin-top:4px;font-size:88%;">С выбранного флота: <b>−1</b> инженер.</div>
    `;
  };

  const syncHudFleetDetailVisibility = () => {
    const wrap = document.getElementById("hud-fleet-detail");
    if (!wrap) return;
    const onCell =
      selectedCell &&
      Array.isArray(selectedCell.objects) &&
      selectedCell.objects.some(
        (o) => o && o.type === "fleet" && playerId && String(o.owner) === String(playerId),
      );
    const show = !selectedCell || onCell;
    wrap.classList.toggle("hidden", !show);
  };

  const updateSelectedPanel = () => {
    const unit = pickedFleetForHud();
    const isMoving = unit && unit.status === "moving";

    if (!selectedCell) {
      closePlanetModal();
      if (selCoordEl) selCoordEl.textContent = "—";
      if (selTerrainEl) selTerrainEl.textContent = "—";
      if (selBuiltWrapEl) selBuiltWrapEl.classList.add("hidden");
      if (selBuiltEl) selBuiltEl.innerHTML = "";
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
      if (buildBtn) {
        buildBtn.disabled = true;
        buildBtn.classList.remove("hud-btn-blocked");
      }
      if (buildBtnHelp) buildBtnHelp.classList.add("hidden");
      if (discoveryResolveBtn) {
        discoveryHudCellKey = null;
        discoveryResolveBtn.classList.add("hidden");
        discoveryResolveBtn.classList.remove("hud-btn-blocked");
        discoveryResolveBtn.disabled = true;
        discoveryResolveBtn.title = "";
      }
      if (discoveryResolveLabel) discoveryResolveLabel.textContent = "Исследовать";
      if (discoveryResolveHelp) discoveryResolveHelp.classList.add("hidden");
      syncHudFleetDetailVisibility();
      return;
    }

    if (selCoordEl) selCoordEl.textContent = `${selectedCell.x}, ${selectedCell.y}, ${selectedCell.z}`;
    if (selTerrainEl) {
      selTerrainEl.textContent = formatCellContainsRu(selectedCell.terrain, selectedCell.glyph);
    }

    const objs = selectedCell.objects || [];
    const builtHud = formatBuiltHudHtml(objs);
    if (selBuiltWrapEl && selBuiltEl) {
      if (!builtHud) {
        selBuiltWrapEl.classList.add("hidden");
        selBuiltEl.innerHTML = "";
      } else {
        selBuiltWrapEl.classList.remove("hidden");
        selBuiltEl.innerHTML = builtHud;
      }
    }
    if (selObjectsEl) {
      if (objs.length === 0) selObjectsEl.textContent = "нет";
      else {
        const uuidRe = /^[\da-f-]{36}$/i;
        const ownerParenLink = (o) => {
          const oid = o && o.owner ? String(o.owner).trim() : "";
          const oname = o && o.owner_name ? String(o.owner_name) : "";
          if (oid && oname && uuidRe.test(oid)) {
            return ` (<a href="/operator/${escAttr(oid)}" class="chat-player-link sector-owner-link">${escHtml(oname)}</a>)`;
          }
          return oname ? ` (${escHtml(oname)})` : "";
        };
        const buildings = objs.filter((o) => o && o.type === "building");
        const others = objs.filter((o) => !(o && o.type === "building"));
        const fmt = (o) => {
          if (o.type === "planet") {
            return `${escHtml(o.name || "Планета")}${ownerParenLink(o)}`;
          }
          if (o.type === "fleet") {
            const c = o.composition ? formatComposition(o.composition) : "";
            const label = c ? c : `${escHtml(o.unit_type)}×${escHtml(String(o.qty ?? ""))}`;
            const e = Number.isFinite(Number(o.energy)) && Number.isFinite(Number(o.max_energy))
              ? ` • E ${escHtml(String(Number(o.energy)))}/${escHtml(String(Number(o.max_energy)))}`
              : "";
            return `${label}${e}${ownerParenLink(o)}`;
          }
          if (o.type === "outpost") {
            return `${escHtml(o.name || "Форпост")}${ownerParenLink(o)}`;
          }
          if (o.type === "building") {
            const bt = o.building_type ? String(o.building_type) : "постройка";
            return escHtml(buildingLabelRu(bt));
          }
          return escHtml(o.type || "объект");
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
            .map(([k, v]) => `${escHtml(k)}×${escHtml(String(v))}`)
            .join(", ");
          parts.push(`постройки×${escHtml(String(buildings.length))}${top ? ` (${top}${Object.keys(counts).length > 3 ? ", …" : ""})` : ""}`);
        }
        selObjectsEl.innerHTML = parts.join(" • ");
      }
    }

    if (selInfluenceEl) {
      const vis = selectedCell.flags && selectedCell.flags.is_visible;
      if (!vis) selInfluenceEl.textContent = "— (не в обзоре)";
      else selInfluenceEl.innerHTML = formatInfluenceHud(selectedCell.influence, true);
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
      const vis = Boolean(selectedCell.flags && selectedCell.flags.is_visible);
      const ownPlanetHere = objs.some(
        (o) => o && o.type === "planet" && String(o.owner) === String(playerId),
      );
      const engineerFleet = engineerFleetForCell(selectedCell);
      const canBuildHere = Boolean(selectedCell && vis && (ownPlanetHere || engineerFleet));
      const needEngineersHud = Boolean(vis && !ownPlanetHere && !engineerFleet);
      buildBtn.disabled = !canBuildHere;
      buildBtn.classList.toggle("hud-btn-blocked", needEngineersHud);
      buildBtn.title = vis ? "" : "Клетка не в обзоре.";
      if (buildBtnHelp) {
        buildBtnHelp.classList.toggle("hidden", !needEngineersHud);
      }
    }

    if (discoveryResolveBtn && discoveryResolveLabel && discoveryResolveHelp) {
      const vis = selectedCell.flags && selectedCell.flags.is_visible;
      const tr = selectedCell.terrain;
      const dKey = `${selectedCell.x},${selectedCell.y},${selectedCell.z ?? 0}`;
      const onDiscoveryTerrain = Boolean(vis && (tr === "ruins" || tr === "anomaly"));
      if (!onDiscoveryTerrain) {
        discoveryHudCellKey = null;
        discoveryResolveBtn.classList.add("hidden");
        discoveryResolveBtn.classList.remove("hud-btn-blocked");
        discoveryResolveBtn.disabled = true;
        discoveryResolveLabel.textContent = "Исследовать";
        discoveryResolveBtn.title = "";
        discoveryResolveHelp.classList.add("hidden");
      } else {
        const sameHudCell = discoveryHudCellKey === dKey;
        discoveryHudCellKey = dKey;
        // При опросах state/window не гасим кнопку: иначе каждый тик — «Исследовать» до ответа sector и мерцание.
        if (!sameHudCell) {
          discoveryResolveBtn.classList.add("hidden");
          discoveryResolveBtn.disabled = true;
          discoveryResolveLabel.textContent = "Исследовать";
          discoveryResolveBtn.title = "";
          discoveryResolveBtn.classList.remove("hud-btn-blocked");
          discoveryResolveHelp.classList.add("hidden");
        }
        const myGen = ++discoverySectorFetchGen;
        void (async () => {
          try {
            const r = await fetch(
              `/api/world/sector?x=${selectedCell.x}&y=${selectedCell.y}&z=${selectedCell.z ?? 0}`,
            );
            if (!r.ok) return;
            const sec = await r.json();
            if (myGen !== discoverySectorFetchGen) return;
            const d = sec.discovery;
            if (!d) return;
            if (d.can_resolve) {
              discoveryResolveBtn.classList.remove("hud-btn-blocked");
              discoveryResolveHelp.classList.add("hidden");
              discoveryResolveBtn.classList.remove("hidden");
              discoveryResolveBtn.disabled = false;
              discoveryResolveLabel.textContent = "Исследовать";
              discoveryResolveBtn.title = "Исследовать руины или аномалию";
            } else if (d.done) {
              discoveryResolveBtn.classList.remove("hud-btn-blocked");
              discoveryResolveHelp.classList.add("hidden");
              discoveryResolveLabel.textContent = "Исследовано";
              discoveryResolveBtn.classList.remove("hidden");
              discoveryResolveBtn.disabled = true;
              discoveryResolveBtn.title = "";
            } else if (!d.fleet_on_cell && !d.done) {
              discoveryResolveLabel.textContent = "Исследовать";
              discoveryResolveBtn.classList.remove("hidden");
              discoveryResolveBtn.disabled = true;
              discoveryResolveBtn.title = "";
              discoveryResolveBtn.classList.add("hud-btn-blocked");
              discoveryResolveHelp.classList.remove("hidden");
            }
          } catch (_e) {}
        })();
      }
    }
    syncHudFleetDetailVisibility();
  };

  const feedbackPlanetAndHud = (message, kind) => {
    setStatus(message, kind);
    if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, message, kind);
    const pEl = planetModalFeedbackEl();
    if (pEl) showActionFeedback(pEl, message, kind);
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
        const msg = formatApiFailure(body);
        feedbackPlanetAndHud(msg, "err");
        if (body.error === "not_enough_resources") {
          const resHuman = formatCostVsHaveRuTip(body.need || {}, body.have || {});
          const ban = planetModalBody && planetModalBody.querySelector("#planet-build-placement-summary");
          if (ban) {
            ban.innerHTML = `<span class="hud-warn">Не хватает ресурсов.</span> ${resHuman}`;
            ban.classList.add("planet-build-placement-summary--warn");
          }
        }
        return;
      }
      const okMsg = `Построено: «${buildingStatusCaptionRu(body.building?.building_type)}»`;
      feedbackPlanetAndHud(okMsg, "ok");
      recordColonyBuildMilestone(body.building?.building_type || building_type, x, y, z);
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
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const placeBuildingBatch = async (x, y, z, building_type, count, fleetId = null) => {
    setStatus(`Строительство ×${count}…`);
    try {
      const r = await fetch("/api/buildings/place_batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, z, building_type, fleet_id: fleetId, count }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        const msg = formatApiFailure(body);
        feedbackPlanetAndHud(msg, "err");
        if (body.error === "not_enough_resources") {
          const resHuman = formatCostVsHaveRuTip(body.need || {}, body.have || {});
          const ban = planetModalBody && planetModalBody.querySelector("#planet-build-placement-summary");
          if (ban) {
            ban.innerHTML = `<span class="hud-warn">Не хватает ресурсов.</span> ${resHuman}`;
            ban.classList.add("planet-build-placement-summary--warn");
          }
        }
        return;
      }
      const placed = Number(body.placed) || 0;
      const req = Number(body.requested) || count;
      const okMsg =
        placed >= req
          ? `Построено: ${placed}× «${buildingStatusCaptionRu(building_type)}»`
          : `Построено ${placed} из ${req} «${buildingStatusCaptionRu(building_type)}»${body.stopped_early ? " (дальше нельзя или не хватает ресурсов)" : ""}`;
      feedbackPlanetAndHud(okMsg, placed > 0 ? "ok" : "err");
      if (placed > 0) recordColonyBuildMilestone(body.building?.building_type || building_type, x, y, z);
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
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
    feedbackPlanetAndHud(okText, "ok");
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
        const msg = formatApiFailure(body);
        feedbackPlanetAndHud(msg, "err");
        if (body.error === "outpost_too_close") {
          const no = body.nearest_outpost || null;
          if (no && Number.isFinite(Number(no.x)) && Number.isFinite(Number(no.y))) {
            viewCenter = { x: Number(no.x), y: Number(no.y) };
            if (Number.isFinite(Number(no.z))) currentZ = Number(no.z);
            await refreshWindow();
          }
        } else if (body.error === "not_enough_resources") {
          const resHuman = formatCostVsHaveRuTip(body.need || {}, body.have || {});
          const ban = planetModalBody && planetModalBody.querySelector("#outpost-build-placement-summary");
          if (ban) {
            ban.innerHTML = `<span class="hud-warn">Не хватает ресурсов для форпоста.</span> ${resHuman}`;
            ban.classList.add("planet-build-placement-summary--warn");
          }
        }
        return;
      }
      mergeOnboardingMilestones({ exploreOrOutpost: true });
      await handleOutpostResult(body, `Форпост построен: ${body.outpost?.name || outpostType}`);
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return;
      }
      await handleOutpostResult(body, `Форпост улучшен: ${body.outpost?.name || "ok"}`);
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return;
      }
      await handleOutpostResult(body, "Монтаж модуля запущен. Инженеры списаны — дождитесь готовности.");
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return;
      }
      await handleOutpostResult(body, "Улучшение модуля запущено");
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const dismantleOutpostModule = async (moduleId) => {
    if (
      !      confirm(
        "Разобрать модуль? Количество инженеров, соответствующее слоту (1-й / 2-й / 3-й), вернётся на ваш инженерный флот на клетке. Монтаж в процессе снять нельзя.",
      )
    )
      return;
    setStatus("Разбираем модуль...");
    try {
      const r = await fetch("/api/outposts/modules/dismantle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_id: moduleId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return;
      }
      await handleOutpostResult(body, "Модуль разобран");
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const refreshPlanetAfterBuildingAction = async () => {
    await refreshWindow();
    syncSelectedCellFromCurrentWindow();
    await loadWorldState();
    if (selectedCell && planetModalOverlay && !planetModalOverlay.classList.contains("hidden")) {
      await fillPlanetModalFromApi(selectedCell);
    }
    updateSelectedPanel();
  };

  const syncSelectedCellFromCurrentWindow = () => {
    if (!selectedCell || !currentWindow || !currentWindow.cells) return;
    const sx = Number(selectedCell.x);
    const sy = Number(selectedCell.y);
    const sz = selectedCell.z ?? 0;
    for (const row of currentWindow.cells) {
      for (const c of row.row || []) {
        if (Number(c.x) === sx && Number(c.y) === sy && (c.z ?? 0) === sz) {
          selectedCell = { ...c };
          return;
        }
      }
    }
  };

  /** @returns {Promise<boolean>} */
  const upgradeBuilding = async (building_id, opts = {}) => {
    const skipUiRefresh = Boolean(opts.skipUiRefresh);
    setStatus("Улучшение постройки...");
    try {
      const r = await fetch("/api/buildings/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return false;
      }
      feedbackPlanetAndHud(`Улучшено до «${buildingStatusCaptionRu(body.building?.building_type)}»`, "ok");
      if (!skipUiRefresh) await refreshPlanetAfterBuildingAction();
      return true;
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
      return false;
    }
  };

  /** @returns {Promise<boolean>} */
  const dismantleBuilding = async (building_id, opts = {}) => {
    const skipUiRefresh = Boolean(opts.skipUiRefresh);
    setStatus("Снос постройки...");
    try {
      const r = await fetch("/api/buildings/dismantle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        feedbackPlanetAndHud(formatApiFailure(body), "err");
        return false;
      }
      feedbackPlanetAndHud("Постройка снесена (50% стоимости возвращено)", "ok");
      if (!skipUiRefresh) await refreshPlanetAfterBuildingAction();
      return true;
    } catch (_e) {
      feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
      return false;
    }
  };

  const preservePlanetModalDetailsState = () => {
    const openBySummary = {};
    if (!planetModalBody) return openBySummary;
    for (const det of planetModalBody.querySelectorAll("details.game-modal-details")) {
      const sum = det.querySelector(":scope > summary");
      const label = sum ? String(sum.textContent || "").trim().replace(/\s+/g, " ") : "";
      if (label) openBySummary[label] = Boolean(det.open);
    }
    return openBySummary;
  };

  const restorePlanetModalDetailsState = (openBySummary) => {
    if (!planetModalBody || !openBySummary || typeof openBySummary !== "object") return;
    for (const det of planetModalBody.querySelectorAll("details.game-modal-details")) {
      const sum = det.querySelector(":scope > summary");
      const label = sum ? String(sum.textContent || "").trim().replace(/\s+/g, " ") : "";
      if (label && Object.prototype.hasOwnProperty.call(openBySummary, label)) {
        det.open = Boolean(openBySummary[label]);
      }
    }
  };

  const fillPlanetModalFromApi = async (cell) => {
    if (!planetModalBody) return;
    if (
      selectedCell &&
      Number(selectedCell.x) === Number(cell.x) &&
      Number(selectedCell.y) === Number(cell.y) &&
      (selectedCell.z ?? 0) === (cell.z ?? 0)
    ) {
      syncSelectedCellFromCurrentWindow();
    }
    const cellLive =
      selectedCell &&
      Number(selectedCell.x) === Number(cell.x) &&
      Number(selectedCell.y) === Number(cell.y) &&
      (selectedCell.z ?? 0) === (cell.z ?? 0)
        ? selectedCell
        : cell;
    const preservedDetailsOpen = preservePlanetModalDetailsState();
    const x = cellLive.x;
    const y = cellLive.y;
    const z = cellLive.z ?? 0;
    const mapPlanet = (cellLive.objects || []).find((o) => o && o.type === "planet");
    const mapOutpost = (cellLive.objects || []).find((o) => o && o.type === "outpost");

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
      const pOwnId = planetOwn.owner ? String(planetOwn.owner).trim() : "";
      let ownName = "";
      if (planetOwn.owner_name && pOwnId && /^[\da-f-]{36}$/i.test(pOwnId)) {
        ownName = ` • <a href="/operator/${escAttr(pOwnId)}" class="chat-player-link sector-owner-link">${escHtml(String(planetOwn.owner_name))}</a>`;
      } else if (planetOwn.owner_name) {
        ownName = ` • ${escHtml(String(planetOwn.owner_name))}`;
      }
      const cls = d.planet_class ? String(d.planet_class) : "—";
      const fld = d.build_slots && d.build_slots.field_buildings != null ? Number(d.build_slots.field_buildings) : NaN;
      const slotsLine =
        d.build_slots && typeof d.build_slots === "object"
          ? `Слоты поверхности: <b>${Number(d.build_slots.used || 0)}</b> / <b>${Number(d.build_slots.total || 0)}</b>${
              Number.isFinite(fld) && fld > 0
                ? ` <span class="muted">• полевых: <b>${fld}</b></span>`
                : ""
            }`
          : "";
      const supN = Number(d.supplier_count) || 0;
      const supBase = Number(d.supply_base) || 5;
      const supPer = Number(d.supply_per_supplier) || 3;
      const supR = Number(d.supply_radius) || supBase + supPer * supN;

      const flags = cellLive.flags || {};
      const objs = cellLive.objects || [];
      const canBuild = Boolean(flags.zone_build_self) && !Boolean(flags.zone_build_enemy) && Boolean(flags.is_visible);
      const cellBuildings = objs.filter((o) => o && o.type === "building");
      const cellBuilding = cellBuildings[0] || null;
      let planetSurfaceBuildingsActions = "";
      if (cellLive.terrain === "planet" && cellBuildings.length > 0) {
        const catOrder = { food: 0, water: 1, other: 2 };
        const catTitles = { food: "Еда", water: "Вода", other: "Прочее" };
        const grpMap = new Map();
        for (const b of cellBuildings) {
          if (!b || b.type !== "building") continue;
          const bt = b.building_type ? String(b.building_type) : "";
          const bid = b.id ? String(b.id) : "";
          const def = resolveBuildingDef(bt);
          const cat = buildingSurfaceProduceCat(def);
          const canon = resolveBuildingCanonId(bt) || bt.toLowerCase();
          const lvl = Number(b.level) || 1;
          const grpTitle = buildingSurfaceGroupTitle(def);
          const gk = `${cat}|${canon}|${grpTitle}|${lvl}`;
          let g = grpMap.get(gk);
          if (!g) {
            g = { cat, canon, lvl, grpTitle, bt, ids: [] };
            grpMap.set(gk, g);
          }
          if (bid) g.ids.push(bid);
        }
        const groups = Array.from(grpMap.values()).sort((a, b) => {
          const c = catOrder[a.cat] - catOrder[b.cat];
          return c !== 0 ? c : a.grpTitle.localeCompare(b.grpTitle, "ru");
        });
        let prevCat = null;
        const parts = [];
        for (const g of groups) {
          if (g.cat !== prevCat) {
            parts.push(`<div class="planet-build-category-title">${escHtml(catTitles[g.cat] || g.cat)}</div>`);
            prevCat = g.cat;
          }
          parts.push(planetSurfaceGroupRowHtml(g));
        }
        planetSurfaceBuildingsActions = `<div class="planet-built-groups">${parts.join("")}</div>`;
      }

      let buildDetailsInner = "";
      if (!canBuild) {
        buildDetailsInner = "<div class='muted'>Стройка недоступна (вне зоны, туман или зона врага).</div>";
      } else if (cellBuildings.length && cellLive.terrain !== "planet") {
        const b = cellBuilding;
        buildDetailsInner = `<div id="planet-field-built-wrap"><div id="planet-field-build-desc" class="planet-build-type-desc muted hidden" role="status" aria-live="polite"></div>${planetBuiltSingleOffColonyHtml(b)}</div>`;
      } else {
        buildDetailsInner = `
          <div id="planet-build-placement-summary" class="planet-build-placement-summary" aria-live="polite" role="status"></div>
          <label class="row" style="gap:8px;align-items:center;margin:6px 0 0 0;">
            <input type="checkbox" id="show-all-build" name="show_all_build" />
            <span class="muted">Показать все варианты</span>
          </label>
          ${buildButtonsHtml()}
          <div class="muted" style="margin-top:8px;">Ресурс списывается с домашней планеты (имперский склад).</div>`;
      }

      const rg = worldState && worldState.race_growth;
      const canRecruitPop =
        Boolean(rg && rg.no_passive_population_growth) &&
        pOwnId &&
        String(playerId || "").trim() &&
        String(pOwnId) === String(playerId || "").trim();
      const recruitPopHtml = canRecruitPop
        ? `<div class="muted" style="margin-top:10px;font-size:86%;max-width:300px;">Население: только явный набор (еда/вода/металл/кристалл со склада планеты).</div>
            <div class="row" style="gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center;">
              <label class="muted" style="margin:0;">Δ жителей</label>
              <input type="number" id="recruit-pop-amount" name="recruit_pop_amount" min="1" max="500" value="50" style="width:80px;padding:4px 6px;" />
              <button type="button" id="recruit-pop-btn" class="btn-secondary" data-planet-id="${escHtml(String(planetOwn.id || mapPlanet?.id || ""))}">Набор населения</button>
            </div>`
        : "";

      const buildInfo = d.build && typeof d.build === "object" ? d.build : null;
      const buildQ = buildInfo && Array.isArray(buildInfo.queue) ? buildInfo.queue : [];
      const buildActive = buildInfo && buildInfo.active ? String(buildInfo.active) : "";
      const buildCurrentSol =
        buildInfo != null &&
        buildInfo.current_tick != null &&
        Number.isFinite(Number(buildInfo.current_tick))
          ? Number(buildInfo.current_tick)
          : null;
      let buildQueueBlockHtml = "";
      if (!buildQ.length && !buildActive) {
        buildQueueBlockHtml = `<div class="muted" style="margin-top:6px;font-size:82%;">Очередь пуста${
          buildCurrentSol != null ? ` • текущий сол <b>${escHtml(String(buildCurrentSol))}</b>` : ""
        }.</div>`;
      } else {
        const solBit =
          buildCurrentSol != null ? ` • текущий сол <b>${escHtml(String(buildCurrentSol))}</b>` : "";
        const head = `<div style="margin-top:6px;font-size:86%;">В очереди: <b>${escHtml(
          String(buildQ.length),
        )}</b>${buildActive ? ` • первым: <b>${escHtml(buildActive)}</b>` : ""}${solBit}</div>`;
        const items =
          buildQ.length > 0
            ? `<ul style="margin:6px 0 0 18px;padding:0;font-size:84%;line-height:1.4;">${buildQ
                .map((it) => {
                  const btt = escHtml(String((it && it.building_type) || "?"));
                  const rem =
                    it && it.remaining_ticks != null
                      ? Math.max(0, Math.trunc(Number(it.remaining_ticks)))
                      : 0;
                  return `<li>${btt} — ещё ${ruSolsCountLabel(rem)}</li>`;
                })
                .join("")}</ul>`
            : "";
        buildQueueBlockHtml = head + items;
      }

      planetModalBody.innerHTML = `
        <div class="game-modal-grid">
          <div class="game-modal-col game-modal-col--entity">
            <div class="section-title">Колония</div>
            <div><b>${escHtml(planetOwn.name || "Планета")}</b> (${escHtml(String(sector.x))}, ${escHtml(String(sector.y))}, ${escHtml(String(sector.z))})${ownName}</div>
            <div class="muted" style="margin-top:6px;">Содержит: ${formatCellContainsRu(cellLive.terrain, cellLive.glyph)}</div>
            <div style="margin-top:8px;">
              Население: <b>${d.population != null ? escHtml(String(d.population)) : "—"}</b> / <b>${d.max_population != null ? escHtml(String(d.max_population)) : "—"}</b>
            </div>
            ${
              slotsLine
                ? `<div class="muted" style="margin-top:6px;">${slotsLine} • класс: <b>${escHtml(cls)}</b></div>`
                : `<div class="muted" style="margin-top:6px;">Класс: <b>${escHtml(cls)}</b></div>`
            }
            ${unitsNz.length ? `<div class="section-title">Юниты</div>\n            <div>${u}</div>` : ""}
          </div>
          <div class="game-modal-col game-modal-col--state">
            <div class="section-title">Состояние</div>
            <div class="muted" style="margin:0 0 6px;font-size:84%;">Производство и содержание населения за сол</div>
            <div>⛏+<b>${mp}</b> 💎+<b>${cp}</b> ⚡+<b>${ep}</b> ⛽+<b>${fp}</b> 🍲+<b>${fdp}</b> 💧+<b>${wp}</b></div>
            ${
              d.population_vitals
                ? `<div style="margin-top:10px;">🍲 <b>−${escHtml(String(Number(d.population_vitals.food_per_sol ?? 0) || 0))}</b> 💧 <b>−${escHtml(String(Number(d.population_vitals.water_per_sol ?? 0) || 0))}</b> <span class="muted">население</span></div>`
                : ""
            }
            ${
              d.population_vitals
                ? `<div class="muted" style="margin-top:6px;font-size:82%;">Оценка к производству: еда <b>${Math.max(0, (Number(fdp) || 0) - Number(d.population_vitals.food_per_sol || 0))}</b> • вода <b>${Math.max(0, (Number(wp) || 0) - Number(d.population_vitals.water_per_sol || 0))}</b>.</div>`
                : ""
            }
            <div class="section-title">Снабжение</div>
            <div>Снабженцев: <b>${supN}</b> • радиус: <b>${supR}</b> клеток</div>
            <div class="muted" style="margin-top:4px;font-size:82%;">База <b>${supBase}</b> • за снабженца <b>+${supPer}</b>. Чужой флот на L-пути режет линию.</div>
            <div class="section-title">Склад</div>
            <div>⛏${d.resources.metal} 💎${d.resources.crystal} ⚡${d.resources.energy} ⛽${d.resources.fuel ?? 0} 🍲${d.resources.food ?? 0} 💧${d.resources.water ?? 0}</div>
            <div class="section-title">Стройка</div>
            ${buildQueueBlockHtml}
          </div>
          <div class="game-modal-col game-modal-col--actions">
            <div class="game-modal-actions-stack">
              <div id="planet-modal-action-feedback" class="hud-action-feedback hud-action-feedback--in-modal" aria-live="polite" role="status" hidden></div>
              <button type="button" id="hire-supplier-btn" data-planet-id="${escHtml(String(planetOwn.id || mapPlanet?.id || ""))}" class="btn-secondary">Нанять снабженца</button>
              <button type="button" class="btn-primary btn-create-fleet" data-planet-id="${escHtml(String(planetOwn.id || mapPlanet?.id || ""))}">Создать флот…</button>
              ${recruitPopHtml}
            </div>
            ${
              planetSurfaceBuildingsActions
                ? `<details class="game-modal-details game-modal-details--construction">
              <summary class="game-modal-details-summary game-modal-details-summary--construction">Постройки на поверхности · действия</summary>
              <div class="game-modal-details-inner">
                <div class="muted" style="font-size:82%;line-height:1.4;margin:0 0 10px;">Карточка типа: клик по имени — описание; поле числа или «−»/«+» — сколько построек затронуть подряд; строка апгрейда пересчитывается по числу; «Улучшить» / «Утилизировать» — по очереди с домашнего склада.</div>
                <div id="planet-surface-build-desc" class="planet-build-type-desc muted hidden" role="status" aria-live="polite"></div>
                ${planetSurfaceBuildingsActions}
              </div>
            </details>`
                : ""
            }
            <details class="game-modal-details game-modal-details--construction">
              <summary class="game-modal-details-summary game-modal-details-summary--construction">Строительство</summary>
              <div class="game-modal-details-inner">${buildDetailsInner}</div>
            </details>
            <div class="muted" style="font-size:82%;margin-top:4px;">Снабженец — логистика планеты (не юнит на карте).</div>
          </div>
        </div>
      `;

      restorePlanetModalDetailsState(preservedDetailsOpen);

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
          feedbackPlanetAndHud("Найм снабженца…", "info");
          try {
            const r = await fetch("/api/supply/hire_supplier", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ planet_id: plid }),
            });
            const body = await r.json();
            if (!r.ok || !body.ok) {
              const msg =
                body.error === "not_enough_resources"
                  ? "Не хватает ресурсов для найма снабженца."
                  : formatApiFailure(body);
              feedbackPlanetAndHud(msg, "err");
              return;
            }
            const okMsg = `Снабжение: радиус ${body.supply_radius} клеток`;
            feedbackPlanetAndHud(okMsg, "ok");
            await loadWorldState();
            void refreshSupplyHud(selectedCell);
            syncSelectedCellFromCurrentWindow();
            await fillPlanetModalFromApi(selectedCell || cellLive);
          } catch (_e) {
            feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
          }
        });
      }
      const recruitPopBtn = planetModalBody.querySelector("#recruit-pop-btn");
      if (recruitPopBtn) {
        recruitPopBtn.addEventListener("click", async () => {
          const plid = recruitPopBtn.getAttribute("data-planet-id");
          if (!plid) return;
          const inp = planetModalBody.querySelector("#recruit-pop-amount");
          const amt = inp ? Math.max(1, Math.floor(Number(inp.value) || 0)) : 50;
          feedbackPlanetAndHud("Набор населения…", "info");
          try {
            const r = await fetch("/api/world/recruit_population", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ planet_id: plid, amount: amt }),
            });
            const body = await r.json();
            if (!r.ok || !body.ok) {
              feedbackPlanetAndHud(formatApiFailure(body), "err");
              return;
            }
            feedbackPlanetAndHud(
              `Набрано +${body.added} (всего ${body.population}). Списано со склада.`,
              "ok",
            );
            await loadWorldState();
            syncSelectedCellFromCurrentWindow();
            await fillPlanetModalFromApi(selectedCell || cellLive);
          } catch (_e) {
            feedbackPlanetAndHud("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
      await fetchBalanceCached();
      const d = outpostOwn.details;
      const oid = String(outpostOwn.id || "");
      const mods = Array.isArray(d.modules) ? d.modules : [];
      const bb = window.__guardstarBalanceCache && window.__guardstarBalanceCache.body;
      const allBalMods = bb && Array.isArray(bb.outpost_modules) ? bb.outpost_modules : [];
      const installCandidates = rootInstallableOutpostModules(allBalMods);
      const empireBusy = Boolean(d.empire_module_work_busy);

      const vBase = Number(d.vision_base_radius ?? d.vision?.radius ?? 0);
      const vAdd = Number(d.module_bonuses?.vision_radius_add || 0);
      const vTot = Number(d.vision?.radius ?? vBase + vAdd);
      const mb = d.module_bonuses || {};

      let upkeepHtml = "";
      const uBase = d.upkeep_per_tick_base;
      const uDelta = d.upkeep_per_tick_modules_delta;
      const uTot = d.upkeep_per_tick_total;
      if (
        uBase &&
        typeof uBase === "object" &&
        uTot &&
        typeof uTot === "object"
      ) {
        upkeepHtml = `
        <div class="muted" title="Ресурс списывается с домашней планеты (имперский склад).">База форпоста: ${escHtml(formatBalanceCostRuPlain(uBase) || "—")}</div>
        ${
          uDelta && formatUpkeepDeltaPlain(uDelta)
            ? `<div class="muted">Модули: ${escHtml(formatUpkeepDeltaPlain(uDelta))}</div>`
            : ""
        }
        <div>Итого за сол: <b>${escHtml(formatBalanceCostRuPlain(uTot) || "—")}</b></div>`;
      }

      const structure = d.structure_upgrade;
      let structureHtml = "";
      if (structure && oid) {
        const costH = formatBalanceCostRuHtml(structure.cost);
        const miss = Array.isArray(structure.missing_techs) ? structure.missing_techs.join(", ") : "";
        structureHtml = `
        <div class="section-title">Структура</div>
        <div>Цель: <b>${escHtml(String(structure.to_name || structure.to || ""))}</b></div>
        ${
          structure.can_apply
            ? `<div style="margin-top:10px;"><button type="button" class="btn-primary btn-upgrade-build" style="width:100%;max-width:360px;" data-outpost-upgrade="${escHtml(oid)}">Улучшить форпост…</button></div>`
            : `<div class="muted" style="margin-top:6px;">Нужны исследования: <b>${escHtml(miss || "—")}</b></div>`
        }
        ${costH ? `<div class="muted" style="margin-top:6px;">Ресурсы: ${costH}</div>` : ""}<div class="muted" style="margin-top:6px;font-size:84%;">Апгрейд корпуса не требует инженеров на клетке — только ресурсы с домашней планеты.</div>`;
      }

      const moduleRows =
        mods.length === 0
          ? `<div class="muted">Нет установленных модулей.</div>`
          : mods
              .map((m) => {
                const mid = m.id ? String(m.id) : "";
                const st = String(m.status || "active");
                const effAuto = formatOutpostEffectsSummaryPlain(m.effects);
                const descr =
                  m.effects_summary_ru != null &&
                  typeof m.effects_summary_ru === "string" &&
                  m.effects_summary_ru.trim()
                    ? String(m.effects_summary_ru).trim()
                    : effAuto;
                const up = m.upgrade;
                const canUp = Boolean(m.can_upgrade_module) && !empireBusy;
                const miss = Array.isArray(m.upgrade_missing_techs) ? m.upgrade_missing_techs.join(", ") : "";
                let upHint = "";
                if (up) {
                  if (canUp) {
                    const durUp = Number(up.time_ticks) || 1;
                    upHint += `<div class="muted" style="font-size:88%;margin-top:4px;">Улучшение → ${escHtml(String(up.to_name || up.to || ""))} · срок монтажа <b>~${escHtml(String(durUp))}</b> ${escHtml(solWord(durUp))} · инженеров как у слота <b>${escHtml(String(m.need_engineers ?? m.slot_cost_engineers ?? 1))}</b></div>`;
                    if (up.summary_ru) {
                      upHint += `<div style="margin-top:4px;line-height:1.35;font-size:86%;color:rgba(232,226,206,0.92);">${escHtml(String(up.summary_ru))}</div>`;
                    }
                  } else {
                    upHint = `<div class="muted" style="font-size:88%;margin-top:4px;">Улучшение: нужны исследования — ${escHtml(miss)}</div>`;
                    if (!empireBusy && up.summary_ru) {
                      upHint += `<div class="muted" style="margin-top:4px;font-size:84%;">${escHtml(String(up.summary_ru))}</div>`;
                    }
                  }
                }
                const progLine =
                  st === "in_progress"
                    ? (() => {
                        const rem = Number(m.ticks_remaining ?? 0) || 0;
                        const ft = m.finish_tick;
                        const remRu = `${escHtml(String(rem))} ${escHtml(solWord(rem))}`;
                        const solRu =
                          ft != null && ft !== ""
                            ? `до <b>${escHtml(String(ft))}</b>-го сола`
                            : "";
                        return `<div style="margin-top:6px;font-size:88%;color:#e8c37a;line-height:1.35;"><b>Монтаж:</b> осталось ≈ ${remRu}${solRu ? ` (${solRu})` : ""}.</div>`;
                      })()
                    : "";
                const btnDism =
                  mid && st === "active"
                    ? `<button type="button" class="btn-icon-action btn-demolish-build" data-module-dismantle="${escHtml(mid)}" title="Разобрать модуль" aria-label="Разобрать модуль"><span class="ico-recycle" aria-hidden="true">♻</span></button>`
                    : "";
                const btnUpg =
                  mid && up && st === "active" && empireBusy ? (
                    `<button type="button" class="btn-icon-action btn-upgrade-build" disabled title="Дождитесь другого монтажа" aria-label="Улучшить модуль">🔧</button>`
                  ) : mid && up && canUp ? (
                    `<button type="button" class="btn-icon-action btn-upgrade-build" data-module-upgrade="${escHtml(mid)}" title="Улучшить модуль" aria-label="Улучшить модуль">🔧</button>`
                  ) : mid && up ? (
                    `<button type="button" class="btn-icon-action btn-upgrade-build" disabled title="Сначала исследования" aria-label="Улучшить модуль (нужны исследования)">🔧</button>`
                  ) : "";
                const tierL = m.tier != null ? ` <span class="muted">T${Number(m.tier)}</span>` : "";
                const engN = Number(m.need_engineers ?? m.slot_cost_engineers ?? 1) || 1;
                const engLine =
                  st === "in_progress" && !m.pending_module_type
                    ? `<div class="muted" style="font-size:86%;margin-top:4px;">Списано инженеров под этот слот: <b>${engN}</b> · монтаж к новому уровню модуля</div>`
                    : st === "in_progress" && m.pending_module_type
                      ? `<div class="muted" style="font-size:86%;margin-top:4px;">Списано инженеров слота <b>${engN}</b> · апгрейд установки до следующего блока баланса</div>`
                      : `<div class="muted" style="font-size:86%;margin-top:4px;">Слот: инженеры при установке — <b>${engN}</b> (расходуется один раз как «рабочая сила»)</div>`;
                const descrBlock = descr
                  ? `<div style="margin-top:6px;font-size:87%;line-height:1.4;">${escHtml(descr)}</div>`
                  : effAuto
                    ? `<div class="muted" style="font-size:88%;margin-top:6px;">${escHtml(effAuto)}</div>`
                    : "";
                return `<div style="margin-top:10px;padding:10px;border:1px solid rgba(120,140,170,0.35);border-radius:8px;"><div class="row" style="justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;"><div><b>${escHtml(String(m.name || m.module_type))}</b>${tierL}${engLine}${descrBlock}${progLine}${upHint}</div><span class="row" style="gap:6px;flex-shrink:0;">${btnUpg}${btnDism}</span></div></div>`;
              })
              .join("");

      const slotsUsed = Number(d.slots?.used || 0);
      const slotsTotal = Number(d.slots?.total || 0);
      const freeSlots = Math.max(0, slotsTotal - slotsUsed);

      const installBlocks =
        freeSlots <= 0 || !oid || installCandidates.length === 0
          ? ""
          : empireBusy
            ? `<div class="section-title">Установка (свободно слотов: ${freeSlots})</div>
          <div class="muted" style="font-size:88%;line-height:1.4;color:#e8c37a;">Сейчас в империи уже идёт монтаж или апгрейд модуля. Дождитесь завершения (несколько солов), затем ставьте следующий модуль.</div>`
            : `<div class="section-title">Установка (свободно слотов: ${freeSlots})</div>
          <div class="muted" style="margin-bottom:8px;font-size:88%;line-height:1.35;">Нужен инженерный флот на клетке форпоста. Оплачивается только <b>инженерами по номеру слота</b> (1-й слот — 1, 2-й — 2, 3-й — 3). Одновременно в империи — не больше <b>одного</b> монтажа/апгрейда модуля. Ресурсы металла/кристалла за модуль не берутся.</div>
          ${installCandidates
            .map((m) => {
              const mt = m.id ? String(m.id) : "";
              const rawCost = (m.build && m.build.cost) || null;
              const cst =
                rawCost && typeof rawCost === "object" ? formatBalanceCostRuPlain(rawCost) : "";
              const dur = Number((m.build && m.build.time_ticks) ?? 3) || 3;
              const timingRu = `<span class="muted">${cst ? `${escHtml(cst)} · ` : ""}срок установки ~<b>${escHtml(String(dur))}</b> ${escHtml(solWord(dur))}</span>`;
              const descM =
                m.effects_summary_ru != null &&
                typeof m.effects_summary_ru === "string" &&
                m.effects_summary_ru.trim()
                  ? `<div class="muted" style="font-size:84%;margin-top:4px;max-width:520px;line-height:1.35;">${escHtml(String(m.effects_summary_ru).trim())}</div>`
                  : "";
              return `<div style="margin-top:12px;"><div class="row" style="gap:10px;align-items:flex-start;margin-top:4px;flex-wrap:wrap;">
                <button type="button" data-module-install="${escHtml(mt)}" data-outpost-id="${escHtml(oid)}">${escHtml(String(m.name || mt))}</button>
                <span style="font-size:88%;line-height:1.35;">${timingRu}</span></div>${descM}</div>`;
            })
            .join("")}`;

      let supplyCenterHtml = "";
      if (d.supply_line && typeof d.supply_line === "object") {
        const sl = d.supply_line;
        const hubLabel = sl.hub_planet_name
          ? escHtml(String(sl.hub_planet_name))
          : sl.hub_planet_id
            ? `планета <span class="muted">(${escHtml(String(sl.hub_planet_id).slice(0, 8))}…)</span>`
            : "—";
        const lineOk = Boolean(sl.in_supply && sl.route_clear);
        const lineRu = lineOk ? "активна" : "прервана";
        let blk = "";
        if (!lineOk && sl.route_blocked_at && sl.route_blocked_at.x != null && sl.route_blocked_at.y != null) {
          blk = ` • узел (${escHtml(String(sl.route_blocked_at.x))},${escHtml(String(sl.route_blocked_at.y))})`;
        }
        supplyCenterHtml = `
          <div class="section-title">Снабжение</div>
          <div>Хаб: <b>${hubLabel}</b></div>
          <div style="margin-top:6px;">Линия: <b>${lineRu}</b>${blk}</div>
          ${
            lineOk
              ? `<div class="muted" style="margin-top:6px;font-size:88%;line-height:1.35;">За сол с хаба (логистика): 🍲 <b>${Number(sl.food_per_sol || 0)}</b> 💧 <b>${Number(sl.water_per_sol || 0)}</b>. При нехватке еды/воды на планете-хабе форпост может отключиться.</div>`
              : `<div class="muted" style="margin-top:6px;font-size:88%;line-height:1.35;">Поставки по маршруту не идут — восстановите линию (радиус снабжения и чужие корабли на L-пути).</div>`
          }
          ${
            !lineOk
              ? `<div style="margin-top:10px;color:#e88;font-size:90%;"><b>Внимание:</b> при длительных сбоях форпост отключается, как при неоплатимом содержании.</div>`
              : ""
          }`;
      } else if ((cellLive.z ?? 0) === 0) {
        supplyCenterHtml = `<div class="section-title">Снабжение</div><div class="muted" style="font-size:88%;">Для этой клетки отдельная линия с хабом не считается (например, зона домашней планеты).</div>`;
      }

      planetModalBody.innerHTML = `
        <div class="game-modal-grid">
          <div class="game-modal-col game-modal-col--entity">
            <div class="section-title">Форпост</div>
            <div><b>${escHtml(String(d.name || "Форпост"))}</b> (${x}, ${y}, ${z})</div>
            <div class="muted" style="margin-top:6px;">Статус: ${escHtml(String(d.status || "active"))} • тип: ${escHtml(String(d.outpost_type || ""))} • уровень: <b>${Number(d.level) || 1}</b></div>
            <div class="section-title">Территория и обзор</div>
            <div>Влияние: <b>${Number(d.territory?.influence_strength || 0)}</b> • радиус: <b>${Number(d.territory?.influence_radius || 0)}</b></div>
            <div>Обзор: база <b>${vBase}</b>${vAdd ? ` • модули <b>+${vAdd}</b>` : ""} • всего <b>${vTot}</b></div>
            <div class="section-title">Бой</div>
            <div>
              HP <b>${Number(d.combat?.hp || 0)}</b>${Number(mb.hp_add) ? ` <span class="muted">(+${Number(mb.hp_add)})</span>` : ""}
              • урон <b>${Number(d.combat?.attack || 0)}</b>${Number(mb.attack_add) ? ` <span class="muted">(+${Number(mb.attack_add)})</span>` : ""}
              • защита <b>${Number(d.combat?.defense || 0)}</b>${Number(mb.defense_add) ? ` <span class="muted">(+${Number(mb.defense_add)})</span>` : ""}
            </div>
            <div class="section-title">Слоты модулей</div>
            <div>Занято <b>${slotsUsed}</b> / <b>${slotsTotal}</b></div>
          </div>
          <div class="game-modal-col game-modal-col--state">
            <div class="section-title">Состояние</div>
            ${upkeepHtml ? `<div class="section-title" style="margin-top:0;font-size:0.85rem;">Содержание (за сол)</div>${upkeepHtml}` : ""}
            ${supplyCenterHtml}
          </div>
          <div class="game-modal-col game-modal-col--actions">
            <div id="planet-modal-action-feedback" class="hud-action-feedback hud-action-feedback--in-modal" aria-live="polite" role="status" hidden></div>
            ${structureHtml}
            ${
              moduleRows
                ? `<details class="game-modal-details">
              <summary class="game-modal-details-summary">Установленные модули</summary>
              <div class="game-modal-details-inner">${moduleRows}</div>
            </details>`
                : ""
            }
            <details class="game-modal-details">
              <summary class="game-modal-details-summary">Установить модуль…</summary>
              <div class="game-modal-details-inner">${
                installBlocks || `<span class="muted">Нет доступных установок (слоты или баланс).</span>`
              }</div>
            </details>
          </div>
        </div>
      `;
      bindOutpostButtons(planetModalBody, { x, y, z, fleetId: null });
      return;
    }

    if (mapPlanet) {
      const moid = mapPlanet.owner ? String(mapPlanet.owner).trim() : "";
      let ownerInner;
      if (mapPlanet.owner_name && moid && /^[\da-f-]{36}$/i.test(moid)) {
        ownerInner = `<a href="/operator/${escAttr(moid)}" class="chat-player-link sector-owner-link">${escHtml(String(mapPlanet.owner_name))}</a>`;
      } else if (mapPlanet.owner_name) {
        ownerInner = `<b>${escHtml(String(mapPlanet.owner_name))}</b>`;
      } else if (mapPlanet.owner) {
        ownerInner = `<b>${escHtml(String(mapPlanet.owner))}</b>`;
      } else {
        ownerInner = "—";
      }
      planetModalBody.innerHTML = `
        <div class="section-title">Объект</div>
        <div><b>${escHtml(mapPlanet.name || "Планета")}</b> (${escHtml(String(x))}, ${escHtml(String(y))}, ${escHtml(String(z))})</div>
        <div>Владелец: ${ownerInner}</div>
        <div class="muted" style="margin-top:10px;">Детальное производство и стройка доступны только для ваших планет.</div>
      `;
      return;
    }

    const engFleets = engineerFleetsForCell(cellLive);
    const fleetBuilder = engFleets[0] || null;
    const buildingHere = (cellLive.objects || []).find((o) => o && o.type === "building");
    const outpostHere = (cellLive.objects || []).find((o) => o && o.type === "outpost");
    if (fleetBuilder) {
      const fleetLabel = fleetBuilder.name && String(fleetBuilder.name).trim() ? String(fleetBuilder.name).trim() : "Флот";
      const engineerQty = Number(fleetBuilder.composition?.engineer || 0);
      let engineerPickHtml = "";
      if (engFleets.length > 1) {
        engineerPickHtml = `
          <div class="muted" style="margin:10px 0 4px;font-size:90%;"><b>Инженерный флот</b> (на клетке несколько — выберите, с кого списывать инженера):</div>
          <select id="sector-builder-fleet" name="sector_builder_fleet" style="width:100%;max-width:440px;padding:6px 8px;margin-bottom:4px;">
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
      const outpostHereOwned =
        outpostHere &&
        playerId &&
        outpostHere.owner &&
        String(outpostHere.owner) === String(playerId);
      if (outpostHereOwned) {
        buildHtml = `<div class="muted" style="line-height:1.4;"><b>Ваш форпост</b> на этой клетке — выберите клетку (или откройте объект на карте), чтобы увидеть модули, содержание и улучшения. Это же окно открывается при выборе клетки с вашим форпостом.</div>`;
      } else if (outpostHere) {
        buildHtml = (() => {
          const ooid = outpostHere.owner ? String(outpostHere.owner).trim() : "";
          const onm = outpostHere.owner_name ? String(outpostHere.owner_name) : "";
          let ownBit = "";
          if (onm && ooid && /^[\da-f-]{36}$/i.test(ooid)) {
            ownBit = ` (<a href="/operator/${escAttr(ooid)}" class="chat-player-link sector-owner-link">${escHtml(onm)}</a>)`;
          } else if (onm) {
            ownBit = ` (${escHtml(onm)})`;
          }
          return `<div>На клетке уже стоит <b>${escHtml(outpostHere.name || "форпост")}</b>${ownBit}.</div>`;
        })();
      } else if (buildingHere) {
        buildHtml = `<div>На клетке уже стоит <b>${escHtml(buildingLabelRu(buildingHere.building_type || "постройка"))}</b>.</div>`;
      } else {
        const outpostCostHtml = await outpostBuildCostBlockHtml("outpost_t1");
        buildHtml = `
          <div id="planet-build-placement-summary" class="planet-build-placement-summary" aria-live="polite" role="status"></div>
          <div id="outpost-build-placement-summary" class="planet-build-placement-summary" aria-live="polite" role="status"></div>
          <div class="section-title">Форпосты</div>
          ${outpostButtonsHtml()}
          ${outpostCostHtml}
          <div class="muted" style="margin-top:8px;">Форпосты дают влияние, обзор, слоты модулей и базовую оборону.</div>
          <div class="section-title">Обычные постройки</div>
          ${buildButtonsHtml({ sectorField: true })}
          <div class="muted" style="margin-top:8px;">Строит выбранный флот с инженерами; ресурсы списываются с домашней планеты.</div>
        `;
      }
      planetModalBody.innerHTML = `
        <div class="section-title">Строительство в секторе</div>
        <div><b>${fleetLabel}</b> (${x}, ${y}, ${z})</div>
        ${engineerPickHtml}
        <div class="muted" style="margin-top:6px;">Инженеров в выбранном флоте: <b>${engineerQty}</b></div>
        <div class="muted" style="margin-top:6px;">Содержит: ${formatCellContainsRu(cellLive.terrain, cellLive.glyph)}</div>
        ${buildHtml}
      `;
      restorePlanetModalDetailsState(preservedDetailsOpen);
      const defaultBid = fleetBuilder.id || null;
      bindBuildButtons(planetModalBody, x, y, z, defaultBid);
      bindOutpostButtons(planetModalBody, { x, y, z, fleetId: defaultBid });
      const selEng = planetModalBody.querySelector("#sector-builder-fleet");
      const runPlacementChecks = async () => {
        const fid = selEng && selEng.value ? String(selEng.value) : defaultBid;
        await updateBuildButtonsAvailability(x, y, z, fid);
        await updateOutpostBuildButtonsAvailability(x, y, z, fid);
      };
      if (selEng) selEng.addEventListener("change", () => void runPlacementChecks());
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
            <input type="number" class="fleet-create-qty-input" id="fleet-create-qty-${escAttr(k)}" name="fleet_create_qty_${k}" data-u="${k}" min="0" max="99999" step="1" value="${q}" style="width:80px;padding:6px 8px;" />
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
        <input type="text" class="fleet-create-name" id="fleet-create-name" name="fleet_create_name" maxlength="64" value="${escHtml(nmVal)}" style="flex:1;min-width:140px;padding:6px 8px;" placeholder="Alpha (Альфа)…" />
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
          showFleetActionMessage("Добавьте хотя бы один корабль", "err");
          return;
        }
        showFleetActionMessage("Создание флота…", "info");
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
            showFleetActionMessage(formatApiFailure(body), "err");
            return;
          }
          activeFleetId = body.fleet_id || activeFleetId;
          showFleetActionMessage(
            `Флот создан: ${body.name || ""} @ (${body.pos?.x},${body.pos?.y})`,
            "ok",
          );
          closeFleetCreateModal();
          await refreshWindow();
          await loadWorldState();
          if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
        } catch (_e) {
          showFleetActionMessage("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
      showFleetActionMessage("Введите имя флота", "err");
      return;
    }
    const total = Object.values(composition || {}).reduce(
      (s, v) => s + Math.max(0, Math.floor(Number(v) || 0)),
      0
    );
    if (total < 1) {
      showFleetActionMessage("В сумме должно быть хотя бы один корабль (или расформируйте флот).", "err");
      return;
    }
    showFleetActionMessage("Сохранение флота…", "info");
    try {
      const r = await fetch("/api/fleets/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId, name, composition }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        showFleetActionMessage(formatApiFailure(body), "err");
        return;
      }
      const net = body.cost_net;
      if (net && (net.metal || net.crystal || net.energy || net.fuel)) {
        showFleetActionMessage(
          `Сохранено. Изменение склада (Δ металл/кристалл/энергия/топливо): ${-net.metal}/${-net.crystal}/${-net.energy}/${-net.fuel}`,
          "ok",
        );
      } else {
        showFleetActionMessage("Сохранено", "ok");
      }
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      showFleetActionMessage("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const disbandFleetApi = async (fleetId) => {
    showFleetActionMessage("Расформирование…", "info");
    try {
      const r = await fetch("/api/fleets/disband", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        showFleetActionMessage(formatApiFailure(body), "err");
        return;
      }
      showFleetActionMessage("Флот расформирован, ресурсы частично возвращены на домашнюю планету.", "ok");
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      const ownedAfter = (Array.isArray(worldState.fleets) ? worldState.fleets : []).filter((x) => x && x.id);
      activeFleetId = ownedAfter[0] ? ownedAfter[0].id : null;
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      showFleetActionMessage("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const mergeFleetsApi = async (targetFleetId, sourceFleetId) => {
    showFleetActionMessage("Слияние флотов…", "info");
    try {
      const r = await fetch("/api/fleets/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_fleet_id: targetFleetId, source_fleet_id: sourceFleetId }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        showFleetActionMessage(formatApiFailure(body), "err");
        return;
      }
      showFleetActionMessage("Флоты объединены", "ok");
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      showFleetActionMessage("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
    }
  };

  const splitFleetApi = async (fleetId, take) => {
    showFleetActionMessage("Разделение флота…", "info");
    try {
      const r = await fetch("/api/fleets/split", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleet_id: fleetId, take }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        showFleetActionMessage(formatApiFailure(body), "err");
        return;
      }
      showFleetActionMessage(`Создан новый флот (${body.new_fleet_id || ""})`, "ok");
      if (body.new_fleet_id) activeFleetId = body.new_fleet_id;
      closeFleetSubModal();
      closeFleetModal();
      await loadWorldState();
      await refreshWindow();
      if (fleetSelectEl && activeFleetId) fleetSelectEl.value = activeFleetId;
    } catch (_e) {
      showFleetActionMessage("Нет связи с сервером. Проверьте сеть и попробуйте снова.", "err");
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
          : "Характеристики и цена набора задаются правилами мира; итоговый состав проверяется на сервере при сохранении.";
      const roleStr = escHtml(fleetUnitRolePurposeRu(k));
      return `
        <div class="fleet-ship-slot" data-unit-card="${escHtml(k)}">
          <div class="fleet-ship-slot-row">
            <details class="fleet-ship-acc">
              <summary class="fleet-ship-acc-sum">
                <span class="fleet-ship-glyph" aria-hidden="true">${gl}</span>
                <span class="fleet-ship-sum-text"><strong>${escHtml(lab)}</strong> <span class="muted">×${escHtml(String(q))}</span></span>
              </summary>
              <div class="fleet-ship-acc-body">
                <div class="fleet-ship-role-line muted">${roleStr}</div>
                <div class="fleet-ship-meta">Цена 1 шт: ${escHtml(costLine)}</div>
                <div class="fleet-ship-meta">HP ${escHtml(String(hp))} · урон ${escHtml(String(dmg))} · клеток/сол ${escHtml(String(spd))} · топл./клетку ${escHtml(String(fu))}</div>
                <div class="fleet-ship-desc">${desc}</div>
              </div>
            </details>
            <div class="fleet-ship-qty">
              <button type="button" class="fleet-qty-step" data-u="${escHtml(k)}" data-s="-1" ${dis}>−</button>
              <input type="number" class="fleet-qty-input" id="fleet-qty-${escAttr(String(f.id))}--${escAttr(String(k))}" name="fleet_qty_${k}" data-u="${escHtml(k)}" min="0" max="99999" step="1" value="${q}" ${blocked ? "disabled" : ""}/>
              <button type="button" class="fleet-qty-step" data-u="${escHtml(k)}" data-s="1" ${dis}>+</button>
            </div>
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
      <div class="game-modal-grid">
        <div class="game-modal-col game-modal-col--entity">
          <div class="section-title">Флот</div>
          <div><b>${escHtml(fn)}</b></div>
          <div class="muted" style="margin-top:6px;">Клетка: (${escHtml(String(f.x))}, ${escHtml(String(f.y))}, ${escHtml(String(f.z ?? 0))})</div>
          <div style="margin-top:10px;">Статус: <b>${escHtml(ruFleetStatus(f.status))}</b></div>
          ${blocked ? `<div style="margin-top:10px;color:#e88;"><b>В пути</b> — состав, слияние и разделение недоступны.</div>` : ""}
          <div class="section-title">Сводка состава</div>
          <div class="muted" style="font-size:88%;line-height:1.4;">${escHtml(formatComposition(f.composition) || "нет кораблей")}</div>
          <div class="section-title">Содержание (за сол)</div>
          <div id="fleet-upkeep-preview" class="fleet-upkeep-core" style="min-height:2em;">Загрузка…</div>
          <div class="muted" style="margin-top:10px;font-size:82%;line-height:1.35;">
            Изменение кораблей списывается с домашней планеты; при распуске части состава возможен частичный возврат (~50%). Сохранение — по кнопке «Сохранить».
          </div>
        </div>
        <div class="game-modal-col game-modal-col--state">
          <div class="section-title">Корабли</div>
          <p class="muted" style="margin:0 0 10px;font-size:82%;">Чтобы открыть роль и характеристики корпуса, нажмите на строку с названием.</p>
          ${roleSection(byRole.recon, "Разведка")}
          ${roleSection(byRole.combat, "Боевой состав")}
          ${roleSection(byRole.tech, "Техника и логистика")}
        </div>
        <div class="game-modal-col game-modal-col--actions">
          <div class="fleet-modal-name-block">
            <label class="muted" style="margin:0 0 4px;font-size:90%;display:block;"><b>Имя флота</b></label>
            <input type="text" class="fleet-rename-input" id="fleet-rename-${escAttr(String(f.id))}" name="fleet_rename" maxlength="64" value="${escHtml(fn)}" ${blocked ? "disabled" : ""} />
          </div>
          <div class="game-modal-actions-stack fleet-modal-primary-actions">
            <button type="button" class="fleet-modal-save btn-primary" ${dis}>Сохранить</button>
            <button type="button" class="fleet-locate-this btn-secondary" title="Показать на карте и выделить">На карте</button>
          </div>
          <div class="fleet-modal-actions-muted" style="margin-top:12px;display:flex;flex-direction:column;gap:8px;">
            <button type="button" class="btn-secondary fleet-open-merge" ${dis}>Слить другой флот сюда…</button>
            <button type="button" class="btn-secondary fleet-open-split" ${dis}>Разделить флот…</button>
            <button type="button" class="btn-secondary fleet-open-disband" ${dis}>Расформировать этот флот…</button>
          </div>
        </div>
      </div>
    `;

    const upKeeEl = fleetModalBody.querySelector("#fleet-upkeep-preview");
    if (upKeeEl) {
      void (async () => {
        try {
          const r = await fetch(`/api/fleets/${encodeURIComponent(String(f.id))}/upkeep-preview`);
          const b = await r.json();
          if (!r.ok || !b.ok) {
            upKeeEl.innerHTML = `<span class="muted">Расход за сол не удалось загрузить.</span>`;
            return;
          }
          const esp = b.empire_supply_per_sol || {};
          const en = Number(b.energy_upkeep_per_sol) || 0;
          const fe = Number(b.fleet_energy_current);
          const pen = Number(b.energy_penalty_on_unpaid_maintenance) || 0;
          const penTitle =
            pen > 0
              ? `Если на складе столицы не хватает металла, кристаллов, еды или воды на снабжение этого флота, с борта списывается штраф: ${pen} ⚡ за сол.`
              : "";
          upKeeEl.innerHTML = `
            <div class="fleet-upkeep-line">⚡ Борт: <b>−${escHtml(String(en))}</b> / сол</div>
            <div class="fleet-upkeep-line" style="margin-top:8px;">Со склада столицы: ⛏ <b>${escHtml(String(esp.metal ?? 0))}</b> 💎 <b>${escHtml(String(esp.crystal ?? 0))}</b> 🍲 <b>${escHtml(String(esp.food ?? 0))}</b> 💧 <b>${escHtml(String(esp.water ?? 0))}</b> <span class="muted">/ сол</span></div>
            ${
              en > 0 && Number.isFinite(fe)
                ? `<div class="fleet-upkeep-line" style="margin-top:8px;">Автономность: <b>~${escHtml(String(Math.floor(fe / en)))}</b> ${escHtml(solWord(Math.floor(fe / en)))} <span class="muted">(энергия на корпус)</span></div>`
                : ""
            }
            ${
              pen > 0
                ? `<div class="muted" style="margin-top:8px;font-size:80%;" title="${escHtml(penTitle)}">Штраф при нехватке снабжения со столицы: ${escHtml(String(pen))} ⚡/сол</div>`
                : ""
            }`;
        } catch (_e) {
          upKeeEl.innerHTML = `<span class="muted">Расход за сол недоступен.</span>`;
        }
      })();
    }

    const readCompositionFromInputs = () => {
      const o = {};
      for (const k of qtyKeys) {
        const inp = fleetModalBody.querySelector(`input.fleet-qty-input[data-u="${k}"]`);
        o[k] = inp ? Math.max(0, Math.floor(Number(inp.value) || 0)) : 0;
      }
      return o;
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
            <select id="fleet-merge-sub-sel" name="fleet_merge_source" style="width:100%;padding:6px 8px;">${mergeOpts}</select>`,
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
              <input type="number" class="fleet-split-qty" id="fleet-split-qty-${escAttr(String(f.id))}--${escAttr(String(k))}" name="fleet_split_qty_${k}" data-u="${escHtml(k)}" min="0" max="99999" value="0" style="width:80px;padding:6px 8px;" ${blocked ? "disabled" : ""}/>
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

  const RESOURCE_TOPBAR_KEYS = [
    "metal",
    "crystal",
    "energy",
    "fuel",
    "food",
    "water",
  ];

  const syncTopbarResourceDrain = (economyBlock) => {
    const bar = document.getElementById("resources-chip");
    if (!bar) return;
    const rawNet =
      economyBlock &&
      typeof economyBlock === "object" &&
      typeof economyBlock.net_per_sol === "object" &&
      economyBlock.net_per_sol
        ? economyBlock.net_per_sol
        : null;
    const drainNote =
      " За сол расход по складу больше прироста. Подробности — в разделе «Империя».";
    for (const key of RESOURCE_TOPBAR_KEYS) {
      const chip = bar.querySelector(`.res-chip[data-res="${key}"]`);
      if (!chip) continue;
      let drain = false;
      if (rawNet && Object.prototype.hasOwnProperty.call(rawNet, key)) {
        const n = Number(rawNet[key]);
        drain = Number.isFinite(n) && n < 0;
      }
      chip.classList.toggle("res-chip--drain", drain);
      const mark = chip.querySelector(".res-drain-marker");
      if (mark) mark.toggleAttribute("hidden", !drain);
      const base =
        chip.getAttribute("data-res-title-base") ||
        chip.getAttribute("title") ||
        (key === "metal"
          ? "Металл"
          : key === "crystal"
            ? "Кристаллы"
            : key === "energy"
              ? "Энергия"
              : key === "fuel"
                ? "Топливо"
                : key === "food"
                  ? "Еда"
                  : key === "water"
                    ? "Вода"
                    : key);
      const full = drain ? `${base}.${drainNote}` : base;
      chip.title = full;
      chip.setAttribute("aria-label", full);
    }
  };

  function renderOnboardingGoals() {
    if (!onboardingGoalsBodyEl) return;
    const m = readOnboardingMilestones();
    const goals = [
      {
        text: "Откройте «Империя» и посмотрите баланс ресурсов за сол (нетто и производство).",
        done: Boolean(m.empireOpened),
      },
      {
        text: "В «Исследованиях» запустите в очередь хотя бы одну технологию.",
        done: Boolean(m.techQueued),
      },
      {
        text: "На карте: исследуйте руины/аномалию или поставьте форпост вне дома.",
        done: Boolean(m.exploreOrOutpost),
      },
    ];
    const allDone = goals.every((g) => g.done);
    if (onboardingGoalsSectionEl) onboardingGoalsSectionEl.classList.toggle("hidden", allDone);
    onboardingGoalsBodyEl.innerHTML = goals
      .map(
        (g) =>
          `<div class="onboarding-goal-line${g.done ? " done" : ""}"><span aria-hidden="true">${g.done ? "✔" : "○"}</span><span>${escHtml(g.text)}</span></div>`,
      )
      .join("");
  }

  const loadWorldState = async () => {
    try {
      const r = await fetch("/api/world/state");
      if (!r.ok) return;
      const body = await r.json();
      worldState = body || worldState;
      if (body && body.player_id) worldState.player_id = body.player_id;
      if (body) {
        const wasAdmin = playerIsGameAdmin;
        playerIsGameAdmin = Boolean(body.is_game_admin);
        playerIsGameModerator = Boolean(body.is_game_moderator);
        if (uiAdminFogWrap) uiAdminFogWrap.classList.toggle("hidden", !playerIsGameAdmin);
        if (wasAdmin && !playerIsGameAdmin) {
          const s = { ...loadUiSettings(), revealFogAdmin: false };
          saveUiSettings(s);
          if (uiRevealFogAdmin) uiRevealFogAdmin.checked = false;
        }
      }
      if (tickEl) tickEl.textContent = String(body.current_sol ?? body.current_tick ?? 0);
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
          const rw = body.research && typeof body.research === "object" ? body.research : {};
          const inProg = Boolean(rw.in_progress);
          const pctRaw = Number(rw.progress_percent);
          const fmtRpTop = (v) => {
            const n = Number(v);
            if (!Number.isFinite(n)) return "—";
            return String(Number(n.toFixed(2)));
          };
          if (rp != null && Number.isFinite(Number(rp))) {
            const main = fmtRpTop(rp);
            const pctOk = inProg && Number.isFinite(pctRaw);
            const line = pctOk ? `${main} (${Math.round(pctRaw)}%)` : main;
            topRpEl.textContent = line;
            const rppNum = Number(rpp);
            const tipBits = [`RP: ${main}`];
            if (pctOk)
              tipBits.push(`текущее исследование: ~${Math.round(pctRaw)}% готово (доля этого теха, не «всех сразу»)`);
            else if (inProg) tipBits.push("идёт исследование");
            if (rpp != null && Number.isFinite(rppNum))
              tipBits.push(`прирост +${Number(rppNum.toFixed(4))} за сол`);
            const tip = tipBits.join(" · ");
            if (topRpChipEl) {
              topRpChipEl.title = tip;
              topRpChipEl.setAttribute("aria-label", `Очки исследований. ${tip}. Справка в вики`);
              topRpChipEl.classList.toggle("res-chip-rp-idle", !inProg);
            }
          } else {
            topRpEl.textContent = "—";
            if (topRpChipEl) {
              topRpChipEl.title = topRpChipEl.getAttribute("data-res-title-base") || "";
              topRpChipEl.setAttribute(
                "aria-label",
                topRpChipEl.getAttribute("data-res-title-base") || "Очки исследований",
              );
              topRpChipEl.classList.add("res-chip-rp-idle");
            }
          }
        }
      }
      if (body) syncTopbarResourceDrain(body.economy || null);
      try {
        await fetchBalanceCached();
      } catch (_e) {
        /* не блокируем сол, ресурсы и события из-за сети/JSON у /api/balance */
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

      syncSystemToastsFromEvents(body.events || []);
      renderEvents(body.events);
      renderOnboardingGoals();
      updateSelectedPanel();
      syncMapLayerElBoxFromGrid();
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
    techModalPathGuide = null;
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
      const expensesAgg = body.expenses_aggregate_per_sol || {};
      const binfo = body.buildings || {};
      const buildOnTile = Number(binfo.planet_buildings ?? 0) || 0;
      const buildFieldShown = Number(binfo.external_buildings ?? 0) || 0;
      const buildFieldHidden = Number(binfo.external_buildings_hidden ?? 0) || 0;
      const buildTotalEmpire =
        buildOnTile +
        buildFieldShown +
        buildFieldHidden;
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
      const resWikiTitle = (k) => {
        const m = {
          metal: "Металл",
          crystal: "Кристаллы",
          energy: "Энергия",
          fuel: "Топливо",
          food: "Еда",
          water: "Вода",
        };
        return m[k] || String(k || "");
      };
      const resWikiBtn = (k, innerHtml) =>
        `<button type="button" class="econ-wiki-res" data-wiki-res="${escHtml(k)}" title="Справка: ${escHtml(resWikiTitle(k))}">${innerHtml}</button>`;
      const resGrid = (map, useSigned = false) => {
        const f = useSigned ? fmtSigned : fmt;
        return `<div class="econ-resource-grid">${resKeys
          .map((k) => {
            const ic = resIcons[k] || k;
            return resWikiBtn(k, `${ic} <b>${escHtml(f(map && map[k]))}</b>`);
          })
          .join("")}</div>`;
      };
      const costRow = (label, map, keys) => {
        const parts = keys.map((k) => {
          const ic = resIcons[k] || k;
          return resWikiBtn(k, `${ic} <b>${escHtml(fmt(map && map[k]))}</b>`);
        });
        return `<div class="econ-cost-row"><span class="econ-row-label">${escHtml(label)}</span>${parts.join("")}</div>`;
      };
      const resKeys4 = ["metal", "crystal", "energy", "fuel"];
      const resGridFour = (map) =>
        `<div class="econ-resource-grid" style="grid-template-columns:repeat(4,1fr)">${resKeys4
          .map((k) => {
            const ic = resIcons[k];
            return resWikiBtn(k, `${ic} <b>${escHtml(fmt(map && map[k]))}</b>`);
          })
          .join("")}</div>`;

      const showExtChk = `<label class="econ-toggle econ-toggle--inline"><input type="checkbox" id="econ-show-ext" name="econ_show_ext" ${showExt ? "checked" : ""} />
        <span>Внешние постройки в сводке</span></label>`;

      const ep = readEconPrefs();
      const detailsReadOpen = Boolean(ep.econModalDetailsReadTable);
      const detailsRefsOpen = Boolean(ep.econModalDetailsBuildings);

      const expenseWeight = (m) =>
        resKeys.reduce((acc, k) => acc + Math.max(0, Number(m && m[k]) || 0), 0);
      const expenseCategories = [
        { key: "population_vitals", label: "Население (еда и вода)", map: costs.population_vitals },
        {
          key: "outpost_supply_logistics",
          label: "Логистика форпостов",
          map: costs.outpost_supply_logistics || {},
        },
        { key: "outpost_upkeep", label: "Содержание форпостов", map: costs.outpost_upkeep || {} },
        {
          key: "fleet_empire_upkeep",
          label: "Содержание флотов (империя)",
          map: costs.fleet_empire_upkeep || {},
        },
        {
          key: "fleet_energy_upkeep",
          label: "Энергия на борту флотов",
          map: costs.fleet_energy_upkeep || {},
        },
      ];
      let biggestCategory = expenseCategories[0];
      let biggestW = expenseWeight(biggestCategory.map);
      for (let i = 1; i < expenseCategories.length; i++) {
        const c = expenseCategories[i];
        const w = expenseWeight(c.map);
        if (w > biggestW) {
          biggestW = w;
          biggestCategory = c;
        }
      }
      const rowKeysBig = resKeys.filter((k) => Number(biggestCategory.map && biggestCategory.map[k]) > 0);
      const biggestExpenseBlock =
        biggestW <= 0
          ? `<p class="econ-muted" style="margin:0;">Статьи расхода по API — нули; при росте нагрузки здесь будет самая «тяжёлая» статья.</p>`
          : `<div class="econ-muted" style="margin:0 0 10px;line-height:1.35;"><b>${escHtml(biggestCategory.label)}</b> — крупнейшая суммарная статья за сол среди расходов (по включённым ресурсам).</div>
             ${costRow("За сол", biggestCategory.map, rowKeysBig)}`;

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

      const runway = body.runway_sols || {};
      const runwayCells = resKeys
        .map((k) => {
          const ic = resIcons[k] || k;
          const e = runway[k];
          let txt = "—";
          if (e && e.trend === "drain" && e.approx_sols != null) {
            const n = Number(e.approx_sols);
            txt = `≈ ${n} ${solWord(n)}`;
          } else if (e && e.trend === "surplus") {
            txt = "растёт";
          }
          return resWikiBtn(k, `${ic} <b>${escHtml(txt)}</b>`);
        })
        .join("");

      economyModalBody.innerHTML = `
        <div class="econ-modal">
          <div class="econ-lead econ-lead-tools">
            <span class="econ-lead-main">Текущий сол: <b>${escHtml(String(body.current_sol ?? body.current_tick ?? 0))}</b> • Наука:
            <button type="button" class="econ-wiki-res econ-wiki-res--bare" data-wiki-res="rp" title="Справка: очки исследований (RP)"><b>${escHtml(String(body.research_points ?? 0))}</b></button>
            <span class="muted"> (+${escHtml(String(body.research_points_per_sol ?? 0))}/сол)</span></span>
            ${showExtChk}
          </div>

          <div class="game-modal-grid econ-three">
            <div class="game-modal-col game-modal-col--entity">
              <div class="section-title">Чистый приток за сол</div>
              <p class="muted" style="margin:0 0 8px;font-size:82%;">По сумме складов империи после всех статей.</p>
              ${resGrid(net, true)}
              <div class="section-title" style="margin-top:14px;">Домашняя планета</div>
              <p class="muted" style="margin:0 0 8px;font-size:80%;">Отдельно от имперских списаний флотов с капитала.</p>
              ${resGrid(netHome, true)}
            </div>
            <div class="game-modal-col game-modal-col--state">
              <div class="section-title">Производство планет</div>
              <p class="muted" style="margin:0 0 8px;font-size:80%;">Сумма колоний</p>
              ${resGrid(prod)}
              <div class="section-title" style="margin-top:14px;">Расходы за сол</div>
              ${costRow("Население", costs.population_vitals, ["food", "water"])}
              ${costRow("Логистика форпостов", costs.outpost_supply_logistics || {}, ["food", "water"])}
              ${costRow("Содержание форпостов", costs.outpost_upkeep, ["metal", "crystal", "energy", "fuel"])}
              ${costRow("Имперские расходы флотов", costs.fleet_empire_upkeep, ["metal", "crystal", "food", "water"])}
              ${costRow("Энергия флотов на борту", costs.fleet_energy_upkeep, ["energy"])}
              <p class="muted" style="margin:10px 0 4px;font-size:78%;line-height:1.35;">Итого по строкам выше (металл, кристалл, энергия, топливо) в основном даёт <b>содержание форпостов</b> и энергия флотов; при отдельных настройках — имперское снабжение кораблей. Сумма всех списаний по складам за сол:</p>
              ${costRow("Всего списано за сол", expensesAgg, resKeys)}
              <div class="section-title" style="margin-top:14px;">Запасы</div>
              <div class="muted" style="margin:0 0 6px;font-size:80%;">Империя и дом</div>
              <div class="econ-resource-grid">${resKeys
                .map((k) => {
                  const ic = resIcons[k] || k;
                  const a = tEmp && tEmp[k] != null ? fmt(tEmp[k]) : "0";
                  const h = tHome && tHome[k] != null ? fmt(tHome[k]) : "0";
                  return resWikiBtn(k, `${ic} <b>${escHtml(a)}</b><span class="muted"> / ${escHtml(h)}</span>`);
                })
                .join("")}</div>
              <div class="section-title" style="margin-top:14px;">Горизонт</div>
              <p class="muted" style="margin:0 0 6px;font-size:78%;">Оценка «хватит на N солов» при текущем чистом расходе</p>
              <div class="econ-resource-grid">${runwayCells}</div>
            </div>
            <div class="game-modal-col game-modal-col--actions econ-col-spend">
              <div class="section-title">Главный расход</div>
              <div class="econ-card econ-card-nested">${biggestExpenseBlock}</div>
            </div>
          </div>

          <details class="game-modal-details econ-modal-details" data-econ-details="guide" style="margin-top:12px;"${detailsReadOpen ? " open" : ""}>
            <summary class="game-modal-details-summary">Как читать таблицу</summary>
            <div class="game-modal-details-inner">
              <ol class="econ-flow-hints econ-muted" style="margin:8px 0 0;">
                <li><b>Слева</b> — прирост/спад складов империи за сол (домашняя планета отдельно).</li>
                <li><b>Центр</b> — производство колоний, статьи расхода и запасы с горизонтом.</li>
                <li><b>Справа</b> — статья с наибольшей суммарной нагрузкой по ресурсам.</li>
                <li>Иконки ресурсов в этой модалке и в топбаре кликабельны — открывают вики с пояснением.</li>
              </ol>
            </div>
          </details>

          <details class="game-modal-details econ-modal-details" data-econ-details="refs"${detailsRefsOpen ? " open" : ""}>
            <summary class="game-modal-details-summary">Строительство (справочно), постройки, полевые данные, флоты</summary>
            <div class="game-modal-details-inner">
              <section class="econ-section" style="margin-top:0;">
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
                <h4 class="econ-section-title">Постройки (счётчики)</h4>
                <div class="econ-card">
                  На тайле колонии (клетка планеты): <b>${escHtml(String(buildOnTile))}</b> • Полевые (остальные клетки): <b>${escHtml(
        String(buildFieldShown)
      )}</b>${buildFieldHidden ? ` <span class="muted">(скрыто в сводке: ${escHtml(String(buildFieldHidden))})</span>` : ""}
                  <p class="econ-muted" style="margin:8px 0 0;font-size:82%;line-height:1.4;">Всего построек империи: <b>${escHtml(String(buildTotalEmpire))}</b>. Счётчик <b>«Слоты»</b> у колонии учитывает только <b>тайл планеты</b> (число при старте с небольшим разбросом). Полевые постройки <b>не расходуют</b> эти слоты — их ограничивают ресурсы, зона и правило «одна постройка на клетку».</p>
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
          </details>
        </div>
      `;

      const bindEconomyDetailPref = (selector, prefKey) => {
        const el = economyModalBody.querySelector(selector);
        if (!el) return;
        el.addEventListener("toggle", () => {
          writeEconPrefs({ [prefKey]: Boolean(el.open) });
        });
      };
      bindEconomyDetailPref('[data-econ-details="guide"]', "econModalDetailsReadTable");
      bindEconomyDetailPref('[data-econ-details="refs"]', "econModalDetailsBuildings");

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
    mergeOnboardingMilestones({ empireOpened: true });
    await loadEconomyModalContent();
  };
  const closeEconomyModal = () => {
    if (economyModalOverlay) economyModalOverlay.classList.add("hidden");
  };

  const WIKI_ANCHOR_BY_RES_KEY = Object.freeze({
    metal: "wiki-res-metal",
    crystal: "wiki-res-crystal",
    energy: "wiki-res-energy",
    fuel: "wiki-res-fuel",
    food: "wiki-res-food",
    water: "wiki-res-water",
    rp: "wiki-res-rp",
  });

  const openWikiForResourceKey = (key) => {
    const k = String(key || "").trim().toLowerCase();
    const anchor = WIKI_ANCHOR_BY_RES_KEY[k] || "wiki-eco-resources";
    closeEconomyModal();
    closeTechModal();
    closePlanetModal();
    closeFleetModal();
    openEntryTutorial(anchor);
  };

  const TECH_RES_LABEL_RU = {
    metal: "металл",
    crystal: "кристалл",
    energy: "энергия",
    fuel: "топливо",
    food: "еда",
    water: "вода",
  };
  const TECH_RES_ICONS = {
    metal: "⛏",
    crystal: "💎",
    energy: "⚡",
    fuel: "⛽",
    food: "🍲",
    water: "💧",
  };

  const fieldDataRequirementRu = (k) => {
    const key = String(k || "").trim();
    const map = {
      ruin_archives: "архивы развалин",
      anomaly_data: "данные аномалии",
      research_fragments: "исследовательские фрагменты",
    };
    return map[key] || key.replace(/_/g, " ");
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
      lines.push(`расход топлива в полёте ×${eff.travel_fuel_multiplier} (ниже — дешевле)`);
    }
    if (eff.production_multiplier && typeof eff.production_multiplier === "object") {
      for (const [k, v] of Object.entries(eff.production_multiplier)) {
        const lab = TECH_RES_LABEL_RU[k] || k;
        lines.push(`производство «${lab}» ×${v}`);
      }
    }
    for (const [k, v] of Object.entries(eff)) {
      if (k === "travel_fuel_multiplier" || k === "production_multiplier") continue;
      if (typeof v === "number") lines.push(`${TECH_RES_LABEL_RU[k] || k} ×${v}`);
      else if (v && typeof v === "object") lines.push(`${k}: данные см. сервер`);
    }
    return lines;
  };

  /** Пояснения к эффекту теха с числами «сейчас → после» по сводке экономики игрока. */
  const describeTechEffectsForTooltipLines = (eff, econ) => {
    if (!eff || typeof eff !== "object") return [];
    const prod =
      econ && econ.production_per_sol && typeof econ.production_per_sol === "object"
        ? econ.production_per_sol
        : null;
    const costs =
      econ && econ.costs_per_sol && typeof econ.costs_per_sol === "object" ? econ.costs_per_sol : null;
    const fmtSolInt = (n) => {
      const x = Number(n);
      if (!Number.isFinite(x)) return "?";
      return String(Math.round(x));
    };

    const lines = [];
    if (eff.production_multiplier && typeof eff.production_multiplier === "object" && prod) {
      for (const [k, multRaw] of Object.entries(eff.production_multiplier)) {
        const mult = Number(multRaw);
        if (!Number.isFinite(mult) || mult <= 0) continue;
        const cur = Number(prod[k]);
        if (!Number.isFinite(cur)) continue;
        const after = Math.round(cur * mult);
        const ic = TECH_RES_ICONS[k] || "";
        const lab = TECH_RES_LABEL_RU[k] || k;
        lines.push(`${ic} ${lab}: суммарное произв. колоний сейчас +${fmtSolInt(cur)}/сол → после +${fmtSolInt(after)}/сол (×${mult})`);
      }
    } else if (eff.production_multiplier && typeof eff.production_multiplier === "object") {
      for (const [k, v] of Object.entries(eff.production_multiplier)) {
        const lab = TECH_RES_LABEL_RU[k] || k;
        lines.push(`производство «${lab}» ×${v} (откройте сводку «Империя» для цифр)`);
      }
    }

    if (typeof eff.travel_fuel_multiplier === "number") {
      lines.push(`расход топлива за клетку перелёта ×${eff.travel_fuel_multiplier} (ниже — дешевле; суммируется с другими техами)`);
    }

    if (typeof eff.upkeep_energy_multiplier === "number" && costs && costs.fleet_energy_upkeep) {
      const u = Number(costs.fleet_energy_upkeep.energy);
      if (Number.isFinite(u) && u > 0) {
        const nu = Math.round(u * eff.upkeep_energy_multiplier);
        lines.push(
          `${TECH_RES_ICONS.energy || "⚡"} энергия на борт флотов (статья): сейчас ${fmtSolInt(u)}/сол → после ${fmtSolInt(nu)}/сол (×${eff.upkeep_energy_multiplier})`
        );
      } else {
        lines.push(`энергоудержание флотов ×${eff.upkeep_energy_multiplier} (ниже — дешевле)`);
      }
    } else if (typeof eff.upkeep_energy_multiplier === "number") {
      lines.push(`энергоудержание флотов ×${eff.upkeep_energy_multiplier} (ниже — дешевле)`);
    }

    if (typeof eff.combat_damage_multiplier === "number") {
      lines.push(`боевой урон флотов ×${eff.combat_damage_multiplier} (перемножается с другими завершёнными техами)`);
    }
    if (typeof eff.combat_hp_multiplier === "number") {
      lines.push(`боевая выживаемость (HP-подобное) ×${eff.combat_hp_multiplier} (перемножается)`);
    }

    if (typeof eff.supply_base_add === "number") {
      lines.push(`📡 базовый радиус снабжения колонии: +${eff.supply_base_add} к «базе» узла`);
    }
    if (typeof eff.supply_per_supplier_add === "number") {
      lines.push(`📡 вклад каждого поставщика в радиус: +${eff.supply_per_supplier_add}`);
    }

    const handled = new Set([
      "production_multiplier",
      "travel_fuel_multiplier",
      "upkeep_energy_multiplier",
      "combat_damage_multiplier",
      "combat_hp_multiplier",
      "supply_base_add",
      "supply_per_supplier_add",
    ]);
    for (const [key, val] of Object.entries(eff)) {
      if (handled.has(key)) continue;
      if (typeof val === "number") lines.push(`${TECH_RES_LABEL_RU[key] || key}: ×${val}`);
      else if (val && typeof val === "object") lines.push(`${key}: см. описание технологии`);
    }
    return lines;
  };

  const formatPrereqNames = (prereq, byTechId) => {
    const arr = Array.isArray(prereq) ? prereq : [];
    if (!arr.length) return "нет";
    return arr
      .map((id) => {
        const t = byTechId[id];
        return t && t.name ? String(t.name) : "Неизвестная технология";
      })
      .join(", ");
  };

  const techDetailTooltipPlain = (t, byTechId, effectsBody, econSnap) => {
    const lines = [];
    const fdReq = Array.isArray(t.field_data_requirements)
      ? t.field_data_requirements.filter((x) => typeof x === "string" && x.trim())
      : [];
    const effs = effectsBody && Array.isArray(effectsBody.effects) ? effectsBody.effects : [];
    const effCount = (k) => effs.filter((e) => e && e.effect_type === k && e.used_at_tick == null).length;
    const fdReqRu = fdReq.filter((kk) => effCount(kk) < 1);
    lines.push(`Тир: ${t.tier ?? "—"}`);
    const tickN = Number(t.time_ticks);
    const residualN = Number(t.residual_time_ticks);
    const workTicks = Number.isFinite(residualN) && residualN > 0 ? residualN : tickN;
    if (Number.isFinite(workTicks) && workTicks > 0) lines.push(`Длительность работы: ${Math.round(workTicks)} ${solWord(workTicks)}`);
    const rpNeed = Number(t.research_points_cost);
    const payBits = [];
    if (Number.isFinite(rpNeed) && rpNeed > 0) payBits.push(`наука ${rpNeed}`);
    const cst = formatTechCost(t.cost);
    if (cst && cst !== "—") payBits.push(cst);
    lines.push(`Оплата при запуске: ${payBits.length ? payBits.join(", ") : "—"}`);
    const desc = typeof t.description === "string" && t.description.trim() ? t.description.trim() : "";
    if (desc) lines.push(`Описание: ${desc}`);
    const efLines = describeTechEffectsForTooltipLines(
      t.effects && typeof t.effects === "object" ? t.effects : {},
      econSnap && econSnap.ok ? econSnap : null
    );
    if (efLines.length) lines.push(`Эффекты:\n${efLines.join("\n")}`);
    lines.push(`Нужные технологии: ${formatPrereqNames(t.prereq, byTechId)}`);
    lines.push(`Полевые данные для старта: ${fdReq.length ? fdReq.map(fieldDataRequirementRu).join(", ") : "нет"}`);
    if (fdReqRu.length) lines.push(`Не хватает полевых данных: ${fdReqRu.map(fieldDataRequirementRu).join(", ")}`);
    return lines.join("\n");
  };

  const researchStepsWordRu = (n) => {
    const v = Math.abs(Math.floor(Number(n) || 0));
    const mod100 = v % 100;
    const mod10 = v % 10;
    if (mod100 >= 11 && mod100 <= 14) return "исследований";
    if (mod10 === 1) return "исследование";
    if (mod10 >= 2 && mod10 <= 4) return "исследования";
    return "исследований";
  };

  const scrollTechCardIntoView = (techId) => {
    if (!techModalBody || !techId) return;
    const id = String(techId).replace(/\\/g, "").replace(/"/g, "");
    const el = techModalBody.querySelector(`[data-tech-card="${id}"]`);
    if (el && typeof el.scrollIntoView === "function")
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
      const rpPlayerBal = Number(stBody.research_points) || 0;
      const rows = Array.isArray(stBody.techs) ? stBody.techs : [];
      const byId = {};
      for (const r of rows) byId[r.tech_id] = r;
      const doneSet = new Set(rows.filter((r) => r && r.status === "done" && r.tech_id).map((r) => String(r.tech_id)));

      const techList = Array.isArray(balBody.tech) ? balBody.tech : [];
      const byTechId = {};
      for (const t of techList) if (t && t.id) byTechId[t.id] = t;
      const enabled = techList.filter((t) => t && t.enabled !== false);

      let effectsBody = null;
      let econSnap = null;
      try {
        const [er, econR] = await Promise.all([
          fetch("/api/effects/active"),
          fetch("/api/economy/summary?include_external_buildings=1"),
        ]);
        const eb = await er.json().catch(() => null);
        if (er.ok && eb && eb.ok) effectsBody = eb;
        const ecb = await econR.json().catch(() => null);
        if (econR.ok && ecb && ecb.ok) econSnap = ecb;
      } catch (_e2) {
        effectsBody = null;
        econSnap = null;
      }

      const prefs = readTechUiPrefs();
      const searchDraft =
        typeof prefs.search === "string"
          ? prefs.search.slice(0, 240)
          : "";
      const validTechTabs = new Set(["all", "available", "done"]);
      if (prefs.tab === "in_progress") writeTechUiPrefs({ tab: "available" });
      let activeTab =
        prefs.tab === "in_progress"
          ? "available"
          : validTechTabs.has(prefs.tab)
            ? prefs.tab
            : "available";

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
      const techRowsList = Array.isArray(stBody.techs) ? stBody.techs : [];
      const activeResearchRow =
        techRowsList.find((r) => r && r.status === "in_progress") || null;
      const researchQueueBusy = Boolean(activeResearchRow);

      const techReadyIgnoringQueue = (t) => {
        if (techStatus(t) !== "none") return false;
        return techPrereqMissing(t).length === 0 && techFieldDataMissing(t).length === 0;
      };
      const techCanStart = (t) => techReadyIgnoringQueue(t) && !researchQueueBusy;

      /** Следующий «рубеж»: есть неизученные прямые prereq и каждый из них готов к запуску (если бы очередь была свободна); у самого теха уже хватает полевых данных. */
      const techQualifiesNextPreview = (t) => {
        if (!t || techStatus(t) !== "none") return false;
        const missP = techPrereqMissing(t);
        if (missP.length === 0) return false;
        if (techFieldDataMissing(t).length > 0) return false;
        for (const pid of missP) {
          const pt = byTechId[String(pid)];
          if (!pt || pt.enabled === false) return false;
          if (!techReadyIgnoringQueue(pt)) return false;
        }
        return true;
      };

      const previewIdSet = new Set(
        enabled.filter(techQualifiesNextPreview).map((t) => String(t.id))
      );

      const fillTechQueuePanel = () => {
        const el = techModalBody.querySelector("#tech-queue-panel");
        if (!el) return;
        const curSol = Number(stBody.current_sol ?? stBody.current_tick ?? 0);
        const active = techRowsList.find((r) => r && r.status === "in_progress") || null;
        const past =
          techRowsList
            .filter((r) => r && r.status === "done")
            .sort(
              (a, b) =>
                (Number(b.finish_tick) || Number(b.finish_sol) || 0) -
                (Number(a.finish_tick) || Number(a.finish_sol) || 0)
            )[0] || null;
        const nm = (tid) => {
          const bd = tid && byTechId[String(tid)];
          return bd && bd.name ? String(bd.name) : tid || "—";
        };

        let activeBlock = `<div class="muted tech-queue-empty">Нет активного исследования</div>`;
        if (active) {
          const tid = String(active.tech_id || "");
          const start = Number(active.started_tick ?? active.started_sol ?? 0);
          const fin = Number(active.finish_tick ?? active.finish_sol ?? 0);
          const remRaw = Number(active.remaining_ticks ?? active.remaining_sols);
          const rem =
            Number.isFinite(remRaw) && remRaw >= 0
              ? Math.floor(remRaw)
              : Math.max(0, Math.floor(fin - curSol));
          const totalTicks = Math.max(1, fin - start);
          const elapsed = Math.min(totalTicks, Math.max(0, curSol - start));
          const pct = Math.min(100, Math.max(0, Math.round((100 * elapsed) / totalTicks)));
          const tipActive = [
            `Сол старта: ${start}`,
            `Примерное завершение: сол ${fin}`,
            Number.isFinite(rem) ? `Осталось: ~${rem} ${solWord(rem)}` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          activeBlock = `<div class="tech-queue-active">
            <div class="muted tech-queue-label">Сейчас</div>
            <abbr class="tech-queue-name-wrap" tabindex="0" title="${escAttr(tipActive)}"><span class="tech-queue-name">${escHtml(nm(tid))}</span></abbr>
            <div class="tech-queue-meta muted" aria-hidden="true">~${rem} ${solWord(rem)} · сол ${fin}</div>
            <div class="tech-queue-bar-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Прогресс текущего исследования">
              <div class="tech-queue-bar-fill" style="width:${pct}%"></div>
            </div>
          </div>`;
        }

        let pastBlock = `<div class="tech-queue-past"><div class="muted tech-queue-label">Ранее</div><span class="muted">—</span></div>`;
        if (past) {
          const ptid = String(past.tech_id || "");
          const fSol = Number(past.finish_tick ?? past.finish_sol ?? 0);
          const tipPast = `Завершено примерно к солу ${fSol}`;
          pastBlock = `<div class="tech-queue-past">
            <div class="muted tech-queue-label">Ранее</div>
            <abbr class="tech-queue-past-name-wrap" tabindex="0" title="${escAttr(tipPast)}"><span class="tech-queue-past-name">${escHtml(nm(ptid))}</span></abbr>
          </div>`;
        }

        el.innerHTML = activeBlock + pastBlock;
      };

      const renderCardInnerCompact = (t) => {
        const st0 = byId[t.id] || null;
        const status = st0 ? st0.status : "none";
        const rem = st0 && Number.isInteger(st0.remaining_ticks) ? st0.remaining_ticks : null;
        const missingPrereq = techPrereqMissing(t);
        const missingFd = techFieldDataMissing(t);
        const blockedReason =
          missingPrereq.length
            ? `Сначала: ${formatPrereqNames(missingPrereq, byTechId)}`
            : missingFd.length
              ? `Нужно: ${missingFd.map(fieldDataRequirementRu).join(", ")}`
              : null;
        const queueBlockTitle =
          researchQueueBusy && !blockedReason
            ? "Сначала завершите текущее исследование — панель задач исследований слева."
            : "";
        const canStart = status === "none" && !blockedReason && !researchQueueBusy;
        const startTitle = blockedReason || queueBlockTitle || "";
        const btn =
          status === "none"
            ? `<button type="button" class="btn-primary" data-tech="${escHtml(t.id)}" ${canStart ? "" : "disabled"} title="${escAttr(startTitle)}">${canStart ? "Запустить" : "Недоступно"}</button>`
            : "";
        const prog =
          status === "in_progress"
            ? `<div class="tech-item-progress muted">Идёт: осталось <b>${rem ?? "?"}</b> ${rem != null && Number.isFinite(Number(rem)) ? solWord(rem) : "ходов галактики"}</div>`
            : "";

        const effLines = describeTechEffectsForTooltipLines(
          t.effects && typeof t.effects === "object" ? t.effects : {},
          econSnap
        );
        const desc =
          typeof t.description === "string" && t.description.trim()
            ? t.description.trim()
            : effLines.length
              ? effLines.slice(0, 2).join(" · ")
              : "Подробнее — значок справа.";
        const tooltip = techDetailTooltipPlain(t, byTechId, effectsBody, econSnap);
        const name = escHtml(t.name || "Технология");
        const help = `<abbr class="tech-item-help-abbr" tabindex="0" title="${escAttr(tooltip)}" aria-label="Подробная карточка">?</abbr>`;

        return `
            <div class="tech-item-head">
              <div class="tech-item-title-line">${name}${help}</div>
              <div class="tech-item-act">${btn}</div>
            </div>
            ${prog}
            <div class="tech-item-snippet muted">${escHtml(desc)}</div>
        `;
      };

      const techCardPathCls = (t) => {
        if (!techModalPathGuide?.active || !Array.isArray(techModalPathGuide.prereqIds)) return "";
        const set = new Set(techModalPathGuide.prereqIds.map(String));
        return set.has(String(t.id)) ? " tech-item-path-focus" : "";
      };

      const renderCard = (t) => {
        const status = techStatus(t);
        const tip = escAttr(techDetailTooltipPlain(t, byTechId, effectsBody, econSnap));
        const pathCls = techCardPathCls(t);
        const cardIdAttr = ` data-tech-card="${escAttr(String(t.id))}"`;
        if (status === "done") {
          const nm = escHtml(t.name || "Технология");
          return `<div class="tech-item tech-item-done-strip${pathCls}"${cardIdAttr}>
            <span class="muted tech-done-chip">✓ готово</span>
            <span class="tech-done-strip-name">${nm}</span>
            <abbr class="tech-item-help-abbr" tabindex="0" title="${tip}" aria-label="Подробная карточка">?</abbr>
          </div>`;
        }
        const activeCls = status === "in_progress" ? " tech-item-active" : "";
        return `<div class="tech-item${activeCls}${pathCls}"${cardIdAttr}>${renderCardInnerCompact(t)}</div>`;
      };

      const matchesSearch = (t, q) => {
        if (!q) return true;
        const id = String(t.id || "").toLowerCase();
        const nm = String(t.name || "").toLowerCase();
        return id.includes(q) || nm.includes(q);
      };

      const filterList = (qRaw) => {
        const q = (qRaw || "").trim().toLowerCase();
        if (techModalPathGuide?.active && Array.isArray(techModalPathGuide.prereqIds)) {
          const allowed = new Set(techModalPathGuide.prereqIds.map(String));
          return enabled.filter((t) => {
            if (!allowed.has(String(t.id))) return false;
            return matchesSearch(t, q);
          });
        }
        return enabled.filter((t) => {
          if (previewIdSet.has(String(t.id))) return false;
          const st = techStatus(t);
          if (!matchesSearch(t, q)) return false;
          if (activeTab === "available") return techCanStart(t);
          if (activeTab === "done") return st === "done";
          return true;
        });
      };

      const filterPreviewList = (qRaw) => {
        const q = (qRaw || "").trim().toLowerCase();
        const arr = enabled.filter((t) => previewIdSet.has(String(t.id)) && matchesSearch(t, q));
        arr.sort((a, b) => {
          const ta = Number(a.tier);
          const tb = Number(b.tier);
          if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return ta - tb;
          const na = String(a.name || a.id || "");
          const nb = String(b.name || b.id || "");
          return na.localeCompare(nb, "ru");
        });
        return arr;
      };

      const renderPreviewCard = (t) => {
        const tip = escAttr(techDetailTooltipPlain(t, byTechId, effectsBody, econSnap));
        const nm = escHtml(t.name || "Технология");
        const prereqOrder = Array.isArray(t.prereq)
          ? t.prereq.filter((x) => typeof x === "string" && String(x).trim())
          : [];
        const chainHtml = prereqOrder
          .map((pid, idx) => {
            const pidS = String(pid);
            const done = doneSet.has(pidS);
            const pt = byTechId[pidS];
            const label = pt && pt.name ? String(pt.name).trim() : pidS;
            const mark = done ? "✔" : "✖";
            const btn = `<button type="button" class="tech-chain-pill${done ? " tech-chain-pill--done" : " tech-chain-pill--todo"}" data-tech-preview-anchor="${escAttr(String(t.id))}" data-tech-focus-prereq="${escAttr(pidS)}">${mark} ${escHtml(label)}</button>`;
            const arrow =
              idx < prereqOrder.length - 1
                ? `<span class="tech-chain-arr" aria-hidden="true">→</span>`
                : "";
            return `${btn}${arrow}`;
          })
          .join("");
        let desc = "";
        if (typeof t.description === "string" && t.description.trim()) {
          const raw = t.description.trim();
          desc =
            raw.length > 220
              ? `${escHtml(raw.slice(0, 220).trimEnd())}…`
              : escHtml(raw);
        }
        const totalReq = prereqOrder.length || 1;
        const doneReq = prereqOrder.filter((pid) => doneSet.has(String(pid))).length;
        const leftReq = prereqOrder.filter((pid) => !doneSet.has(String(pid))).length;
        const pathActive =
          techModalPathGuide?.active && String(techModalPathGuide.targetId) === String(t.id)
            ? " tech-item-preview--path-active"
            : "";
        return `<div class="tech-item tech-item-preview${pathActive}" data-tech-preview-target="${escAttr(String(t.id))}">
          <div class="tech-item-head">
            <div class="tech-item-title-line"><span class="tech-preview-lock" title="Откроется после зависимостей">🔒</span>${nm}
              <abbr class="tech-item-help-abbr" tabindex="0" title="${tip}" aria-label="Подробная карточка">?</abbr>
            </div>
          </div>
          <div class="tech-preview-metrics muted">
            <span class="tech-preview-metrics-strong">${doneReq}/${totalReq} условий</span>
            <span class="tech-preview-metrics-dot"> · </span>
            <span>до открытия: ещё <b>${leftReq}</b> ${researchStepsWordRu(leftReq)}</span>
          </div>
          <div class="tech-preview-chain-wrap">
            <div class="tech-preview-chain">${chainHtml}</div>
          </div>
          ${desc ? `<div class="tech-item-snippet muted">${desc}</div>` : ""}
          <button type="button" class="btn-secondary tech-path-build-btn" data-tech-path-for="${escAttr(String(t.id))}">Построить путь</button>
        </div>`;
      };

      const paint = (searchVal) => {
        const searchLive =
          techModalBody && techModalBody.querySelector("#tech-search")
            ? String(techModalBody.querySelector("#tech-search").value ?? "")
            : String(searchVal ?? "");
        const bannerSlot = techModalBody.querySelector("#tech-path-banner-slot");
        if (bannerSlot) {
          if (techModalPathGuide?.active && techModalPathGuide.targetId) {
            const gt = byTechId[String(techModalPathGuide.targetId)];
            const gnm = gt && gt.name ? String(gt.name) : "технология";
            bannerSlot.innerHTML = `<div class="tech-path-banner" role="region" aria-label="Маршрут исследований"><div class="tech-path-banner-inner"><span>В центре — шаги к <b>${escHtml(gnm)}</b>; подсвечены ячейки маршрута.</span><button type="button" class="btn-secondary tech-path-banner-clear">Снять маршрут</button></div></div>`;
          } else {
            bannerSlot.innerHTML = "";
          }
        }
        const clr = bannerSlot && bannerSlot.querySelector(".tech-path-banner-clear");
        if (clr) {
          clr.addEventListener("click", () => {
            techModalPathGuide = null;
            paint(String(techModalBody.querySelector("#tech-search")?.value ?? ""));
          });
        }

        const list = filterList(searchLive);
        const plist = filterPreviewList(searchLive);
        const elList = techModalBody.querySelector("#tech-modal-list");
        if (!elList) return;
        elList.innerHTML =
          list.map(renderCard).join("") ||
          `<div class="muted">${
            techModalPathGuide?.active
              ? "Нет шагов маршрута в списке. Снимите маршрут или измените поиск."
              : `По фильтру ничего нет (${escHtml(activeTab)})`
          }</div>`;
        for (const b of elList.querySelectorAll("button[data-tech]")) {
          b.addEventListener("click", async () => {
            if (b.disabled) return;
            const tech_id = b.getAttribute("data-tech");
            const tnm = tech_id && byTechId[tech_id] && byTechId[tech_id].name ? String(byTechId[tech_id].name) : "Исследование";
            setStatus("Запуск исследования…");
            const r = await fetch("/api/tech/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tech_id }),
            });
            const body = await r.json();
            const techFb = techModalBody.querySelector("#tech-modal-feedback");
            if (!r.ok || !body.ok) {
              const errRu = formatApiFailure(body);
              setStatus(errRu, "err");
              if (techFb) showActionFeedback(techFb, errRu, "err");
              await loadTechModalContent();
              return;
            }
            const extra = [];
            if (body.research_time_multiplier && body.research_time_multiplier < 0.999)
              extra.push(`ускорение ×${Number(body.research_time_multiplier).toFixed(2)}`);
            if (body.blueprint_cache_consumed) extra.push("потрачен кэш чертежей");
            const okMsg = `Запущено: «${tnm}»${extra.length ? ". " + extra.join(", ") : ""}`;
            setStatus(okMsg, "ok");
            if (techFb) showActionFeedback(techFb, okMsg, "ok");
            mergeOnboardingMilestones({ techQueued: true });
            await loadTechModalContent();
          });
        }
        const elPv = techModalBody.querySelector("#tech-modal-preview-list");
        if (elPv) {
          elPv.innerHTML =
            plist.length > 0
              ? plist.map(renderPreviewCard).join("")
              : `<div class="muted">Здесь появятся технологии, у которых остались только неизученные зависимости — и каждую из них вы можете начать в средней колонке.</div>`;
          for (const b of techModalBody.querySelectorAll("[data-tech-focus-prereq]")) {
            b.addEventListener("click", () => {
              const anchor = b.getAttribute("data-tech-preview-anchor");
              const prereqFocus = b.getAttribute("data-tech-focus-prereq");
              const techT = anchor ? byTechId[String(anchor)] : null;
              if (!techT || !prereqFocus) return;
              const misses = techPrereqMissing(techT);
              if (!misses.length) return;
              techModalPathGuide = {
                active: true,
                targetId: String(anchor),
                prereqIds: misses.map(String),
              };
              const qNow =
                techModalBody.querySelector("#tech-search")?.value ??
                "";
              paint(String(qNow));
              requestAnimationFrame(() => requestAnimationFrame(() => scrollTechCardIntoView(prereqFocus)));
            });
          }
          for (const b of techModalBody.querySelectorAll("[data-tech-path-for]")) {
            b.addEventListener("click", () => {
              const tid = b.getAttribute("data-tech-path-for");
              const tt = tid ? byTechId[String(tid)] : null;
              if (!tt) return;
              const misses = techPrereqMissing(tt);
              if (!misses.length) return;
              techModalPathGuide = { active: true, targetId: String(tid), prereqIds: misses.map(String) };
              const qNow =
                techModalBody.querySelector("#tech-search")?.value ??
                "";
              paint(String(qNow));
              const firstTodo = misses.find((pid) => !doneSet.has(String(pid)));
              requestAnimationFrame(() =>
                requestAnimationFrame(() => scrollTechCardIntoView(firstTodo || misses[0]))
              );
            });
          }
        }
      };

      const scrollKeep =
        techModalBody && techModalBody.querySelector(".tech-research-grid")
          ? (() => {
              const mainEl = techModalBody.querySelector(".tech-modal-main");
              const listEl = techModalBody.querySelector("#tech-modal-list");
              const pvEl = techModalBody.querySelector("#tech-modal-preview-list");
              return {
                body: techModalBody.scrollTop,
                main: mainEl ? mainEl.scrollTop : 0,
                list: listEl ? listEl.scrollTop : 0,
                preview: pvEl ? pvEl.scrollTop : 0,
              };
            })()
          : null;

      const rpRounded = escHtml(String(Math.round(rpPlayerBal * 100) / 100));
      techModalBody.innerHTML = `
        <div class="game-modal-grid tech-research-grid">
          <aside class="game-modal-col tech-modal-sidebar">
            <div class="section-title">Запасы науки</div>
            <div class="tech-rp-balance" id="tech-rp-bal">${rpRounded}</div>
            <div class="section-title" style="margin-top:14px;">Задачи исследований</div>
            <div id="tech-queue-panel" class="tech-queue-panel muted"></div>
            <div class="section-title" style="margin-top:14px;">Модификаторы</div>
            <div id="tech-sidebar-effects" class="tech-sidebar-effects muted"></div>
            <div class="section-title" style="margin-top:14px;">Поиск</div>
            <input type="search" id="tech-search" name="tech_search" class="tech-search" placeholder="Имя технологии…" autocomplete="off" value="${escAttr(searchDraft)}" />
            <div class="section-title" style="margin-top:12px;">Фильтр</div>
            <div class="tech-tabs tech-tabs-vertical" role="tablist">
              <button type="button" class="tech-tab${activeTab === "available" ? " is-active" : ""}" data-tech-tab="available">Можно начать</button>
              <button type="button" class="tech-tab${activeTab === "all" ? " is-active" : ""}" data-tech-tab="all">Все</button>
              <button type="button" class="tech-tab${activeTab === "done" ? " is-active" : ""}" data-tech-tab="done">Изучены</button>
            </div>
          </aside>
          <div class="game-modal-col tech-modal-main game-modal-col--state">
            <div id="tech-path-banner-slot" class="tech-path-banner-slot"></div>
            <div id="tech-modal-feedback" class="hud-action-feedback hud-action-feedback--in-modal" aria-live="polite" role="status" hidden></div>
            <div id="tech-modal-list" class="tech-modal-list"></div>
          </div>
          <div class="game-modal-col tech-modal-preview game-modal-col--state">
            <div class="section-title tech-preview-heading">Скоро доступно</div>
            <p class="tech-preview-hint muted">Откроется после перечисленных исследований; каждый шаг уже можно начать в центральной колонке.</p>
            <div id="tech-modal-preview-list" class="tech-modal-preview-list"></div>
          </div>
        </div>
      `;

      const effectsSidebar = techModalBody.querySelector("#tech-sidebar-effects");
      const renderSidebarEffects = () => {
        if (!effectsSidebar) return;
        const effects = effectsBody && Array.isArray(effectsBody.effects) ? effectsBody.effects : [];
        const lines = [];
        for (const e of effects) {
          if (!e || typeof e !== "object") continue;
          const t = String(e.effect_type || "");
          if (t === "bandit_ambush_cooldown") continue;
          if (t === "research_speed_boost") {
            const m = e.payload && typeof e.payload.time_multiplier === "number" ? e.payload.time_multiplier : 1.0;
            const pct = Math.max(0, Math.round((1.0 - m) * 100));
            const rem = Number.isInteger(e.remaining_ticks) ? e.remaining_ticks : null;
            lines.push(
              `Архив/телеметрия: исследования быстрее на ${pct}%${rem != null ? `, ещё ${rem} ${solWord(rem)}` : ""}`
            );
          } else if (t === "blueprint_cache") {
            lines.push("Кэш чертежей: скидка на следующий запуск");
          } else {
            lines.push(`Эффект: ${t.replace(/_/g, " ")}`);
          }
        }
        effectsSidebar.innerHTML =
          lines.length > 0
            ? `<ul class="tech-sidebar-effects-ul">${lines.map((x) => `<li>${escHtml(x)}</li>`).join("")}</ul>`
            : `<div class="muted" style="font-size:82%;">Нет внешних усилений</div>`;
      };
      renderSidebarEffects();
      fillTechQueuePanel();

      const searchInput = techModalBody.querySelector("#tech-search");

      for (const tabBtn of techModalBody.querySelectorAll("button[data-tech-tab]")) {
        tabBtn.addEventListener("click", () => {
          activeTab = tabBtn.getAttribute("data-tech-tab") || "available";
          writeTechUiPrefs({ tab: activeTab });
          for (const b of techModalBody.querySelectorAll("button[data-tech-tab]"))
            b.classList.toggle("is-active", b.getAttribute("data-tech-tab") === activeTab);
          paint(searchInput ? searchInput.value : "");
        });
      }
      const restoreTechModalScroll = (sk) => {
        if (!sk || !techModalBody) return;
        const go = () => {
          techModalBody.scrollTop = sk.body;
          const m = techModalBody.querySelector(".tech-modal-main");
          const l = techModalBody.querySelector("#tech-modal-list");
          const pv = techModalBody.querySelector("#tech-modal-preview-list");
          if (m) m.scrollTop = sk.main;
          if (l) l.scrollTop = sk.list;
          if (pv) pv.scrollTop = sk.preview ?? 0;
        };
        go();
        requestAnimationFrame(() => {
          go();
          requestAnimationFrame(go);
        });
      };

      if (searchInput) {
        searchInput.addEventListener("input", () => {
          writeTechUiPrefs({ search: searchInput.value });
          paint(searchInput.value);
        });
      }

      paint(searchDraft);
      restoreTechModalScroll(scrollKeep);
    } catch (_e) {
      techModalBody.innerHTML = "<div class='muted'>Ошибка загрузки исследований.</div>";
    }
  };

  /** Встроенные SVG для графического режима; при `false` графический режим откатывается к тактическим глифам. */
  const MAP_GRAPHIC_SVG_AVAILABLE = true;

  /** Растровые иконки карты 128×128 RGBA (`docs/art/map_128_white` → `static/img/map`); ключи совпадают с `MAP_GRAPHIC_SVG`. */
  const MAP_GRAPHIC_RASTER = {
    planet: "/static/img/map/planets/planet-rocky.png",
    asteroids: "/static/img/map/terrain-asteroids.png",
    nebula: "/static/img/map/terrain-nebula.png",
    ruins: "/static/img/map/terrain-ruins.png",
    ruinsSurveyed: "/static/img/map/terrain-ruins-surveyed.png",
    anomaly: "/static/img/map/terrain-anomaly.png",
    fogQ: "/static/img/map/terrain-fog-unknown.png",
    fleetFighter: "/static/img/map/fleet-fighter.png",
    fleetScout: "/static/img/map/fleet-scout.png",
    outpost: "/static/img/map/object-outpost.png",
    mine: "/static/img/map/building-mine.png",
    reactor: "/static/img/map/building-reactor.png",
    genericBuilding: "/static/img/map/building-generic.png",
  };

  /** Варианты спрайта планеты: выбор стабилен по координатам клетки (для «рандомайзера» без сервера). */
  const MAP_GRAPHIC_PLANET_VARIANTS = [
    "/static/img/map/planets/planet-rocky.png",
    "/static/img/map/planets/planet-gas.png",
    "/static/img/map/planets/planet-ice.png",
    "/static/img/map/planets/planet-ocean.png",
    "/static/img/map/planets/planet-desert.png",
  ];

  const pickPlanetGraphicRasterSrc = (cell) => {
    const arr = MAP_GRAPHIC_PLANET_VARIANTS;
    if (!arr.length) return MAP_GRAPHIC_RASTER.planet;
    const xq = Number.isFinite(Number(cell && cell.x)) ? Number(cell.x) : 0;
    const yq = Number.isFinite(Number(cell && cell.y)) ? Number(cell.y) : 0;
    const zq = Number.isFinite(Number(cell && cell.z)) ? Number(cell.z) : 0;
    const u =
      (Math.imul(xq, 73856093) ^ Math.imul(yq, 19349663) ^ Math.imul(zq, 83492791)) >>> 0;
    return arr[u % arr.length];
  };

  const getMapRenderOpts = () => {
    const s = loadUiSettings();
    const mapShowCoords = s.mapShowCoords !== false;
    const graphic = s.mapMode === "graphic" && MAP_GRAPHIC_SVG_AVAILABLE;
    return { graphic, mapShowCoords };
  };

  const MAP_GRAPHIC_SVG = {
    planet:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="1.75"/><ellipse cx="12" cy="12" rx="10" ry="3.2" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".55"/></svg>',
    asteroids:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><circle cx="8" cy="9" r="2.2" fill="currentColor"/><circle cx="14" cy="7" r="1.6" fill="currentColor" opacity=".85"/><circle cx="15" cy="14" r="2" fill="currentColor" opacity=".7"/><circle cx="10" cy="15" r="1.4" fill="currentColor" opacity=".55"/></svg>',
    nebula:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" d="M5 14c3-4 6-5 9-2s6 3 9-1M6 10c2.5-2 6-2 8 1"/><path fill="none" stroke="currentColor" stroke-width="1" opacity=".6" d="M7 17c3-2 5-1 8 1"/></svg>',
    ruins:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="currentColor" d="M8 18V10l2-4h4l2 4v8H8zm1-1h6v-3H9v3zm1-4h4v-2l-1-2h-2l-1 2v2z"/></svg>',
    ruinsSurveyed:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.65" d="M12 4l2.2 6.8H21l-5.5 4 2.1 6.7L12 17.5 6.4 21.5l2.1-6.7L3 10.8h6.8L12 4z"/></svg>',
    anomaly:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="2.2" fill="currentColor"/></svg>',
    fogQ:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 2.5"/></svg>',
    fleetFighter:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="currentColor" d="M12 4l6 14h-4l-1.2-3H11.2L10 18H6L12 4z"/></svg>',
    fleetScout:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.55" d="M12 5v7M8 9l4-2 4 2"/><rect x="9" y="13" width="6" height="5.5" rx="1.1" fill="none" stroke="currentColor" stroke-width="1.45"/><path fill="currentColor" d="M11 14.2h2v1.9h-2z"/></svg>',
    outpost:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><rect x="6" y="7" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.75"/><path fill="currentColor" opacity=".35" d="M8 9h8v2H8z"/></svg>',
    mine:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="currentColor" d="M11 4h2l1 3h2l-6 9H6l6-9H10l1-3zm0 11l-2 3h6l-2-3h-2z"/></svg>',
    reactor:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path fill="none" stroke="currentColor" stroke-width="1.35" d="M12 4.5v3M12 16.5v3M4.5 12h3M16.5 12h3M6.8 6.8l2.1 2.1M15.1 15.1l2.1 2.1M17.2 6.8l-2.1 2.1M8.9 15.1l-2.1 2.1"/></svg>',
    genericBuilding:
      '<svg class="map-cell-icon" viewBox="0 0 24 24" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.7" d="M12 5l6.5 6H17v8H7v-8H5.5L12 5z"/></svg>',
  };

  const mapGraphicFromKey = (tone, key, rasterSrcOverride, wrapExtraClass) => {
    const extra =
      wrapExtraClass && String(wrapExtraClass).trim().length > 0
        ? ` ${String(wrapExtraClass).trim()}`
        : "";
    const wrapOpen = `<span class="map-cell-icon-wrap map-cell-icon-tone-${tone}${extra}" aria-hidden="true">`;
    let src = MAP_GRAPHIC_RASTER[key];
    if (rasterSrcOverride != null && String(rasterSrcOverride).length > 0) {
      src = String(rasterSrcOverride);
    }
    if (src) {
      const u = escAttr(src);
      return `${wrapOpen}<img class="map-cell-icon map-cell-icon--raster" src="${u}" alt="" decoding="async" loading="lazy" /></span>`;
    }
    const svgInner = MAP_GRAPHIC_SVG[key];
    return svgInner ? `${wrapOpen}${svgInner}</span>` : null;
  };

  const buildGraphicMapMarker = (ctx) => {
    if (!MAP_GRAPHIC_SVG_AVAILABLE) return null;
    const {
      c,
      playerId,
      isHomeCell,
      planetObj,
      isEnemyPlanet,
      anyFleetObj,
      isEnemyFleet,
      hasAnyFleet,
      isFromCell,
      outpostObj,
      buildingObj,
      rsRuins,
    } = ctx;
    const T_SELF = "self";
    const T_ENEMY = "enemy";
    const T_NEUTRAL = "neutral";
    const T_FOG = "fog";

    if (planetObj || isHomeCell) {
      let t = T_NEUTRAL;
      if (isEnemyPlanet) t = T_ENEMY;
      else if (
        planetObj &&
        playerId &&
        planetObj.owner &&
        String(planetObj.owner) === String(playerId)
      )
        t = T_SELF;
      else if (isHomeCell) t = T_SELF;
      const planetHtml = mapGraphicFromKey(
        t,
        "planet",
        pickPlanetGraphicRasterSrc(c),
        "map-cell-icon-wrap--planet-scale",
      );
      if (hasAnyFleet && anyFleetObj && !isFromCell) {
        const ft = isEnemyFleet ? T_ENEMY : T_SELF;
        const isFighter = fleetMapGraphicIsCombatDominant(anyFleetObj.unit_type);
        const flHtml = mapGraphicFromKey(ft, isFighter ? "fleetFighter" : "fleetScout");
        return `<span class="map-graphic-stack map-graphic-stack--planet-fleet" aria-hidden="true">${planetHtml}${flHtml}</span>`;
      }
      return planetHtml;
    }
    if (hasAnyFleet && anyFleetObj && !isFromCell) {
      const ft = isEnemyFleet ? T_ENEMY : T_SELF;
      const isFighter = fleetMapGraphicIsCombatDominant(anyFleetObj.unit_type);
      return mapGraphicFromKey(ft, isFighter ? "fleetFighter" : "fleetScout");
    }
    if (outpostObj) {
      const t = playerId && String(outpostObj.owner) === String(playerId) ? T_SELF : T_ENEMY;
      return mapGraphicFromKey(t, "outpost");
    }
    if (buildingObj) {
      const t = playerId && String(buildingObj.owner) === String(playerId) ? T_SELF : T_ENEMY;
      const bCls = "map-cell-icon-wrap--field-building";
      if (buildingObj.building_type === "mine") return mapGraphicFromKey(t, "mine", null, bCls);
      if (buildingObj.building_type === "reactor") return mapGraphicFromKey(t, "reactor", null, bCls);
      return mapGraphicFromKey(t, "genericBuilding", null, bCls);
    }
    if (c.terrain === "planet")
      return mapGraphicFromKey(
        T_NEUTRAL,
        "planet",
        pickPlanetGraphicRasterSrc(c),
        "map-cell-icon-wrap--planet-scale",
      );
    if (c.terrain === "asteroids") return mapGraphicFromKey(T_NEUTRAL, "asteroids");
    if (c.terrain === "nebula") return mapGraphicFromKey(T_NEUTRAL, "nebula");
    if (c.terrain === "ruins" && rsRuins) return mapGraphicFromKey(T_NEUTRAL, "ruinsSurveyed");
    if (c.terrain === "ruins") return mapGraphicFromKey(T_NEUTRAL, "ruins");
    if (c.terrain === "anomaly") return mapGraphicFromKey(T_NEUTRAL, "anomaly");
    if (c.terrain === "fog" && c.glyph === "?") return mapGraphicFromKey(T_FOG, "fogQ");
    return null;
  };

  /** Размеры клетки по осям: сетка gridW×gridH заполняет прямоугольник `.map-wrap` без прокрутки (ширина и высота независимо). */
  const computeMapLayoutCellsPx = (gridW, gridH) => {
    const gw = Math.max(1, Number(gridW) || 1);
    const gh = Math.max(1, Number(gridH) || 1);
    const size = Math.max(gw, gh);
    const minC = 22;
    const maxC = 140;
    const baseCell =
      Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--cell-size"), 10) || 96;
    const refCells = 13;
    const fallbackSq = Math.max(minC, Math.min(baseCell, Math.round((baseCell * refCells) / size)));
    const w = mapWrapEl ? mapWrapEl.clientWidth : 0;
    const h = mapWrapEl ? mapWrapEl.clientHeight : 0;
    if (!w || !h || w < size * minC || h < size * minC) return { cw: fallbackSq, ch: fallbackSq };
    const slotW = Math.max(0, w - 6);
    const slotH = Math.max(0, h - 6);
    const byW = Math.floor(slotW / gw);
    const byH = Math.floor(slotH / gh);
    return {
      cw: Math.max(minC, Math.min(maxC, byW)),
      ch: Math.max(minC, Math.min(maxC, byH)),
    };
  };

  const readMapLayoutDimsFromCss = () => {
    const fb =
      Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--cell-size"), 10) || 96;
    if (!mapEl) return { cw: fb, ch: fb };
    const st = getComputedStyle(mapEl);
    const cw = Number.parseInt(st.getPropertyValue("--map-layout-cell-w"), 10);
    const ch = Number.parseInt(st.getPropertyValue("--map-layout-cell-h"), 10);
    return { cw: Number.isFinite(cw) && cw > 0 ? cw : fb, ch: Number.isFinite(ch) && ch > 0 ? ch : fb };
  };

  const renderMap = () => {
    if (!mapEl || !currentWindow || !currentWindow.cells) return;
    const mapOpts = getMapRenderOpts();
    const span = mapWindowGridSpan(currentWindow);
    const size = Math.max(span.w, span.h);
    mapEl.innerHTML = "";
    mapEl.style.setProperty("--map-size", String(Math.max(span.w, 1)));
    mapEl.classList.toggle("map-hex", currentWindow.topology === "hex");
    mapEl.classList.toggle("map-mode-graphic", mapOpts.graphic);
    mapEl.classList.toggle("map-mode-tactical", !mapOpts.graphic);
    mapEl.classList.toggle("map-hide-coords", !mapOpts.mapShowCoords);
    let dims = computeMapLayoutCellsPx(span.w, span.h);
    let hexS = null;
    /** Мин. экранный x = hexS·√3·(q + r/2) по окну — для padding рядов (pointy-top axial). */
    let hexGlobalMinX = 0;
    if (currentWindow.topology === "hex") {
      const vY = MAP_HEX_VERTICAL_COMPRESS;
      hexS = Math.min(dims.cw / SQRT3, dims.ch / (2 * vY));
      hexS = Math.max(14, hexS);
      dims = { cw: hexS * SQRT3, ch: 2 * hexS * vY };
      const maxCellPx = 140;
      const hexBBoxPx = (s) => {
        const cw0 = s * SQRT3;
        let gmin = Infinity;
        for (const rw of currentWindow.cells) {
          for (const c of rw.row || []) {
            const u = c.x + c.y / 2;
            if (u < gmin) gmin = u;
          }
        }
        if (!Number.isFinite(gmin)) return { w: 0, h: 0 };
        const base = s * SQRT3 * gmin;
        let xmax = -Infinity;
        for (const rw of currentWindow.cells) {
          for (const c of rw.row || []) {
            const right = s * SQRT3 * (c.x + c.y / 2) + cw0 - base;
            if (right > xmax) xmax = right;
          }
        }
        const nrows = currentWindow.cells.length;
        const hPx = s * vY * (2 + 1.5 * Math.max(0, nrows - 1));
        return { w: Math.max(0, xmax), h: hPx };
      };
      if (mapWrapEl) {
        const pad = 10;
        const sw = Math.max(0, mapWrapEl.clientWidth - pad);
        const sh = Math.max(0, mapWrapEl.clientHeight - pad);
        const bbox0 = hexBBoxPx(hexS);
        if (bbox0.w > 0 && bbox0.h > 0 && sw > 0 && sh > 0) {
          let scale = sw / bbox0.w;
          if (bbox0.h * scale > sh) scale = sh / bbox0.h;
          if (scale > 1.02) {
            const maxS = Math.min(maxCellPx / SQRT3, maxCellPx / (2 * vY));
            let s2 = hexS * scale;
            s2 = Math.min(s2, maxS);
            s2 = Math.max(14, s2);
            hexS = s2;
            dims = { cw: hexS * SQRT3, ch: 2 * hexS * vY };
          }
        }
      }
      hexGlobalMinX = Infinity;
      for (const rw of currentWindow.cells) {
        for (const c of rw.row || []) {
          const xPx = hexS * SQRT3 * (c.x + c.y / 2);
          if (xPx < hexGlobalMinX) hexGlobalMinX = xPx;
        }
      }
      if (!Number.isFinite(hexGlobalMinX)) hexGlobalMinX = 0;
    }
    mapEl.style.setProperty("--map-layout-cell-w", `${dims.cw}px`);
    mapEl.style.setProperty("--map-layout-cell-h", `${dims.ch}px`);

    const scout = detectScoutPos();
    if (unitPosEl) unitPosEl.textContent = `${scout.x}, ${scout.y}, ${scout.z}`;
    if (zEl) zEl.textContent = String(currentZ);

    let hexRowIdx = 0;
    for (const row of currentWindow.cells) {
      const rowEl = document.createElement("div");
      const rowR = Number(row.y);
      rowEl.className = currentWindow.topology === "hex" ? "map-row map-hex-row" : "map-row";
      if (currentWindow.topology === "hex" && hexS != null) {
        rowEl.style.display = "flex";
        rowEl.style.flexDirection = "row";
        rowEl.style.flexWrap = "nowrap";
        rowEl.style.justifyContent = "flex-start";
        rowEl.style.alignItems = "center";
        let qMinRow = Infinity;
        for (const c of row.row || []) {
          if (c.x < qMinRow) qMinRow = c.x;
        }
        if (!Number.isFinite(qMinRow)) qMinRow = 0;
        const padLeft = hexS * SQRT3 * (qMinRow + rowR / 2) - hexGlobalMinX;
        rowEl.style.paddingLeft = `${Math.max(0, padLeft)}px`;
        if (hexRowIdx > 0) {
          rowEl.style.marginTop = `${-(dims.ch - 1.5 * hexS * MAP_HEX_VERTICAL_COMPRESS)}px`;
        }
        hexRowIdx += 1;
      }
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
          if (!mapCellHasMeaningfulContent(c)) btn.classList.add("cell-empty-visible");
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

        const ct = c.flags && c.flags.cell_tint ? String(c.flags.cell_tint) : "";
        if (ct === "ally") btn.classList.add("cell-tint-ally");
        else if (ct === "hostile") btn.classList.add("cell-tint-hostile");
        else if (ct === "neutral") btn.classList.add("cell-tint-neutral");
        else if (ct === "ruins_surveyed") btn.classList.add("cell-tint-ruins-surveyed");

        const rsRuins = Boolean(c.flags && c.flags.ruins_surveyed);
        const terrainIcon =
          c.terrain === "planet"
            ? "<span class='terrain-icon'>🪐</span>"
            :
          c.terrain === "asteroids"
            ? "<span class='terrain-icon'>☄</span>"
            : c.terrain === "nebula"
              ? "<span class='terrain-icon' aria-label='Туманность'>≋</span>"
              : c.terrain === "ruins" && rsRuins
                ? "<span class='terrain-icon terrain-ruins-surveyed' aria-label='Исследованные руины'>◈</span>"
              : c.terrain === "ruins"
                ? "<span class='terrain-icon' aria-label='Руины'>⟁</span>"
                : c.terrain === "anomaly"
                  ? "<span class='terrain-icon' aria-label='Аномалия'>◎</span>"
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

        const fleetIcon =
          anyFleetObj && fleetMapGraphicIsCombatDominant(anyFleetObj.unit_type) ? "🚀" : "🛰";
        const fleetMarker = hasAnyFleet && !isFromCell
          ? `<span class='unit-icon ${isEnemyFleet ? "enemy" : "ally"}' aria-label='Флот'>${fleetIcon}</span>`
          : null;

        // Центр окна — это только рамка (cell-center), не "планета".
        const outpostMarker = outpostObj
          ? `<span class="terrain-icon ${String(outpostObj.owner) === String(playerId) ? "outpost-ally" : "outpost-hostile"}" aria-label="Форпост">▣</span>`
          : null;

        const buildingMarker = buildingObj
          ? `<span class="terrain-icon ${String(buildingObj.owner) === String(playerId) ? "building-ally" : "building-hostile"}" aria-label="Постройка">${buildingObj.building_type === "mine" ? "⛏" : (buildingObj.building_type === "reactor" ? "⚙" : "◇")}</span>`
          : null;

        const tacticalStack = [];
        if (terrainIcon && !planetMarker) tacticalStack.push(terrainIcon);
        if (planetMarker) tacticalStack.push(planetMarker);
        if (outpostMarker) tacticalStack.push(outpostMarker);
        if (buildingMarker) tacticalStack.push(buildingMarker);
        if (fleetMarker) tacticalStack.push(fleetMarker);
        const tacticalMarkerInner = tacticalStack.length ? tacticalStack.join("") : null;
        const tacticalMarker =
          tacticalStack.length > 1
            ? `<span class="map-marker-stack">${tacticalMarkerInner}</span>`
            : tacticalMarkerInner;
        const graphicMarker = mapOpts.graphic
          ? buildGraphicMapMarker({
              c,
              playerId,
              isHomeCell,
              planetObj,
              isEnemyPlanet,
              anyFleetObj,
              isEnemyFleet,
              hasAnyFleet,
              isFromCell,
              outpostObj,
              buildingObj,
              rsRuins,
            })
          : null;
        const marker = graphicMarker || tacticalMarker;
        const markerHtml = marker ? `<div>${marker}</div>` : "<div class='marker-spacer'></div>";
        const showCoord =
          mapOpts.mapShowCoords && Boolean(hasObjects || tacticalMarker);
        const coordHtml = showCoord ? `<div class='coord'>${c.x},${c.y}</div>` : "<div class='coord'></div>";

        // Клики по краям окна двигают карту. Стрелки рисуем поверх содержимого клетки.
        const winCenter = currentWindow && currentWindow.center ? currentWindow.center : viewCenter;
        const r = clampMapWindowRadius(
          currentWindow && Number.isInteger(currentWindow.radius) ? currentWindow.radius : MAP_WINDOW_RADIUS_MIN
        );
        const isHexWin = currentWindow.topology === "hex";
        const isEdgeHex =
          isHexWin && jsHexDistance(c.x, c.y, winCenter.x, winCenter.y) === r;
        const isLeft = c.x === winCenter.x - r;
        const isRight = c.x === winCenter.x + r;
        const isTop = c.y === winCenter.y - r;
        const isBottom = c.y === winCenter.y + r;
        const isEdge = isHexWin ? isEdgeHex : isLeft || isRight || isTop || isBottom;
        let arrow = "";
        if (isEdge) {
          if (isHexWin) {
            arrow = hexPanArrow(c.x, c.y, winCenter.x, winCenter.y);
          } else if (isLeft && isTop) arrow = "↖";
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

        if (isHexWin && arrow && hexS != null) {
          const dqx = c.x - winCenter.x;
          const dqy = c.y - winCenter.y;
          const sx = SQRT3 * (dqx + dqy / 2);
          const sy = (3 / 2) * dqy;
          const sl = Math.hypot(sx, sy) || 1;
          const push = Math.min(Math.max(8, hexS * 0.52), dims.cw * 0.3);
          btn.style.setProperty("--pan-tx", `${((sx / sl) * push).toFixed(1)}px`);
          btn.style.setProperty("--pan-ty", `${((sy / sl) * push).toFixed(1)}px`);
        } else {
          btn.style.removeProperty("--pan-tx");
          btn.style.removeProperty("--pan-ty");
        }

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
              const stackOthers = (c.objects || []).filter(
                (o) =>
                  o &&
                  o.type === "fleet" &&
                  o.owner != null &&
                  String(o.owner) === String(playerId) &&
                  String(o.id) !== String(data.fleet_id),
              );
              if (stackOthers.length > 0) {
                await openFleetStackingChoiceModal({
                  draggedFleetId: String(data.fleet_id),
                  targetFleetId: String(stackOthers[0].id),
                  targetPos: { x: c.x, y: c.y, z: c.z },
                });
                return;
              }
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

        // Край окна: панорама; если в клетке есть объекты/непустой террейн — первый клик только выбор, второй — сдвиг.
        btn.addEventListener("click", () => {
          const cellKey = `${c.x},${c.y},${c.z ?? 0}`;
          if (isEdge) {
            if (mapCellHasMeaningfulContent(c)) {
              if (lastEdgePanCellKey !== cellKey) {
                lastEdgePanCellKey = cellKey;
                applyMapCellSelection(c);
                return;
              }
              lastEdgePanCellKey = null;
            } else {
              lastEdgePanCellKey = null;
            }
            if (isHexWin) {
              viewCenter = { x: c.x, y: c.y };
            } else {
              const step = r * 2; // двигаемся "окнами" без перекрытия
              const dx = isLeft ? -step : isRight ? step : 0;
              const dy = isTop ? -step : isBottom ? step : 0;
              viewCenter = { x: winCenter.x + dx, y: winCenter.y + dy };
            }
            void refreshWindow();
            return;
          }
          lastEdgePanCellKey = null;
          applyMapCellSelection(c);
        });
        rowEl.appendChild(btn);
      }
      mapEl.appendChild(rowEl);
    }
    syncMapLayerElBoxFromGrid();
    renderFlightOverlay();
  };

  /**
   * Пиксельный размер `.map-layer` для SVG: для гекса нельзя брать max(span)×клетка —
   * ряды со сдвигом (paddingLeft) дают больший bbox, иначе слой сжимается, оверлеи «рвутся».
   */
  const mapLayerPixelRect = (span, cellWpx, cellHpx) => {
    const size = Math.max(span.w, span.h);
    let w = size * cellWpx;
    let h = size * cellHpx;
    if (currentWindow && currentWindow.topology === "hex" && mapEl) {
      // При узком `.map-layer` блок может иметь offset* = ширине родителя; scroll* — полный bbox гекса.
      const ow = Math.max(mapEl.offsetWidth, mapEl.scrollWidth);
      const oh = Math.max(mapEl.offsetHeight, mapEl.scrollHeight);
      if (ow > 0 && oh > 0) {
        w = ow;
        h = oh;
      }
    }
    return { w, h };
  };

  /** Выставить `.map-layer` по фактическому bbox сетки (до SVG с `inset:0`, иначе оверлей сжимается). */
  const syncMapLayerElBoxFromGrid = () => {
    if (!mapLayerEl || !mapEl || !currentWindow || !currentWindow.cells) return;
    const span = mapWindowGridSpan(currentWindow);
    const { cw, ch } = readMapLayoutDimsFromCss();
    const { w, h } = mapLayerPixelRect(span, cw, ch);
    mapLayerEl.style.width = `${w}px`;
    mapLayerEl.style.height = `${h}px`;
  };

  /** Центр клетки в системе координат SVG внутри `.map-layer` (как у zone-overlay). */
  const getCellCenterInLayerSpace = (x, y, z) => {
    if (!mapEl || !mapLayerEl) return null;
    const el = mapEl.querySelector(`button.cell[data-x='${x}'][data-y='${y}'][data-z='${z}']`);
    if (!el) return null;
    const layerRect = mapLayerEl.getBoundingClientRect();
    const cellRect = el.getBoundingClientRect();
    if (!layerRect.width && !layerRect.height) return null;
    return {
      cx: cellRect.left - layerRect.left + cellRect.width / 2,
      cy: cellRect.top - layerRect.top + cellRect.height / 2,
    };
  };

  const renderFlightOverlay = () => {
    if (!flightOverlayEl || !mapEl || !mapLayerEl || !currentWindow || !currentWindow.cells) return;
    // clear
    flightOverlayEl.innerHTML = "";

    const span = mapWindowGridSpan(currentWindow);
    const { cw: cellWPx, ch: cellHPx } = readMapLayoutDimsFromCss();
    const { w: W, h: H } = mapLayerPixelRect(span, cellWPx, cellHPx);
    flightOverlayEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
    flightOverlayEl.setAttribute("width", String(W));
    flightOverlayEl.setAttribute("height", String(H));

    const ns = "http://www.w3.org/2000/svg";

    const fleets = worldState && Array.isArray(worldState.fleets)
      ? worldState.fleets
      : (worldState && worldState.fleet ? [worldState.fleet] : []);

    const moving = fleets.filter((f) => f && f.status === "moving" && f.active_order);
    if (!moving.length) return;

    for (const f of moving) {
      const ao = f.active_order;
      const from = getCellCenterInLayerSpace(ao.from_x, ao.from_y, ao.from_z ?? 0);
      const to = getCellCenterInLayerSpace(ao.target_x, ao.target_y, ao.target_z ?? 0);
      if (!from || !to) continue;

      const travelTicks = Number.isInteger(ao.travel_ticks)
        ? ao.travel_ticks
        : Math.max(1, jsHexDistance(ao.target_x, ao.target_y, ao.from_x, ao.from_y));
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
      dot.setAttribute("r", String(Math.max(4, Math.round(Math.min(cellWPx, cellHPx) * 0.07))));
      dot.setAttribute("class", isEmergency ? "flight-dot flight-dot-emergency" : "flight-dot");

      flightOverlayEl.appendChild(line);
      flightOverlayEl.appendChild(dot);
    }
  };

  const renderZoneOverlay = () => {
    if (!zoneOverlayEl || !mapEl || !mapLayerEl || !currentWindow || !currentWindow.cells) return;
    const span = mapWindowGridSpan(currentWindow);
    const { cw: cellWpx, ch: cellHpx } = readMapLayoutDimsFromCss();
    // Сначала размер слоя — иначе getBoundingClientRect и scroll* дают несогласованные цифры.
    syncMapLayerElBoxFromGrid();
    const { w: mapWpx, h: mapHpx } = mapLayerPixelRect(span, cellWpx, cellHpx);

    // overlay — в тех же px, что и сетка
    zoneOverlayEl.setAttribute("viewBox", `0 0 ${mapWpx} ${mapHpx}`);
    zoneOverlayEl.setAttribute("width", String(mapWpx));
    zoneOverlayEl.setAttribute("height", String(mapHpx));
    zoneOverlayEl.innerHTML = "";

    const ns = "http://www.w3.org/2000/svg";

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
        if (currentWindow.topology === "hex") {
          for (let dq = -r; dq <= r; dq++) {
            for (let dr = -r; dr <= r; dr++) {
              const x = p.x + dq;
              const y = p.y + dr;
              if (jsHexDistance(x, y, p.x, p.y) <= r) inBuild.add(cellIndexKey(x, y, p.z ?? 0));
            }
          }
        } else {
          for (let dy = -r; dy <= r; dy++) {
            for (let dx = -r; dx <= r; dx++) {
              if (Math.abs(dx) + Math.abs(dy) > r) continue;
              inBuild.add(cellIndexKey(p.x + dx, p.y + dy, p.z ?? 0));
            }
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

          const x0 = xi * cellWpx;
          const y0 = yi * cellHpx;
          const x1 = x0 + cellWpx;
          const y1 = y0 + cellHpx;

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

    const smoothClosedPathD = (pts, r, edgeCapMul) => {
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
        const capMul = typeof edgeCapMul === "number" && edgeCapMul > 0 ? edgeCapMul : 0.58;
        const rr = clamp(radius, 0, Math.min(d1, d2) * capMul);

        const p1 = lerp(cur, prev, rr / d1);
        const p2 = lerp(cur, next, rr / d2);

        d += ` L ${p1.x} ${p1.y}`;
        d += ` Q ${cur.x} ${cur.y} ${p2.x} ${p2.y}`;
      }
      d += " Z";
      return d;
    };

    const hexNeighborOffsetLayerPx = (dq, dr, cw, _ch) => {
      const S = cw / SQRT3;
      const x = S * SQRT3 * (dq + dr / 2);
      const y = S * (3 / 2) * dr * MAP_HEX_VERTICAL_COMPRESS;
      return { x, y };
    };

    const AXIAL_HEX_DIRS_OVERLAY = [
      [1, 0],
      [1, -1],
      [0, -1],
      [-1, 0],
      [-1, 1],
      [0, 1],
    ];

    /** 6 вершин clip-path гекса в px слоя `.map-layer` (как у кнопки `.cell`). */
    const hexCellCornersInLayerSpace = (x, y, z) => {
      if (!mapEl || !mapLayerEl) return null;
      const el = mapEl.querySelector(`button.cell[data-x='${x}'][data-y='${y}'][data-z='${z}']`);
      if (!el) return null;
      const layerRect = mapLayerEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const w = r.width;
      const h = r.height;
      if (!(w > 0 && h > 0)) return null;
      const left = r.left - layerRect.left;
      const top = r.top - layerRect.top;
      const corners = [
        { x: left + w * 0.5, y: top },
        { x: left + w, y: top + h * 0.25 },
        { x: left + w, y: top + h * 0.75 },
        { x: left + w * 0.5, y: top + h },
        { x: left, y: top + h * 0.75 },
        { x: left, y: top + h * 0.25 },
      ];
      return { corners, cx: left + w / 2, cy: top + h / 2 };
    };

    /** Ребро шестиугольника, «смотрящее» на соседа (центр соседа — внутри или синтетический). */
    const hexBoundaryEdgeForOutsideNeighbor = (corners, cx, cy, tgx, tgy) => {
      if (!corners || corners.length < 3) return null;
      const ux = tgx - cx;
      const uy = tgy - cy;
      const ulen = Math.hypot(ux, uy);
      if (ulen < 1e-6) return null;
      const uxn = ux / ulen;
      const uyn = uy / ulen;
      let bestDot = -Infinity;
      let ax;
      let ay;
      let bx;
      let by;
      for (let i = 0; i < corners.length; i++) {
        const p0 = corners[i];
        const p1 = corners[(i + 1) % corners.length];
        const mx = (p0.x + p1.x) / 2;
        const my = (p0.y + p1.y) / 2;
        const vx = mx - cx;
        const vy = my - cy;
        const vlen = Math.hypot(vx, vy) || 1;
        const dot = (vx / vlen) * uxn + (vy / vlen) * uyn;
        if (dot > bestDot) {
          bestDot = dot;
          ax = p0.x;
          ay = p0.y;
          bx = p1.x;
          by = p1.y;
        }
      }
      if (!(Number.isFinite(ax) && Number.isFinite(ay) && Number.isFinite(bx) && Number.isFinite(by))) return null;
      return [ax, ay, bx, by];
    };

    const collectHexEdges = (zoneSet) => {
      const posMap = new Map();
      const geoCache = new Map();
      for (let yi = 0; yi < rows.length; yi++) {
        const row = rows[yi].row;
        for (let xi = 0; xi < row.length; xi++) {
          const c = row[xi];
          const z0 = c.z ?? 0;
          const pt = getCellCenterInLayerSpace(c.x, c.y, z0);
          if (pt) posMap.set(cellIndexKey(c.x, c.y, z0), pt);
        }
      }
      const cornersCached = (x, y, z) => {
        const k0 = cellIndexKey(x, y, z);
        if (geoCache.has(k0)) return geoCache.get(k0);
        const g = hexCellCornersInLayerSpace(x, y, z);
        geoCache.set(k0, g);
        return g;
      };
      const segs = [];
      for (let yi = 0; yi < rows.length; yi++) {
        const row = rows[yi].row;
        for (let xi = 0; xi < row.length; xi++) {
          const c = row[xi];
          const z0 = c.z ?? 0;
          const k = cellIndexKey(c.x, c.y, z0);
          if (!zoneSet.has(k)) continue;
          const center = posMap.get(k);
          if (!center) continue;
          const geo = cornersCached(c.x, c.y, z0);
          for (const [dq, dr] of AXIAL_HEX_DIRS_OVERLAY) {
            const nk = cellIndexKey(c.x + dq, c.y + dr, z0);
            if (zoneSet.has(nk)) continue;
            const nb = posMap.get(nk);
            let nbcx;
            let nbcy;
            if (nb) {
              nbcx = nb.cx;
              nbcy = nb.cy;
            } else {
              const off = hexNeighborOffsetLayerPx(dq, dr, cellWpx, cellHpx);
              nbcx = center.cx + off.x;
              nbcy = center.cy + off.y;
            }
            if (geo && Array.isArray(geo.corners)) {
              const seg = hexBoundaryEdgeForOutsideNeighbor(geo.corners, geo.cx, geo.cy, nbcx, nbcy);
              if (seg) {
                segs.push(seg);
                continue;
              }
            }
            const mx = (center.cx + nbcx) / 2;
            const my = (center.cy + nbcy) / 2;
            const vx = nbcx - center.cx;
            const vy = nbcy - center.cy;
            const len = Math.hypot(vx, vy) || 1;
            const px = -vy / len;
            const py = vx / len;
            const vY = MAP_HEX_VERTICAL_COMPRESS;
            const hexSidePx = Math.min(cellWpx / SQRT3, cellHpx / (2 * vY));
            const half = hexSidePx / 2;
            segs.push([mx - px * half, my - py * half, mx + px * half, my + py * half]);
          }
        }
      }
      return segs;
    };

    const collectEdgesForTopology = (zoneSet) =>
      currentWindow.topology === "hex" ? collectHexEdges(zoneSet) : collectEdges(zoneSet);

    /** Сборка замкнутых контуров из отрезков гекс-границы (со снаппингом точек — иначе граф не замыкается из‑за float). */
    const hexBoundarySegmentsToLoops = (rawSegs) => {
      const SNAP = 3;
      const snap = (v) => Math.round(Number(v) / SNAP) * SNAP;
      const pk = (x, y) => `${snap(x)},${snap(y)}`;
      const segs = [];
      for (const [x1, y1, x2, y2] of rawSegs) {
        const ax = snap(x1);
        const ay = snap(y1);
        const bx = snap(x2);
        const by = snap(y2);
        if (ax === bx && ay === by) continue;
        segs.push({ ax, ay, bx, by });
      }
      const adj = new Map();
      const addAdj = (x1, y1, x2, y2, i) => {
        const k = pk(x1, y1);
        if (!adj.has(k)) adj.set(k, []);
        adj.get(k).push({ i, x: x2, y: y2 });
      };
      for (let i = 0; i < segs.length; i++) {
        const s = segs[i];
        addAdj(s.ax, s.ay, s.bx, s.by, i);
        addAdj(s.bx, s.by, s.ax, s.ay, i);
      }
      const used = new Set();
      const loops = [];
      for (let i = 0; i < segs.length; i++) {
        if (used.has(i)) continue;
        const s0 = segs[i];
        used.add(i);
        const sx = s0.ax;
        const sy = s0.ay;
        let cx = s0.bx;
        let cy = s0.by;
        let px = sx;
        let py = sy;
        const pts = [{ x: sx, y: sy }, { x: cx, y: cy }];
        for (let guard = 0; guard < 25000; guard++) {
          const options = (adj.get(pk(cx, cy)) || []).filter((o) => !used.has(o.i));
          if (!options.length) break;
          const nxt = options.find((o) => !(o.x === px && o.y === py)) || options[0];
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

    const dedupeHexBorderSegments = (segs) => {
      const q = (v) => Math.round(Number(v));
      const edgeKey = (x1, y1, x2, y2) => {
        const a = `${q(x1)},${q(y1)}`;
        const b = `${q(x2)},${q(y2)}`;
        return a < b ? `${a}|${b}` : `${b}|${a}`;
      };
      const seen = new Set();
      const out = [];
      for (const s of segs) {
        const k = edgeKey(s[0], s[1], s[2], s[3]);
        if (seen.has(k)) continue;
        seen.add(k);
        out.push(s);
      }
      return out;
    };

    /** Chaikin по замкнутому контуру — срезает «пилу» из мелких гекс-рёбер до крупных плавных дуг. */
    const chaikinClosedLoop = (pts, iterations) => {
      let ring = pts.slice();
      if (ring.length >= 2) {
        const a = ring[0];
        const b = ring[ring.length - 1];
        if (Math.hypot(a.x - b.x, a.y - b.y) < 1e-3) ring = ring.slice(0, -1);
      }
      if (ring.length < 3) return pts;
      const iters = Math.max(1, Math.min(4, iterations === undefined ? 2 : iterations));
      for (let iter = 0; iter < iters; iter++) {
        const next = [];
        const n = ring.length;
        for (let i = 0; i < n; i++) {
          const p0 = ring[i];
          const p1 = ring[(i + 1) % n];
          next.push(
            { x: 0.75 * p0.x + 0.25 * p1.x, y: 0.75 * p0.y + 0.25 * p1.y },
            { x: 0.25 * p0.x + 0.75 * p1.x, y: 0.25 * p0.y + 0.75 * p1.y },
          );
        }
        ring = next;
      }
      ring.push({ ...ring[0] });
      return ring;
    };

    const drawBorder = (zoneSet, klass) => {
      const segs = collectEdgesForTopology(zoneSet);
      const isHex = currentWindow.topology === "hex";
      if (isHex) {
        const uniq = dedupeHexBorderSegments(segs);
        const loops = hexBoundarySegmentsToLoops(uniq);
        const joinR = Math.max(16, Math.min(cellWpx, cellHpx) * 0.48);
        if (loops.length) {
          for (const loop of loops) {
            const path = document.createElementNS(ns, "path");
            const softened = chaikinClosedLoop(loop, 3);
            path.setAttribute("d", smoothClosedPathD(softened, joinR, 0.84));
            path.setAttribute("class", `${klass} zone-line-hex-smooth`);
            zoneOverlayEl.appendChild(path);
          }
        } else {
          for (const [x1, y1, x2, y2] of uniq) {
            const line = document.createElementNS(ns, "line");
            line.setAttribute("x1", String(x1));
            line.setAttribute("y1", String(y1));
            line.setAttribute("x2", String(x2));
            line.setAttribute("y2", String(y2));
            line.setAttribute("class", `${klass} zone-line-hex-fallback`);
            zoneOverlayEl.appendChild(line);
          }
        }
        return;
      }
      const loops = segmentsToLoops(segs);
      const radius = Math.max(6, Math.round(Math.min(cellWpx, cellHpx) * 0.22));
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

  const applyMapCellSizeFromContainer = () => {
    if (!mapEl || !currentWindow || !currentWindow.cells) return;
    // Гекс: размеры и масштаб считаются только в `renderMap` (bbox, MAP_HEX_VERTICAL_COMPRESS).
    // Иначе здесь подставляется «квадратная» сетка 13×13 → краткий кадр с полосой/искажением и мигание.
    if (currentWindow.topology === "hex") {
      renderMap();
      renderZoneOverlay();
      syncMmoSidePanelHeights();
      return;
    }
    const span = mapWindowGridSpan(currentWindow);
    const d = computeMapLayoutCellsPx(span.w, span.h);
    mapEl.style.setProperty("--map-layout-cell-w", `${d.cw}px`);
    mapEl.style.setProperty("--map-layout-cell-h", `${d.ch}px`);
    renderZoneOverlay();
    renderFlightOverlay();
    syncMmoSidePanelHeights();
  };

  if (mapWrapEl && typeof ResizeObserver !== "undefined") {
    let mapResizeTimer = null;
    new ResizeObserver(() => {
      clearTimeout(mapResizeTimer);
      mapResizeTimer = setTimeout(() => applyMapCellSizeFromContainer(), 60);
    }).observe(mapWrapEl);
  }

  if (mapSectorCard && typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => syncMmoSidePanelHeights()).observe(mapSectorCard);
  }

  // drag-pan removed

  const refreshWindow = async () => {
    const run = async () => {
      try {
        const fog =
          playerIsGameAdmin && loadUiSettings().revealFogAdmin ? "&reveal_fog=1" : "";
        let vx = Math.round(Number(viewCenter.x));
        let vy = Math.round(Number(viewCenter.y));
        if (!Number.isFinite(vx) || !Number.isFinite(vy)) {
          vx = Math.round(Number(home.x)) || 0;
          vy = Math.round(Number(home.y)) || 0;
          viewCenter = { x: vx, y: vy };
        } else {
          viewCenter = { x: vx, y: vy };
        }
        const r = await fetch(
          `/api/world/window?radius=${viewRadius}&z=${currentZ}&center_x=${viewCenter.x}&center_y=${viewCenter.y}${fog}`
        );
        if (!r.ok) {
          setStatus("Ошибка загрузки карты", "err");
          return;
        }
        currentWindow = await r.json();
        if (currentWindow && currentWindow.center) {
          const cx = Math.round(Number(currentWindow.center.x));
          const cy = Math.round(Number(currentWindow.center.y));
          if (Number.isFinite(cx) && Number.isFinite(cy)) viewCenter = { x: cx, y: cy };
        }
        renderMap();
        renderZoneOverlay();
      } catch (_e) {
        setStatus("Ошибка загрузки карты", "err");
      } finally {
        await loadWorldState();
      }
    };
    mapWindowRefreshQueue = mapWindowRefreshQueue.then(run, () => {}).catch(() => {
      setStatus("Ошибка загрузки карты", "err");
    });
    return mapWindowRefreshQueue;
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
        const msg = formatApiFailure(body);
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        return;
      }

      if (r.status === 200 && body.ok) {
        lastTarget = { x, y, z };
        await refreshWindow();
        const okMsg = `Успешно: (${x},${y},${z})`;
        setStatus(okMsg, "ok");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, okMsg, "ok");
        return;
      }

      const msg = formatApiFailure(body);
      setStatus(msg, "err");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
    } catch (_e) {
      const msg = "Нет связи с сервером. Проверьте сеть и попробуйте снова.";
      setStatus(msg, "err");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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
        if (body.error === "cell_occupied_by_own_fleet") {
          const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
          const others = fleets.filter(
            (f) =>
              f &&
              f.id &&
              String(f.id) !== String(fleetId) &&
              Number(f.x) === Number(x) &&
              Number(f.y) === Number(y) &&
              Number(f.z) === Number(z),
          );
          if (others.length > 0) {
            await openFleetStackingChoiceModal({
              draggedFleetId: String(fleetId),
              targetFleetId: String(others[0].id),
              targetPos: { x, y, z },
            });
            return;
          }
        }
        let hint = "";
        if (body.error === "active_order_exists") {
          const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
          const f = fleets.find((fl) => fl && String(fl.id) === String(fleetId)) || worldState.fleet;
          const ao = f && f.active_order ? f.active_order : null;
          hint = ao
            ? `Уже летит в (${ao.target_x},${ao.target_y},${ao.target_z}), осталось ${ao.remaining_ticks} ${solWord(ao.remaining_ticks)}.`
            : "Флот уже в пути.";
        }
        const msg = formatApiFailure(body, { activeOrderHint: hint });
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        return;
      }
      lastTarget = { x, y, z };
      await refreshWindow();
      const okMsg = `Флот в пути: осталось ${body.travel_ticks} ${solWord(body.travel_ticks)}`;
      setStatus(okMsg, "ok");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, okMsg, "ok");
    } catch (_e) {
      const msg = "Нет связи с сервером. Проверьте сеть и попробуйте снова.";
      setStatus(msg, "err");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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
        const msg = formatApiFailure(body);
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        return;
      }
      const okMsg = "Приказ отменён";
      setStatus(okMsg, "ok");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, okMsg, "ok");
      await refreshWindow();
    } catch (_e) {
      const msg = "Нет связи с сервером. Проверьте сеть и попробуйте снова.";
      setStatus(msg, "err");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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
    const disc = pr.disclaimer ? `\n${pr.disclaimer}` : "";
    return `По текущим данным:\nВаш состав: ${mine}\nВраг: ${theirs}\nУсловия клетки: ${terr}\nОриентировочный шанс успеха атаки ≈ ${p}%${disc}`;
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
      viewCenter = { x: tx, y: ty };
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
        const msg = `Бой: ${formatApiFailure(body)}`;
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        closeCombatPromptModal();
        await refreshWindow();
        return;
      }
      const okMsg = attack ? "Решение применено" : "Атака отменена, флот на позиции";
      setStatus(okMsg, "ok");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, okMsg, "ok");
      closeCombatPromptModal();
      await refreshWindow();
    } catch (_e) {
      const msg = "Нет связи с сервером (решение боя). Проверьте сеть и попробуйте снова.";
      setStatus(msg, "err");
      if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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

  const fetchSectorAsDestCell = async (x, y, z) => {
    const zz = Number(z) || 0;
    try {
      const r = await fetch(`/api/world/sector?x=${x}&y=${y}&z=${zz}`);
      const b = await r.json();
      const terrain =
        b.cell && typeof b.cell === "object" && b.cell.terrain ? String(b.cell.terrain) : null;
      return {
        x,
        y,
        z: zz,
        terrain,
        objects: Array.isArray(b.objects) ? b.objects : [],
        flags: { is_visible: true },
      };
    } catch (_e) {
      return { x, y, z: zz, terrain: null, objects: [], flags: { is_visible: true } };
    }
  };

  const cellHasOtherOwnFleet = (cell, draggedFleetId) =>
    Boolean(
      cell &&
        (cell.objects || []).some(
          (o) =>
            o &&
            o.type === "fleet" &&
            o.owner != null &&
            String(o.owner) === String(playerId) &&
            String(o.id) !== String(draggedFleetId),
        ),
    );

  const resolveAdjacentFleetLanding = async (to, draggedFleetId) => {
    const tz = Number(to.z) || 0;
    const axialHexDirs = [
      [1, 0],
      [1, -1],
      [0, -1],
      [-1, 0],
      [-1, 1],
      [0, 1],
    ];
    const cand = axialHexDirs.map((d) => d.slice());
    for (const a of axialHexDirs) {
      for (const b of axialHexDirs) {
        cand.push([a[0] + b[0], a[1] + b[1]]);
      }
    }
    const rows = (currentWindow && currentWindow.cells) || [];
    const cellFromWindow = (nx, ny) => {
      for (const row of rows) {
        for (const cc of row.row || []) {
          if (cc.x === nx && cc.y === ny && (cc.z ?? 0) === tz) return cc;
        }
      }
      return null;
    };
    for (const [dx, dy] of cand) {
      const nx = to.x + dx;
      const ny = to.y + dy;
      let dest = cellFromWindow(nx, ny);
      if (!dest) dest = await fetchSectorAsDestCell(nx, ny, tz);
      if (!cellHasOtherOwnFleet(dest, draggedFleetId))
        return { x: nx, y: ny, z: tz, destCell: dest };
    }
    return null;
  };

  const openFleetStackingChoiceModal = async ({ draggedFleetId, targetFleetId, targetPos }) => {
    await fetchBalanceCached();
    const fleets = Array.isArray(worldState && worldState.fleets) ? worldState.fleets : [];
    const dragged = fleets.find((f) => f && String(f.id) === String(draggedFleetId));
    const target = fleets.find((f) => f && String(f.id) === String(targetFleetId));
    if (!fleetSubOverlay || !fleetSubTitle || !fleetSubBody || !fleetSubFoot) return;
    if (!dragged || !target) {
      setStatus("Не удалось сопоставить флоты — обновите карту (сол).", "err");
      return;
    }
    const to = targetPos || { x: target.x, y: target.y, z: target.z };
    const dn = (f) => (f.name && String(f.name).trim()) || "Флот";
    const dc = (f) => formatComposition(f.composition) || "—";
    const from = { x: dragged.x, y: dragged.y, z: dragged.z };
    fleetSubTitle.textContent = "Два ваших флота";
    fleetSubBody.innerHTML = `
      <p class="muted" style="margin-top:0;">Клетка <b>(${to.x}, ${to.y}, ${to.z})</b> занята <b>${escHtml(dn(target))}</b> (${escHtml(
      dc(target),
    )}). Флот <b>${escHtml(dn(dragged))}</b> (${escHtml(dc(dragged))}) не может занять ту же клетку.</p>
      <p class="muted"><b>Объединить</b> — корабли из «${escHtml(dn(dragged))}» переходят в «${escHtml(
      dn(target),
    )}», перетаскиваемый флот исчезает с карты.</p>
      <p class="muted"><b>Рядом</b> — заказать полёт в ближайшую соседнюю клетку без вашего второго флота (откроется обычное подтверждение полёта).</p>
      <div class="row" style="flex-direction:column;gap:10px;margin-top:14px;">
        <button type="button" class="btn-primary" id="fs-merge-drop">Объединить флоты</button>
        <button type="button" class="btn-secondary" id="fs-near-drop">Остановиться рядом</button>
        <button type="button" class="btn-secondary" id="fs-cancel-drop">Отмена</button>
      </div>`;
    fleetSubFoot.innerHTML = `<span class="muted" style="font-size:88%;">Если «Рядом» недоступен — увеличьте окно карты в «Настройки UI» (до 25×25) или подойдите с другой стороны.</span>`;
    const close = () => closeFleetSubModal();
    fleetSubBody.querySelector("#fs-cancel-drop").addEventListener("click", close);
    fleetSubBody.querySelector("#fs-merge-drop").addEventListener("click", async () => {
      close();
      await mergeFleetsApi(String(target.id), String(dragged.id));
    });
    fleetSubBody.querySelector("#fs-near-drop").addEventListener("click", async () => {
      close();
      const alt = await resolveAdjacentFleetLanding(to, String(dragged.id));
      if (!alt) {
        setStatus("Нет подходящей соседней клетки без вашего флота.", "err");
        return;
      }
      await openFleetMoveConfirm({
        fleet_id: String(dragged.id),
        qty: Number(dragged.qty) || 0,
        from,
        to: { x: alt.x, y: alt.y, z: alt.z },
        destCell: alt.destCell,
        deferOkMs: 450,
      });
    });
    fleetSubOverlay.classList.remove("hidden");
  };

  const openFleetMoveConfirm = async ({ fleet_id, qty, from, to, destCell, deferOkMs }) => {
    if (!overlayEl) return;
    const distance = jsHexDistance(to.x, to.y, from.x, from.y);
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
        const msg = "Нет активного флота для движения — выберите флот в списке справа.";
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        return;
      }
      await moveFleet(activeFleetId, selectedCell.x, selectedCell.y, selectedCell.z);
    });
  }
  if (buildBtn) {
    buildBtn.addEventListener("click", async () => {
      if (!selectedCell) return;
      if (buildBtn.disabled) {
        const msg =
          "Нужны инженеры: приведите в эту клетку флот с инженерами или откройте строительство с клетки своей планеты.";
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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
          const msg = formatApiFailure(body);
          setStatus(msg, "err");
          if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
          return;
        }
        const okMsg = body.already_done
          ? "Объект уже исследован"
          : body.headline
            ? String(body.headline)
            : "Исследование завершено — см. журнал событий";
        setStatus(okMsg, "ok");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, okMsg, "ok");
        if (!body.already_done) mergeOnboardingMilestones({ exploreOrOutpost: true });
        await refreshWindow();
        refreshSelectedCellFromWindow();
        updateSelectedPanel();
        void loadWorldState();
      } catch (_e) {
        const msg = "Нет связи с сервером. Проверьте сеть и попробуйте снова.";
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
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
        const msg = "Сначала выберите флот в списке";
        setStatus(msg, "err");
        if (hudActionFeedbackEl) showActionFeedback(hudActionFeedbackEl, msg, "err");
        return;
      }
      void focusFleetOnMap(activeFleetId);
    });
  }
  if (clearSelBtn) {
    clearSelBtn.addEventListener("click", () => {
      selectedCell = null;
      lastEdgePanCellKey = null;
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

  const formatMapSizeLabel = () => `${mapWindowSideCells(viewRadius)}×${mapWindowSideCells(viewRadius)}`;

  const syncMapWindowUi = () => {
    const t = formatMapSizeLabel();
    if (mapWindowSizeLabel) mapWindowSizeLabel.textContent = t;
    if (uiMapWindowLabel) uiMapWindowLabel.textContent = t;
    if (uiMapWindowMinus) uiMapWindowMinus.disabled = viewRadius <= MAP_WINDOW_RADIUS_MIN;
    if (uiMapWindowPlus) uiMapWindowPlus.disabled = viewRadius >= MAP_WINDOW_RADIUS_MAX;
    if (uiMapPreset13) uiMapPreset13.classList.toggle("is-active", viewRadius === MAP_WINDOW_RADIUS_MIN);
    if (uiMapPreset17) uiMapPreset17.classList.toggle("is-active", viewRadius === 8);
  };

  const setRadius = async (r) => {
    viewRadius = clampMapWindowRadius(r);
    try {
      localStorage.setItem(MAP_VIEW_RADIUS_KEY, String(viewRadius));
    } catch (_e) {
      /* ignore */
    }
    syncMapWindowUi();
    await refreshWindow();
    setStatus(`Размер окна карты: ${formatMapSizeLabel()}`, "ok");
  };

  if (uiMapWindowMinus) {
    uiMapWindowMinus.addEventListener("click", async () => {
      await setRadius(viewRadius - 1);
    });
  }
  if (uiMapWindowPlus) {
    uiMapWindowPlus.addEventListener("click", async () => {
      await setRadius(viewRadius + 1);
    });
  }
  if (uiMapPreset13) uiMapPreset13.addEventListener("click", async () => setRadius(MAP_WINDOW_RADIUS_MIN));
  if (uiMapPreset17) uiMapPreset17.addEventListener("click", async () => setRadius(8));

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
      const wbtn = e.target && e.target.closest && e.target.closest("[data-wiki-res]");
      if (wbtn && economyModalOverlay.contains(wbtn)) {
        e.preventDefault();
        e.stopPropagation();
        openWikiForResourceKey(wbtn.getAttribute("data-wiki-res"));
        return;
      }
      if (e.target === economyModalOverlay) closeEconomyModal();
    });
  }

  const resourcesChipBar = document.getElementById("resources-chip");
  if (resourcesChipBar) {
    resourcesChipBar.addEventListener("click", (e) => {
      const chip = e.target && e.target.closest && e.target.closest(".res-chip[data-res]");
      if (!chip || !resourcesChipBar.contains(chip)) return;
      const rk = chip.getAttribute("data-res");
      if (!rk) return;
      e.preventDefault();
      openWikiForResourceKey(rk);
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
    syncMapWindowUi();
    if (playerIsGameAdmin) {
      if (uiAdminGotoX) uiAdminGotoX.value = String(Math.round(Number(viewCenter.x) || 0));
      if (uiAdminGotoY) uiAdminGotoY.value = String(Math.round(Number(viewCenter.y) || 0));
      if (uiAdminGotoZ) uiAdminGotoZ.value = String(Math.round(Number(currentZ) || 0));
    }
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
    const mapMode = uiMapModeGraphic && uiMapModeGraphic.checked ? "graphic" : "tactical";
    if (uiMapGraphicHint) uiMapGraphicHint.classList.toggle("hidden", mapMode !== "graphic");
    const s = {
      fontSize: uiFontSize ? Number(uiFontSize.value) : 14,
      lineHeight: uiLineHeight ? Number(uiLineHeight.value) : 1.35,
      battleFocusRadius: br,
      forceAttackGuaranteed: Boolean(uiForceAttack && uiForceAttack.checked),
      mapMode,
      mapShowCoords: Boolean(uiMapShowCoords && uiMapShowCoords.checked),
      revealFogAdmin: Boolean(playerIsGameAdmin && uiRevealFogAdmin && uiRevealFogAdmin.checked),
    };
    applyUiSettings(s);
    saveUiSettings(s);
    if (uiBattleRadiusLabel) uiBattleRadiusLabel.textContent = String(br);
    if (typeof renderMap === "function") renderMap();
  };
  if (uiFontSize) uiFontSize.addEventListener("input", onSettingsChanged);
  if (uiLineHeight) uiLineHeight.addEventListener("input", onSettingsChanged);
  if (uiBattleRadius) uiBattleRadius.addEventListener("input", onSettingsChanged);
  if (uiForceAttack) uiForceAttack.addEventListener("change", onSettingsChanged);
  if (uiMapModeTactical) uiMapModeTactical.addEventListener("change", onSettingsChanged);
  if (uiMapModeGraphic) uiMapModeGraphic.addEventListener("change", onSettingsChanged);
  if (uiMapShowCoords) uiMapShowCoords.addEventListener("change", onSettingsChanged);
  if (uiRevealFogAdmin) {
    uiRevealFogAdmin.addEventListener("change", () => {
      onSettingsChanged();
      void refreshWindow();
    });
  }
  if (uiAdminGotoBtn) {
    uiAdminGotoBtn.addEventListener("click", async () => {
      if (!playerIsGameAdmin) return;
      const x = Math.round(Number(uiAdminGotoX && uiAdminGotoX.value));
      const y = Math.round(Number(uiAdminGotoY && uiAdminGotoY.value));
      let zz = Math.round(Number(uiAdminGotoZ && uiAdminGotoZ.value));
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        setStatus("Укажите целые координаты X и Y", "err");
        return;
      }
      if (!Number.isFinite(zz)) zz = currentZ;
      zz = Math.max(-10, Math.min(10, zz));
      viewCenter = { x, y };
      currentZ = zz;
      if (zEl) zEl.textContent = String(currentZ);
      await refreshWindow();
      setStatus(`Карта: центр (${x}, ${y}), z=${currentZ}`, "ok");
    });
  }
  if (uiSettingsReset) {
    uiSettingsReset.addEventListener("click", () => {
      const s = {
        fontSize: 14,
        lineHeight: 1.35,
        battleFocusRadius: 6,
        forceAttackGuaranteed: false,
        mapMode: "tactical",
        mapShowCoords: true,
        revealFogAdmin: false,
      };
      saveUiSettings(s);
      syncUiSettingsControls(s);
      if (typeof renderMap === "function") renderMap();
    });
  }

  document.querySelectorAll("#system-log-filters [data-sys-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const f = btn.getAttribute("data-sys-filter") || "all";
      systemLogFilterCategory = f;
      try {
        localStorage.setItem(SYSTEM_LOG_FILTER_KEY, f);
      } catch (_e) {
        /* ignore */
      }
      document.querySelectorAll("#system-log-filters [data-sys-filter]").forEach((b) => {
        b.classList.toggle("is-active", (b.getAttribute("data-sys-filter") || "") === f);
      });
      renderEvents(worldState.events);
    });
  });
  document.querySelectorAll("#system-log-filters [data-sys-filter]").forEach((b) => {
    b.classList.toggle(
      "is-active",
      (b.getAttribute("data-sys-filter") || "") === systemLogFilterCategory
    );
  });

  document.querySelectorAll(".comms-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.getAttribute("data-comms-tab");
      if (!name) return;
      setActiveCommsTab(name);
      if (name === "global") void fetchGlobalChat();
      if (name === "private") void loadPrivateThreads();
    });
  });

  if (commsCollapseBtn) commsCollapseBtn.addEventListener("click", () => toggleCommsCollapsed());
  if (commsOverlay) {
    commsOverlay.addEventListener("click", () => {
      if (!commsWideMq.matches && !isCommsCollapsed()) {
        commsCollapsedExplicit = true;
        try {
          localStorage.setItem(COMMS_COLLAPSED_KEY, "true");
        } catch (_e) {
          /* ignore */
        }
        applyCommsLayout();
      }
    });
  }
  commsWideMq.addEventListener("change", () => {
    if (commsCollapsedExplicit === null) applyCommsLayout();
    else syncMmoSidePanelHeights();
  });
  applyCommsLayout();
  syncCommsPanelTitle();
  applyChatPrefsToDom();

  const syncChatSettingsControls = () => {
    const p = readChatPrefs();
    if (chatColorSystem) chatColorSystem.value = p.colorSystem || "#61eaa3";
    if (chatColorGlobal) chatColorGlobal.value = p.colorGlobal || "#7ec8e3";
    if (chatColorAlliance) chatColorAlliance.value = p.colorAlliance || "#c9a227";
    if (chatColorPrivate) chatColorPrivate.value = p.colorPrivate || "#d88fd8";
    if (chatDisablePrivate) chatDisablePrivate.checked = Boolean(p.disablePrivateIncoming);
  };
  const openChatSettings = () => {
    if (!chatSettingsOverlay) return;
    syncChatSettingsControls();
    chatSettingsOverlay.classList.remove("hidden");
  };
  const closeChatSettings = () => {
    if (chatSettingsOverlay) chatSettingsOverlay.classList.add("hidden");
  };
  if (chatSettingsOpenBtn) chatSettingsOpenBtn.addEventListener("click", openChatSettings);
  if (chatSettingsClose) chatSettingsClose.addEventListener("click", closeChatSettings);
  if (chatSettingsOverlay) {
    chatSettingsOverlay.addEventListener("click", (e) => {
      if (e.target === chatSettingsOverlay) closeChatSettings();
    });
  }
  if (chatSettingsSave) {
    chatSettingsSave.addEventListener("click", () => {
      writeChatPrefs({
        colorSystem: chatColorSystem && chatColorSystem.value,
        colorGlobal: chatColorGlobal && chatColorGlobal.value,
        colorAlliance: chatColorAlliance && chatColorAlliance.value,
        colorPrivate: chatColorPrivate && chatColorPrivate.value,
        disablePrivateIncoming: Boolean(chatDisablePrivate && chatDisablePrivate.checked),
      });
      applyChatPrefsToDom();
      closeChatSettings();
    });
  }

  if (globalChatForm) {
    globalChatForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const t = globalChatInput && globalChatInput.value.trim();
      if (!t) return;
      if (t.length > MAX_CHAT_BODY_CHARS) {
        if (statusEl)
          statusEl.textContent = `Чат: не более ${MAX_CHAT_BODY_CHARS} символов (сейчас ${t.length}).`;
        return;
      }
      try {
        const r = await fetch("/api/chat/global", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: t }),
        });
        const body = await r.json();
        if (!r.ok || !body || !body.ok) {
          if (statusEl) statusEl.textContent = `Чат: ${(body && body.error) || "ошибка"}`;
          return;
        }
        if (globalChatInput) globalChatInput.value = "";
        await fetchGlobalChat();
      } catch (_e) {
        if (statusEl) statusEl.textContent = "Чат: сеть";
      }
    });
  }

  if (privateChatForm) {
    privateChatForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const peer = (privateChatPeer && privateChatPeer.value.trim()) || privatePeerActive;
      const t = privateChatInput && privateChatInput.value.trim();
      if (!peer || !t) return;
      if (t.length > MAX_CHAT_BODY_CHARS) {
        if (statusEl)
          statusEl.textContent = `ЛС: не более ${MAX_CHAT_BODY_CHARS} символов (сейчас ${t.length}).`;
        return;
      }
      const prefs = readChatPrefs();
      if (prefs.disablePrivateIncoming) {
        if (statusEl) statusEl.textContent = "В настройках чата отключены личные сообщения.";
        return;
      }
      try {
        const r = await fetch("/api/chat/private", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ peer_id: peer, body: t }),
        });
        const body = await r.json();
        if (!r.ok || !body || !body.ok) {
          if (statusEl) statusEl.textContent = `ЛС: ${(body && body.error) || "ошибка"}`;
          return;
        }
        if (privateChatInput) privateChatInput.value = "";
        await fetchPrivateChat();
      } catch (_e) {
        if (statusEl) statusEl.textContent = "ЛС: сеть";
      }
    });
  }

  if (privatePeerOpenBtn && privatePeerInput) {
    privatePeerOpenBtn.addEventListener("click", () => {
      void openPrivatePeer(privatePeerInput.value.trim());
    });
  }
  if (privateBackThreadsBtn) privateBackThreadsBtn.addEventListener("click", () => closePrivatePeerView());
  if (privateIntroYesBtn)
    privateIntroYesBtn.addEventListener("click", () => void completePrivateIntro(true));
  if (privateIntroNoBtn)
    privateIntroNoBtn.addEventListener("click", () => void completePrivateIntro(false));
  if (privateSendReadReceiptCb) {
    privateSendReadReceiptCb.addEventListener("change", () => {
      if (privateReceiptsProgrammaticToggle) return;
      const peer = (privateChatPeer && privateChatPeer.value.trim()) || privatePeerActive;
      if (!peer || !privatePeerActive) return;
      void patchPrivateReceiptPrefs(peer, privateSendReadReceiptCb.checked);
    });
  }
  if (privateDeleteThreadBtn) {
    privateDeleteThreadBtn.addEventListener("click", async () => {
      const peer = (privateChatPeer && privateChatPeer.value.trim()) || privatePeerActive;
      if (
        !peer ||
        !window.confirm("Убрать переписку из списка? Сообщения на сервере сохранятся; новое сообщение снова покажет чат.")
      )
        return;
      try {
        const r = await fetch("/api/chat/private/thread/hide", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ peer_id: peer }),
        });
        const body = await r.json();
        if (!r.ok || !body || !body.ok) {
          if (statusEl) statusEl.textContent = `ЛС: ${(body && body.error) || "ошибка"}`;
          return;
        }
        closePrivatePeerView();
        void refreshPrivateBadge();
      } catch (_e) {
        if (statusEl) statusEl.textContent = "ЛС: сеть";
      }
    });
  }
  if (privateBlockPeerBtn) {
    privateBlockPeerBtn.addEventListener("click", async () => {
      const peer = (privateChatPeer && privateChatPeer.value.trim()) || privatePeerActive;
      if (!peer || !confirm("Игнорировать сообщения этого игрока в чатах?")) return;
      try {
        const r = await fetch("/api/chat/blocks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blocked_id: peer }),
        });
        const body = await r.json();
        if (!r.ok || !body || !body.ok) {
          if (statusEl) statusEl.textContent = `Игнор: ${(body && body.error) || "ошибка"}`;
          return;
        }
        closePrivatePeerView();
      } catch (_e) {
        if (statusEl) statusEl.textContent = "Игнор: сеть";
      }
    });
  }

  maybeAutoShowEntryTutorial();

  void (async () => {
    try {
      await refreshWindow();
    } catch (_e) {
      renderMap();
      renderZoneOverlay();
      void loadWorldState();
    }
    syncMapWindowUi();
    updateSelectedPanel();
    requestAnimationFrame(() => {
      applyMapCellSizeFromContainer();
      syncMmoSidePanelHeights();
    });
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
    // `refreshWindow` уже вызывает `loadWorldState` — второй вызов дублировал опросы и мешал HUD (в т.ч. discovery).
    void refreshWindow();
    // Если открыта статистика экономики — обновляем её вместе с тиками.
    if (economyModalOverlay && !economyModalOverlay.classList.contains("hidden")) {
      void loadEconomyModalContent();
    }
    if (activeCommsTab === "global") void fetchGlobalChat();
    if (activeCommsTab === "private" && privatePeerActive) void fetchPrivateChat();
    void refreshPrivateBadge();
  }, 3000);

  void refreshPrivateBadge();
})();
