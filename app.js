// ============================================================
// Phase 1.1 — Initial Loading Screen (text-only, no audio)
// Phase 1.2 — Audio Gate (tap Play > to unlock audio)
// Phase 1.2.1 — Main Menu placeholder (first real screen after gate)
// ============================================================

// Fixed, ordered "excuses" (approved aviation arc)
const LOADING_LINES = [
  "Removing coat, shoes…",
  "Boarding flight MS-12…",
  "Finding seat near emergency exit…",
  "Cabin doors sealed…",
  "Engines starting…",
  "Woken up by turbulence…",
  "Oxygen masks dropping?",
  "Voice text: “I'm sorry for--”",
  "“Okay. Sending your message…”",
  "What was I... window cracking?",
  "Someone humming",
];

const loadingScreen = document.getElementById("loadingScreen");
const loadingText = document.getElementById("loadingText");

// Main menu nodes
const appScreen = document.getElementById("appScreen");
const menuTitleArt = document.getElementById("menuTitleArt");
const btnStart = document.getElementById("btnStart");
const btnLanguage = document.getElementById("btnLanguage");
const btnMusic = document.getElementById("btnMusic");
const menuHint = document.getElementById("menuHint");

// Phase 2.1 gameplay nodes (transcript + input)
const gameScreen = document.getElementById("gameScreen");
const transcriptBox = document.getElementById("transcriptBox");
const choiceTimer = document.getElementById("choiceTimer");

const gameInput = document.getElementById("gameInput");
const btnEnter = document.getElementById("btnEnter");

// Phase 3.1: virtual keyboard mount point (DOM-only keyboard lives here)
const vkbd = document.getElementById("vkbd");

// Phase 3.1: active submit routing
let __msActiveSubmitFn = null;

// ---> NEW (Phase 3.0): Virtual keyboard buffer (single source of truth)
// gameInput becomes display-only; all typed text lives here.
// all typed text lives here.
const __msUseVirtualKeyboard = true;
let __msVkbBuffer = "";

// Phase 3.1 keyboard modes: exactly two supported modes.
const VKBD_MODE_MINIMAL = "MINIMAL";
const VKBD_MODE_TEXT = "TEXT";

let __msVkbdMode = VKBD_MODE_MINIMAL;

function vkbSetBuffer(s) {
  __msVkbBuffer = String(s ?? "");
  vkbSyncToDisplay();
}

function vkbRefreshTextModeIfNeeded() {
  if (!vkbd) return;
  if (__msVkbdMode !== VKBD_MODE_TEXT) return;

  // Accent enable/disable depends on buffer contents, so TEXT must re-render on each edit.
  vkbd.dataset.mode = "";
  vkbEnsureScaffold();
}

function vkbClearBuffer() {
  __msVkbBuffer = "";
  vkbSyncToDisplay();
  vkbRefreshTextModeIfNeeded(); // ---> NEW
}

function vkbAppend(ch) {
  __msVkbBuffer += String(ch ?? "");
  vkbSyncToDisplay();
  vkbRefreshTextModeIfNeeded(); // ---> NEW
}

function vkbBackspace() {
  if (!__msVkbBuffer) return;
  __msVkbBuffer = __msVkbBuffer.slice(0, -1);
  vkbSyncToDisplay();
  vkbRefreshTextModeIfNeeded(); // ---> NEW
}

function vkbConsumeTrimmed() {
  let s = String(__msVkbBuffer ?? "").trim();

  // If we're in TEXT mode, submit with first-letter capitalization
  // so the story log matches what the player saw in the input line.
  if (__msVkbdMode === VKBD_MODE_TEXT && s.length > 0) {
    const first = s[0];
    if (first >= "a" && first <= "z") s = first.toUpperCase() + s.slice(1);
  }

  if (s) vkbClearBuffer();
  return s;
}

function vkbSetMode(mode) {
  // Phase 3.1 contract boundary:
  // TEXT is naming-only; every other request resolves to MINIMAL.
  __msVkbdMode =
    mode === VKBD_MODE_TEXT
      ? VKBD_MODE_TEXT
      : VKBD_MODE_MINIMAL;

  // Force re-render on next ensure.
  if (vkbd) {
    vkbd.dataset.mode = "";
  }

  vkbEnsureScaffold();
}

// ---> NEW (Phase 3.0 DEV): quick VKBD mode switch helpers (for testing only)
window.MS_setVkbdMode = function (mode) {
  const m = String(mode || "").toUpperCase();

  // Ensure scaffold exists before switching.
  try {
    vkbEnsureScaffold();
  } catch {}

  if (m === "TEXT") {
    vkbSetMode(VKBD_MODE_TEXT);
    return;
  }

  // Phase 3.1 contract: MINIMAL is the only non-TEXT mode.
  vkbSetMode(VKBD_MODE_MINIMAL);
};

function vkbMakeBtnFactory() {
  return (label, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.classList.add("ms-vkbd-btn");

    if (label === "⌫") {
      b.classList.add("ms-vkbd-btn--backspace");
    }

    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onClick();
    });

    return b;
  };
}

function vkbSubmitViaFunnel() {
  // Submit via active screen funnel (menu vs gameplay)
  try {
    if (typeof __msActiveSubmitFn === "function") {
      __msActiveSubmitFn();
      return;
    }
  } catch {}

  // Fallback: gameplay uses the existing Enter button funnel
  if (btnEnter && !btnEnter.disabled) btnEnter.click();
}

function vkbRenderMinimal(makeBtn) {
  // MINIMAL MODE (core gameplay)
  // Top:    [ 1 ] [ 2 ] [ enter ]
  // Bottom: [ ⌫ ] [ space (wide: under 2 + enter) ]
  const rowTop = document.createElement("div");
  rowTop.className = "ms-vkbd-row ms-vkbd-row--top";

  const rowBottom = document.createElement("div");
  rowBottom.className = "ms-vkbd-row ms-vkbd-row--bottom";

  rowTop.appendChild(makeBtn("1", () => vkbAppend("1")));
  rowTop.appendChild(makeBtn("2", () => vkbAppend("2")));
  rowTop.appendChild(makeBtn("enter", () => vkbSubmitViaFunnel()));

  rowBottom.appendChild(makeBtn("⌫", () => vkbBackspace()));

  const spaceBtn = makeBtn("space", () => {
    if (!__msVkbBuffer) return;
    vkbAppend(" ");
  });
  spaceBtn.classList.add("ms-vkbd-btn--space");
  rowBottom.appendChild(spaceBtn);

  return [rowTop, rowBottom];
}

function vkbGetDisplayValue() {
  const raw = String(__msVkbBuffer ?? "");

  // TEXT mode: show first character as uppercase if it is a letter
  if (__msVkbdMode === VKBD_MODE_TEXT && raw.length > 0) {
    const first = raw[0];
    if (first >= "a" && first <= "z") return first.toUpperCase() + raw.slice(1);
    if (first >= "A" && first <= "Z") return first + raw.slice(1);
  }

  return raw;
}

function vkbSyncToDisplay() {
  const val = vkbGetDisplayValue();

  // Phase 3.0: the virtual keyboard exists only during gameplay.
  if (!gameInput) return;
  gameInput.value = val;
}

function vkbRenderText(makeBtn) {
  // TEXT MODE (naming only)
  // AE: no accent row
  // BR-PT: accent row visible from the start, but DISABLED until first base letter is entered.
  // NOTE: Buffer remains raw; display capitalization handled in vkbGetDisplayValue().

  const rows = [];

  const uiLang = String(localStorage.getItem("ms_lang") || navigator.language || "en-US");
  const isPtBr = uiLang.toLowerCase().startsWith("pt");

  // “first base letter typed” gate (Option A):
  // - enabled once any [a-z] exists in buffer
  // - re-disables if player backspaces to empty (no [a-z])
  const raw = String(__msVkbBuffer || "");
  const hasBaseLetter = /[a-z]/.test(raw);

  const makeRow = (cols) => {
    const r = document.createElement("div");
    r.className = "ms-vkbd-row";
    r.style.gridTemplateColumns = cols;
    return r;
  };

  // BR-PT accent row (visible always; disabled until base letter exists)
  if (isPtBr) {
    const accentRow = makeRow("repeat(8, minmax(0, 1fr))");
    ["á", "é", "í", "ó", "ú", "ã", "õ", "ç"].forEach((ch) => {
      const b = makeBtn(ch, () => vkbAppend(ch));
      b.disabled = !hasBaseLetter; // keypress ignored silently when disabled (per spec)
      accentRow.appendChild(b);
    });
    rows.push(accentRow);
  }

  // QWERTY rows (keys always lowercase on keyboard)
  const row1 = makeRow("repeat(10, minmax(0, 1fr))");
  "qwertyuiop".split("").forEach((ch) => row1.appendChild(makeBtn(ch, () => vkbAppend(ch))));
  rows.push(row1);

  const row2 = makeRow("repeat(9, minmax(0, 1fr))");
  "asdfghjkl".split("").forEach((ch) => row2.appendChild(makeBtn(ch, () => vkbAppend(ch))));
  rows.push(row2);

  // Bottom letter row includes backspace at end (per spec)
  const row3 = makeRow("repeat(8, minmax(0, 1fr))");
  "zxcvbnm".split("").forEach((ch) => row3.appendChild(makeBtn(ch, () => vkbAppend(ch))));
  row3.appendChild(makeBtn("⌫", () => vkbBackspace()));
  rows.push(row3);

  // Space + Enter row (space wide)
  const row4 = makeRow("2fr 1fr");
  const spaceBtn = makeBtn("space", () => {
    if (!__msVkbBuffer) return; // disallow leading space
    vkbAppend(" ");
  });
  spaceBtn.classList.add("ms-vkbd-btn--space");
  row4.appendChild(spaceBtn);

  row4.appendChild(makeBtn("enter", () => vkbSubmitViaFunnel()));
  rows.push(row4);

  return rows;
}

function vkbEnsureScaffold() {
  if (!vkbd) return;

  // Ensure base container is initialized once.
  if (vkbd.dataset.built !== "1") {
    vkbd.dataset.built = "1";
    vkbd.innerHTML = "";
    vkbd.classList.add("ms-vkbd");
  }

  // Phase 3.1 contract: only TEXT and MINIMAL can be rendered.
  const modeKey = String(__msVkbdMode);

  if (vkbd.dataset.mode === modeKey) {
    return;
  }

  vkbd.dataset.mode = modeKey;

  // Rebuild the keyboard for this mode.
  vkbd.innerHTML = "";

  const makeBtn = vkbMakeBtnFactory();

  if (__msVkbdMode === VKBD_MODE_TEXT) {
    const rows = vkbRenderText(makeBtn);
    rows.forEach((r) => vkbd.appendChild(r));
    return;
  }

  // Default: MINIMAL
  const rows = vkbRenderMinimal(makeBtn);
  rows.forEach((r) => vkbd.appendChild(r));

  // Bug #3 defense: rare TEXT→MINIMAL rebuild glitch where SPACE vanishes.
  // We allow exactly one automatic retry to avoid loops.
  if (__msVkbdMode === VKBD_MODE_MINIMAL) {
    const didRetry = vkbd.dataset.sanityRetry === "1";
    const hasSpace = !!vkbd.querySelector(
      ".ms-vkbd-row--bottom .ms-vkbd-btn--space"
    );

    if (!hasSpace && !didRetry) {
      vkbd.dataset.sanityRetry = "1";
      vkbd.dataset.mode = "";
      vkbEnsureScaffold();
      return;
    }

    // Reset retry flag after a successful build or after the one retry.
    vkbd.dataset.sanityRetry = "";
  }
}

// Phase 3.0: portrait-only enforcement overlay
const orientationLockEl = document.getElementById("orientationLock");

// Audio element (menu music)
const bgMusicEl = document.getElementById("bgMusic");

// ---------------------------
// Menu music preference helpers
// ---------------------------
function MS_isMenuMusicOn() {
  const raw = localStorage.getItem("ms_menu_music_on");
  if (raw === null) return true;
  return raw === "1";
}

function MS_setMenuMusicPref(on) {
  localStorage.setItem("ms_menu_music_on", on ? "1" : "0");
}

// When we pause the music due to an explicit user toggle, we set this flag briefly
// so the pause-event safety net does NOT show the recovery overlay.
window.__msMusicPausedByUser = false;

// ============================================================
// Shared UI helpers (menu title art, transient menu hints, menu music)
// ============================================================

// NOTE: This is UI art (not narrative). Keep it identical across gate + main menu.
const MS_TITLE_ART =
`__  __ _           _    ____                    
|  \/  (_)_ __   __| |  / ___|  ___  _ __   __ _ 
| |\/| | | '_ \ / _\` |  \___ \ / _ \| '_ \ / _\` |
| |  | | | | | | (_| |   ___) | (_) | | | | (_| |
|_|  |_|_|_| |_|\__,_|  |____/ \___/|_| |_|\__, |
                                           |___/ 
                MIND SONG`;

// Title SVG embedded directly so no external asset path is required.
const MS_TITLE_SVG = String.raw`
<svg
  xmlns="http://www.w3.org/2000/svg"
  width="728"
  height="230"
  viewBox="0 0 728 230"
  role="img"
  aria-label="Mind Song"
>
  <rect width="100%" height="100%" fill="none"></rect>

  <text
    x="10"
    y="30"
    font-family="DejaVu Sans Mono, monospace"
    font-size="24"
    fill="white"
    xml:space="preserve"
  >
    <tspan x="10" dy="0">__  __ _           _    ____                   </tspan>
    <tspan x="10" dy="30">|  \/  (_)_ __   __| |  / ___|  ___  _ __   __ _ </tspan>
    <tspan x="10" dy="30">| |\/| | | &#x27;_ \ / _&#96; |  \___ \ / _ \| &#x27;_ \ / _&#96; |</tspan>
    <tspan x="10" dy="30">| |  | | | | | | (_| |   ___) | (_) | | | | (_| |</tspan>
    <tspan x="10" dy="30">|_|  |_|_|_| |_|\__,_|  |____/ \___/|_| |_|\__, |</tspan>
    <tspan x="10" dy="30">                                           |___/ </tspan>
    <tspan x="10" dy="30">                Mind Song</tspan>
  </text>
</svg>`;

function MS_setMenuTitleArt() {
  if (!menuTitleArt) return;

  // Use the embedded SVG directly; no file path or network request is involved.
  menuTitleArt.innerHTML = MS_TITLE_SVG;
}

// --- Transient hint (matches mind_song.py linger time: 1.2s)
let __msMenuHintTimerId = null;
let __msMenuHintToken = 0;

function MS_setMenuHintTemp(text, { lingerMs = 1200 } = {}) {
  if (!menuHint) return;

  __msMenuHintToken += 1;
  const myToken = __msMenuHintToken;

  menuHint.textContent = String(text ?? "");

  if (__msMenuHintTimerId !== null) {
    clearTimeout(__msMenuHintTimerId);
    __msMenuHintTimerId = null;
  }

  __msMenuHintTimerId = setTimeout(() => {
    // Only clear if nothing newer replaced it.
    if (myToken !== __msMenuHintToken) return;
    if (menuHint) menuHint.textContent = "";
    __msMenuHintTimerId = null;
  }, Math.max(0, Number(lingerMs) || 0));
}

// --- Menu music setting helpers
function MS_isMenuMusicOn() {
  const raw = localStorage.getItem("ms_menu_music_on");
  if (raw === null) return true;
  return raw === "1";
}

function MS_updateMenuMusicButtonLabel() {
  if (!btnMusic) return;
  const on = MS_isMenuMusicOn();
  btnMusic.textContent = `Music: ${on ? "ON" : "OFF"}`;
}

async function MS_setMenuMusicOn(on) {
  localStorage.setItem("ms_menu_music_on", on ? "1" : "0");
  MS_updateMenuMusicButtonLabel();

  if (!bgMusicEl) return;
  if (!on) {
    try { bgMusicEl.pause(); } catch {}
    return;
  }

  // Only try to start if audio is unlocked (gesture already happened at gate or via recovery).
  try { await startMenuMusic(); } catch {}
}

// ============================================================
// Mobile safety:
// Do NOT intercept touchmove (it breaks native scrolling on Chrome/Android).
// We rely on CSS (overscroll-behavior + overflow hidden) to block pull-to-refresh.
// ============================================================

// ============================================================
// Phase 3.0 — Portrait-only Orientation Lock (MANDATORY)
// ============================================================

// Watchdog timer (runs only while locked to prevent "stuck" overlays)
let __msOrientationWatchdogId = null;

function _vvDims() {
  // Prefer VisualViewport dimensions when available (more trustworthy on mobile)
  if (window.visualViewport) {
    return { w: window.visualViewport.width, h: window.visualViewport.height };
  }
  return { w: window.innerWidth, h: window.innerHeight };
}

function isLandscapeNow() {
  // 1) Most reliable on mobile: visual viewport aspect
  const d = _vvDims();
  if (d.w && d.h) return d.w > d.h;

  // 2) Media query fallback
  try {
    if (window.matchMedia && window.matchMedia("(orientation: landscape)").matches) return true;
    if (window.matchMedia && window.matchMedia("(orientation: portrait)").matches) return false;
  } catch {}

  // 3) Last resort
  return window.innerWidth > window.innerHeight;
}

function _startOrientationWatchdog() {
  if (__msOrientationWatchdogId !== null) return;

  // Poll briefly while locked; stop immediately once portrait is detected
  __msOrientationWatchdogId = setInterval(() => {
    if (!orientationLockEl) return;

    const locked = isLandscapeNow();
    if (!locked) {
      // Force-clear stuck overlay + re-enable controls
      applyOrientationLock();
      _stopOrientationWatchdog();
    } else {
      // Keep it enforced in case other UI tries to enable itself
      applyOrientationLock();
    }
  }, 150);
}

function _stopOrientationWatchdog() {
  if (__msOrientationWatchdogId === null) return;
  clearInterval(__msOrientationWatchdogId);
  __msOrientationWatchdogId = null;
}

function applyOrientationLock() {
  if (!orientationLockEl) return;

  const locked = isLandscapeNow();

  // Show/hide overlay (overlay itself blocks interaction behind it)
  orientationLockEl.style.display = locked ? "flex" : "none";

  // Watchdog only while locked (prevents "stuck" overlays)
  if (locked) _startOrientationWatchdog();
  else _stopOrientationWatchdog();

  // Hard-block current UI interactions (belt + suspenders)
  try {
    if (btnStart) btnStart.disabled = locked;
    if (btnLanguage) btnLanguage.disabled = locked;
    if (btnMusic) btnMusic.disabled = locked;

    if (btnEnter) btnEnter.disabled = locked;

    // Keep OS keyboard away while locked
    if (gameInput) {
      gameInput.disabled = locked;
      if (locked && document.activeElement === gameInput) {
        try { gameInput.blur(); } catch {}
      }
    }
  } catch {}
}

function applyOrientationLockSettled() {
  // Rotation can report stale sizes; re-apply after layout settles
  applyOrientationLock();
  requestAnimationFrame(() => applyOrientationLock());
  setTimeout(() => applyOrientationLock(), 80);
  setTimeout(() => applyOrientationLock(), 220);
}

// Install immediately + react to changes
window.addEventListener("resize", applyOrientationLockSettled, { passive: true });
window.addEventListener("orientationchange", applyOrientationLockSettled, { passive: true });

// Extra “Android is weird” hooks
document.addEventListener("visibilitychange", applyOrientationLockSettled, { passive: true });
window.addEventListener("pageshow", applyOrientationLockSettled, { passive: true });
window.addEventListener("focus", applyOrientationLockSettled, { passive: true });

// VisualViewport events often fire more reliably on mobile rotation
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", applyOrientationLockSettled, { passive: true });
  window.visualViewport.addEventListener("scroll", applyOrientationLockSettled, { passive: true });
}

applyOrientationLockSettled();

// Runtime readiness signal:
// When true, Phase 1 loading ritual proceeds to the Audio Gate.
// This may be flipped by runtime init (worker ready) and/or engine meta plumbing.
let runtimeReady = false;
let MS_latestChoices = null;

// ---> NEW: Phase 3.1 engine-declared keyboard mode (capture only for now)
let MS_latestInputMode = null;

// ---> NEW (Phase 2.8): latest engine-declared timed-choice allowance.
// Capture only for now; no countdown behavior yet.
let MS_latestChoiceTimeoutSeconds = null;

// ---> NEW (Phase 2.8.C.36): capture whether the latest engine response
// remains inside the SAME timed-choice countdown lifetime.
let MS_latestChoiceTimerContinues = false;

// ---> NEW (Phase 2.8.C.37): one continuous timed-choice lifetime.
// These are deliberately independent of keyboard/input locking because
// invalid submissions and their narrative response do NOT stop the clock.
let MS_choiceTimerActive = false;
let MS_choiceTimerTimeoutId = null;

// ---> NEW (Phase 2.8.C.45): render the player-facing countdown.
// Passing null hides it completely.
function MS_renderChoiceTimer(secondsLeft) {
  if (!choiceTimer) return;

  if (secondsLeft === null) {
    choiceTimer.textContent = "";
    choiceTimer.style.display = "none";
    return;
  }

  const wholeSeconds = Math.max(0, Math.ceil(Number(secondsLeft) || 0));

  choiceTimer.textContent = `⏳ ${String(wholeSeconds).padStart(2, "0")}s`;
  choiceTimer.style.display = "block";
}

// ---> NEW (Phase 2.8.C.38): start exactly one NEW timed-choice lifetime.
// This helper will eventually be called only when the timed choice has
// finished printing and actually becomes available to the player.
function MS_startChoiceTimer(seconds) {
  const startSeconds = Math.max(0, Math.ceil(Number(seconds) || 0));

  if (MS_choiceTimerTimeoutId !== null) {
    clearTimeout(MS_choiceTimerTimeoutId);
    MS_choiceTimerTimeoutId = null;
  }

  MS_choiceTimerActive = true;

  const tick = async (secondsLeft) => {
    // This callback owns both the visible digit and the next timer step.
    // No second clock runs alongside it.
    MS_renderChoiceTimer(secondsLeft);

    if (secondsLeft <= 0) {
      MS_choiceTimerTimeoutId = null;
      MS_choiceTimerActive = false;

      // The choice is logically over at zero, but preserve the current
      // keyboard/layout briefly so 00 remains part of the visible countdown.
      __msAwaitingInput = false;

      // Give zero a deliberate final beat before collapsing the input UI.
      await new Promise((resolve) => {
        setTimeout(resolve, 1000);
      });

      setGameplayInputEnabled(false);
      MS_renderChoiceTimer(null);

      try {
        await ensureMsPySession();
        await msPySendInput("__TIMEOUT__");
      } catch (e) {
        appendTranscriptLine(
          "[JS ERR] " + (e && e.message ? e.message : String(e))
        );
      }

      return;
    }

    MS_choiceTimerTimeoutId = setTimeout(() => {
      void tick(secondsLeft - 1);
    }, 1000);
  };

  void tick(startSeconds);
}

// ---> NEW (Phase 2.8.C.40): end the current timed-choice lifetime
// after the player has committed a valid answer.
function MS_cancelChoiceTimer() {
  if (MS_choiceTimerTimeoutId !== null) {
    clearTimeout(MS_choiceTimerTimeoutId);
  }

  MS_choiceTimerTimeoutId = null;
  MS_choiceTimerActive = false;

  // ---> NEW (Phase 2.8.C.49): timed-choice lifetime is over;
  // remove its player-facing countdown.
  MS_renderChoiceTimer(null);
}

function MS_applyVkbdFromChoices() {
  if (!__msUseVirtualKeyboard) return;

  // Phase 3.1: keyboard mode is driven only by engine state.
  if (MS_latestInputMode === VKBD_MODE_TEXT) {
    vkbSetMode(VKBD_MODE_TEXT);
    return;
  }

  if (MS_latestInputMode === VKBD_MODE_MINIMAL) {
    vkbSetMode(VKBD_MODE_MINIMAL);
  }
}

// Phase 1.1 timing rules
const LINE_INTERVAL_MS = 1400;     // linger longer
const MAX_LINES = 10;              // 10 lines per cycle
const BLACKOUT_MS = 350;           // brief beat after line 10

function MS_initDefaultLanguage() {
  // Respect any previously chosen language
  const existing = localStorage.getItem("ms_lang");
  if (existing) return existing;

  // Use browser language as the default signal
  const lang =
    (navigator.language && typeof navigator.language === "string")
      ? navigator.language
      : "en-US";

  localStorage.setItem("ms_lang", lang);
  return lang;
}

// Phase 3.0: never show VKBD during loading ritual
try { if (vkbd) vkbd.style.display = "none"; } catch {}
try { document.body.classList.remove("ms-vkbd-on"); } catch {}

let idx = 0;
let intervalId = null;
let inBlackout = false;
let loadingFatal = false;

// ---------------------------
// Phase 1.2 Audio Gate state
// ---------------------------
let audioGateEl = null;
let audioCtx = null;
let audioUnlocked = false;
let gateShowing = false;

// ---------------------------
// Phase 1.3 Audio Recovery state
// ---------------------------
let audioRecoverEl = null;
let recoverShowing = false;
let lastRecoverAttemptMs = 0;

// When we intentionally pause music (e.g., user toggles music OFF),
// do NOT show the Audio Recovery overlay.
let __msSuppressNextPauseOverlay = false;

// ---> NEW: watchdog interval id (prevents multiple installs)
let __msMenuMusicLoopWatchdogId = null;

function setBlackScreen(on) {
  // Full black screen means no text.
  loadingText.textContent = on ? "" : loadingText.textContent;
}

function showLine(i) {
  loadingText.textContent = LOADING_LINES[i];
}

function stopLoadingLoop() {
  if (intervalId !== null) {
    clearInterval(intervalId);
    intervalId = null;
  }
}

function proceedAfterLoading() {
  stopLoadingLoop();

  // Phase 2.2: prevent timeout from firing after we've already progressed
  if (loadingTimeoutId !== null) {
    clearTimeout(loadingTimeoutId);
    loadingTimeoutId = null;
  }

  loadingText.textContent = "";
  showAudioGate();
}

// ============================================================
// Phase 2.1 — Worker bridge helpers
// ============================================================

// --- Worker "set_source" bridge (we preload mind_song_engine.py in main thread) ---
let setSourceReqId = 1;
const setSourcePending = new Map();

function workerSetSource(name, text, { timeoutMs = 10000 } = {}) {
  if (!pyWorker) {
    return Promise.reject(new Error("Py worker not started yet."));
  }

  const id = setSourceReqId++;

  return new Promise((resolve, reject) => {
    setSourcePending.set(id, { resolve, reject });

    pyWorker.postMessage({
      type: "set_source",
      id,
      name: String(name || ""),
      text: String(text || ""),
    });

    setTimeout(() => {
      if (!setSourcePending.has(id)) return;
      setSourcePending.delete(id);
      reject(new Error("set_source timed out."));
    }, timeoutMs);
  });
}

// --- Preload mind_song_engine.py during the Excuses ritual (single loading round) ---
let msSourceText = "";
let msSourceReady = false;
let msSourceError = "";

async function preloadMindSongSource({ timeoutMs = 20000 } = {}) {
  if (msSourceReady || msSourceError) return;

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = new URL("mind_song_engine.py", window.location.href).href;
    const res = await fetch(url, { cache: "no-cache", signal: controller.signal });

    if (!res.ok) {
      throw new Error(`fetch(mind_song_engine.py) failed: ${res.status} ${res.statusText}`);
    }

    msSourceText = await res.text();

    // Push it into the worker cache (so Start does not load anything)
    await workerSetSource("mind_song_engine.py", msSourceText);

    msSourceReady = true;
  } catch (e) {
    msSourceError = (e && e.message) ? e.message : String(e);

    // Phase 2.2: fail fast — don't loop the ritual if engine source can't load
    showLoadingFatalError();
  } finally {
    clearTimeout(t);
  }
}

// ------------------------------------------------------------
// Phase 2.2 — Engine → UI prompt channel (non-narrative)
// ------------------------------------------------------------

// Control-line prefix (never rendered to transcript)
const MS_CTRL_PREFIX = "\x1eMS:";

const promptEl = document.getElementById("prompt");

function parseMsPyOut(rawOut) {
  const meta = {};
  const lines = [];

  if (!rawOut) return { lines, meta };

  const normalized = String(rawOut).replace(/\r\n/g, "\n");
  const parts = normalized.split("\n");

  if (parts.length && parts[parts.length - 1] === "") parts.pop();

  for (const line of parts) {
    if (line.startsWith(MS_CTRL_PREFIX)) {
      try {
        Object.assign(meta, JSON.parse(line.slice(MS_CTRL_PREFIX.length)));
      } catch {}
      continue;
    }
    lines.push(line ?? "");
  }

  return { lines, meta };
}

function applyEnginePrompt(promptStr) {
  if (!promptEl) return;

  // Render the prompt exactly (non-narrative control surface).
  // If prompt is blank/whitespace, hide it.
  const raw = String(promptStr ?? "");
  const trimmed = raw.trim();

  promptEl.textContent = trimmed ? raw : "";

  // ---> NEW: turn-based gate follows whether a real prompt is visible
  __msAwaitingInput = !!trimmed;
}

// ============================================================
// Phase 2.2.1 — Python-driven transcript scaffold
// (Proof of pipeline: JS input -> Python -> transcript output)
// ============================================================

let msPySessionReady = false;
let msEngineReady = false; // <-- NEW (engine contract readiness; NOT runtime readiness)

// ---> NEW (Phase 2.3): ensure we only attempt engine BOOT once during loading
let msBootRequested = false;

async function ensureMsPySession() {
  if (msPySessionReady) return;

  // Phase 2.2 plumbing: pick engine language once, before the engine is created.
  // NOTE: narrative text is unchanged; this only sets which language bucket the engine will use later.
  const uiLang = String(localStorage.getItem("ms_lang") || "en-US"); // "pt-BR" or "en-US"
  const engineLang = uiLang.toLowerCase().startsWith("pt") ? "pt_br" : "en";

  const code = `
import json

def _ms_emit(out):
    meta = out.get("meta") or {}
    ctrl = {
        "prompt": out.get("prompt", "") or "",
        "engine_ready": bool(meta.get("engine_ready", False)),
        "choices": out.get("choices", None),
        "input_mode": out.get("input_mode", None),
        # ---> NEW (Phase 2.8): carry the engine-owned timed-choice allowance
        # across the adapter boundary; JS does not act on it yet.
        "choice_timeout_seconds": meta.get("choice_timeout_seconds", None),
        # ---> NEW (Phase 2.8.C.35): tell JS that an invalid timed submission
        # remains inside the SAME countdown lifetime.
        "choice_timer_continues": bool(meta.get("choice_timer_continues", False)),
    }
    print("\x1eMS:" + json.dumps(ctrl, ensure_ascii=False))

    for line in out.get("lines", []):
        print(line)

from mind_song_engine import MindSongEngine

if "__ms_inited" not in globals():
    __ms_inited = True
    __ms_engine = MindSongEngine(lang=${JSON.stringify(engineLang)})

def ms_start():
    # Only start once per page session (prevents double-start spam)
    if getattr(__ms_engine, "_started", False):
        return
    _ms_emit(__ms_engine.start())

def ms_handle_input(s: str):
    _ms_emit(__ms_engine.step(s))

# ---> NEW (Phase 2.3): BOOT acknowledgment (control-only, never rendered)
print("\\x1eMS:" + json.dumps({"prompt": "", "engine_ready": True, "choices": None}, ensure_ascii=False))
`;

  // Phase 2.3: BOOT via engine contract
  const res = await workerEngineBoot(code, { timeoutMs: 20000 });

  if (res.err && res.err.trim()) {
    appendTranscriptLine(`[PY ERR] ${res.err.trim()}`);
  }

  if (res.out && res.out.length) {
    const parsed = parseMsPyOut(res.out);

    // Phase 2.2: capture engine readiness signal (engine contract), NOT runtime readiness
    if (parsed.meta.engine_ready === true) {
      msEngineReady = true;
    }

    // Phase 2.3 plumbing: keep latest choices (no UI rendering yet)
    if (parsed.meta.choices !== undefined) {
      MS_latestChoices = parsed.meta.choices;
      MS_applyVkbdFromChoices();
    }

    if (parsed.meta.prompt) {
      applyEnginePrompt(parsed.meta.prompt);
    }

    for (const line of parsed.lines) {
      appendTranscriptLine(line);
    }
  }

  msPySessionReady = true;
}

async function msPyStartGame() {
  const res = await workerEngineStart({ timeoutMs: 20000 });

  if (res.err && res.err.trim()) {
    appendTranscriptLine(`[PY ERR] ${res.err.trim()}`);
  }

  // Phase 2.4: STRICT turn-based behavior.
  // If START produced no stdout, do NOT unlock input. Just re-evaluate the gate.
  if (!res.out || !String(res.out).trim()) {
    appendTranscriptLine("[PY WARN] START produced no output.");
    maybeUnlockTurnInput();
    return;
  }

  const parsed = parseMsPyOut(res.out);

  if (parsed.meta.engine_ready === true) {
    msEngineReady = true;
  }

  // ---> NEW: capture engine-declared mode, but do not apply it yet
  if (parsed.meta.input_mode !== undefined) {
    MS_latestInputMode = parsed.meta.input_mode;
  }

  // ---> NEW (Phase 2.8.C.54): START owns its timer metadata just like
  // every later engine response. No stale timer state may cross turns.
  MS_latestChoiceTimeoutSeconds =
    parsed.meta.choice_timeout_seconds !== undefined
      ? parsed.meta.choice_timeout_seconds
      : null;

  MS_latestChoiceTimerContinues =
    parsed.meta.choice_timer_continues === true;

  if (parsed.meta.choices !== undefined) {
    MS_latestChoices = parsed.meta.choices;
    MS_applyVkbdFromChoices();
  }

  if (parsed.meta.prompt !== undefined) {
    applyEnginePrompt(parsed.meta.prompt);
  }

  // If START only updates meta (no lines), the prompt/gate decides whether input is enabled.
  if (!parsed.lines || parsed.lines.length === 0) {
    maybeUnlockTurnInput();
    return;
  }

  enqueueTranscriptLines(parsed.lines, {
    delayMs: GAME_LINE_DELAY_MS,
    initialBurst: GAME_INITIAL_BURST,
  });
}

async function msPySendInput(text) {
  const res = await workerEngineStep(String(text ?? ""), { timeoutMs: 20000 });

  if (res.err && res.err.trim()) {
    appendTranscriptLine(`[PY ERR] ${res.err.trim()}`);
  }

  if (res.out && res.out.trim()) {
    const parsed = parseMsPyOut(res.out);

      // ---> NEW: capture the engine-declared mode for this turn
    if (parsed.meta.input_mode !== undefined) {
      MS_latestInputMode = parsed.meta.input_mode;
    }

    // ---> NEW (Phase 2.8.C.54): every engine response owns its timer metadata.
    // If this response does not declare a new allowance, no stale allowance
    // from an earlier response may survive.
    MS_latestChoiceTimeoutSeconds =
      parsed.meta.choice_timeout_seconds !== undefined
        ? parsed.meta.choice_timeout_seconds
        : null;

    // ---> NEW (Phase 2.8.C.36): capture only; real-time timer behavior
    // is intentionally not implemented in this microstep.
    MS_latestChoiceTimerContinues =
      parsed.meta.choice_timer_continues === true;

    if (parsed.meta.prompt) {
      applyEnginePrompt(parsed.meta.prompt);
    }

    // Phase 2.6: keep latest structured choices synced.
    // Gameplay choices remain authored transcript lines and use the MINIMAL keyboard.
    if (parsed.meta.choices !== undefined) {
      MS_latestChoices = parsed.meta.choices;
      MS_applyVkbdFromChoices();
    }

    // Phase 2.4: prompt controls turn-taking.
    // If engine updated meta (like prompt) but produced no lines, just re-evaluate the gate.
    if (!parsed.lines || parsed.lines.length === 0) {
      maybeUnlockTurnInput();
      return;
    }

    enqueueTranscriptLines(parsed.lines, {
      delayMs: GAME_LINE_DELAY_MS,
      initialBurst: 0,
    });

    return;
  }

  // Phase 2.4: if Python produced no stdout, stay locked unless engine prompt says it's our turn.
  maybeUnlockTurnInput();
}

/* ---------------------------
   Phase 1.2.1 — Main Menu
--------------------------- */
function showMainMenu() {
  // Hide loading UI
  loadingScreen.style.display = "none";

  // Hide gameplay UI (if returning later)
  if (gameScreen) gameScreen.style.display = "none";

  // Show app UI
  appScreen.style.display = "flex";

  // Phase 3.1: NO VKBD in Main Menu (buttons only).

  // Ensure VKBD is hidden on menu
  try {
    if (vkbd) {
      vkbd.style.display = "none";
      vkbd.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("ms-vkbd-on");
  } catch {}

  // ---> NEW (Phase 2.4): reset viewport drift baseline on menu entry
  syncVisualViewportVars();
  forceViewportTop();

  // Title art (reuse the same banner text)
  MS_setMenuTitleArt();

  // Main menu labels (mobile UI — no numeric prefixes)
  if (btnStart) btnStart.textContent = "Start game";
  if (btnLanguage) btnLanguage.textContent = "Language";

  // Match mind_song.py numbering + current setting
  MS_updateMenuMusicButtonLabel();

  if (menuHint) menuHint.textContent = "";

  async function MS_handleMainMenuChoice(cmdRaw) {
    const cmd = String(cmdRaw || "").trim();

    if (cmd == "1") {
      // If preload is still in flight (or failed), handle it here gracefully.
      if (!msSourceReady && !msSourceError) {
        if (menuHint) menuHint.textContent = "(Finishing preload…)";
        await preloadMindSongSource();
      }

      if (msSourceError) {
        // Fail into the same canonical fatal screen (no alerts)
        appScreen.style.display = "none";
        loadingScreen.style.display = "flex";
        showLoadingFatalError();
        return;
      }

      // Switch to gameplay surface
      appScreen.style.display = "none";
      gameScreen.style.display = "flex";

      // Move VKBD under gameplay input row
      try {
        const gameInner = document.getElementById("gameInner");
        if (gameInner && vkbd) gameInner.appendChild(vkbd);
      } catch {}

      // ---> NEW (Phase 2.4): pre-focus viewport sync to reduce first keyboard/layout drift
      syncVisualViewportVars();
      forceViewportTop();

      // Lock input immediately on entering gameplay screen
      setGameplayInputEnabled(false);

      // Clear transcript (game output will now come from Python engine)
      transcriptBox.textContent = "";

      // ---> NEW (Phase 2.3): wipe non-narrative UI state so nothing stale leaks into a fresh Start
      applyEnginePrompt("");     // clears the visible ">" prompt
      MS_latestChoices = null;   // clears cached choices plumbing (UI for choices comes later)

      // ---> NEW (Phase 2.8.C.54): a fresh game is a hard timer boundary.
      // Nothing from a previous timed-choice lifetime may survive Start.
      MS_cancelChoiceTimer();
      MS_latestChoiceTimeoutSeconds = null;
      MS_latestChoiceTimerContinues = false;

      // Phase 2.3: BOOT should already be done during loading ritual.
      // Fallback: if something re-entered the menu without BOOT, recover safely.
      if (!msPySessionReady) {
        await ensureMsPySession(); // ---> fallback
      }

      await msPyStartGame();

      // Now wire input events (Enter key + button)
      wireGameplayInput();

      // Phase 2.4: do NOT force keyboard.
      // Let the engine prompt + printer completion decide when it's the player's TURN.
      maybeUnlockTurnInput();
      return;
    }

    if (cmd == "2") {
      MS_setMenuHintTemp("Language switching will be added later.");
      return;
    }

    if (cmd == "3") {
      const next = !MS_isMenuMusicOn();
      await MS_setMenuMusicOn(next);
      MS_setMenuHintTemp(`Music turned ${next ? "ON" : "OFF"}.`); // ---> NEW: transient, auto-clears
      return;
    }

    MS_setMenuHintTemp("Please tap a menu button.");
  }

  // Buttons route to the same choices
  if (btnStart) btnStart.onclick = () => MS_handleMainMenuChoice("1");
  if (btnLanguage) btnLanguage.onclick = () => MS_handleMainMenuChoice("2");
  if (btnMusic) btnMusic.onclick = () => MS_handleMainMenuChoice("3");

  // Menu uses no VKBD submit funnel
  __msActiveSubmitFn = null;
}

async function startMenuMusic() {
  if (!bgMusicEl) return;

  try {
    const dur = Number(bgMusicEl.duration);
    const endedOrNearEnd =
      bgMusicEl.ended ||
      (Number.isFinite(dur) && dur > 0 && bgMusicEl.currentTime >= dur - 0.05);

    if (!bgMusicEl.paused && !endedOrNearEnd) return;

    if (endedOrNearEnd && !bgMusicEl.paused) {
      try { bgMusicEl.pause(); } catch {}
    }

    // ---> NEW: revert failed low-volume clipping test; 0.22 made crackle slightly worse
    bgMusicEl.volume = 0.45;

    // Ensure looping even if the DOM attribute gets ignored by a browser.
    bgMusicEl.loop = true;

    // Only reset to start when the track naturally ended, not on every recovery/resume.
    if (endedOrNearEnd) {
      bgMusicEl.currentTime = 0;
    }

    await bgMusicEl.play();

    audioUnlocked = true;
  } catch (err) {
    console.warn("Menu music play() blocked:", err);
  }
}

// ============================================================
// Phase 1.2 — Audio Gate
// ============================================================

function ensureGateStyles() {
  if (document.getElementById("msAudioGateStyles")) return;

  const style = document.createElement("style");
  style.id = "msAudioGateStyles";
  style.textContent = `
    #msAudioGate {
      position: fixed;
      inset: 0;
      background: #000;
      color: #fff;
      display: none; /* shown via JS */
      align-items: center;
      justify-content: center;
      padding: 24px;
      box-sizing: border-box;
      z-index: 9999;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    #msAudioGateInner {
      width: 100%;
      max-width: 720px;
      text-align: center;
    }
    #msTitleArt {
      width: min(100%, 640px);
      margin: 0 auto 18px auto;
      display: block;
      user-select: none;
    }
    #msTitleArt svg {
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }
    #msPlayBox {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid #fff;
      padding: 12px 18px;
      border-radius: 10px;
      cursor: pointer;
      user-select: none;
      font-size: 18px;
      letter-spacing: 0.5px;
    }
    #msPlayBox:active {
      transform: translateY(1px);
    }
    #msHint {
      margin-top: 12px;
      opacity: 0.7;
      font-size: 12px;
      user-select: none;
    }
  `;
  document.head.appendChild(style);
}

function buildAudioGateIfNeeded() {
  if (audioGateEl) return;

  ensureGateStyles();

  audioGateEl = document.createElement("div");
  audioGateEl.id = "msAudioGate";

  const inner = document.createElement("div");
  inner.id = "msAudioGateInner";

  const title = document.createElement("div");
  title.id = "msTitleArt";

  // Use the embedded SVG directly; no external file request is involved.
  title.innerHTML = MS_TITLE_SVG;

  const play = document.createElement("div");
  play.id = "msPlayBox";
  play.textContent = "Play >";

  const hint = document.createElement("div");
  hint.id = "msHint";
  hint.textContent = "(Tap to begin)";

  play.addEventListener("click", async () => {
    await unlockAudio();
    hideAudioGate();

    // Start menu music only if the user preference is ON
    const raw = localStorage.getItem("ms_menu_music_on");
    const wantsMusic = (raw === null) ? true : (raw === "1");
    if (wantsMusic) {
      await startMenuMusic();
    } else {
      try { if (bgMusicEl) bgMusicEl.pause(); } catch {}
    }
    showMainMenu();
  });

  inner.appendChild(title);
  inner.appendChild(play);
  inner.appendChild(hint);
  audioGateEl.appendChild(inner);
  document.body.appendChild(audioGateEl);
}

function forceViewportTop() {
  // Some mobile browsers "drift" the page despite overflow hidden,
  // especially after repeated input focus + dynamic content growth.
  try {
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  } catch {}
}

function syncVisualViewportVars() {
  // Drive the CSS vars your style.css already expects:
  //   top: var(--vv-top)
  //   height: var(--vvh)
  //
  // This makes the fixed “screen” track the *visual* viewport correctly
  // when the keyboard appears, and prevents cumulative drift.
  try {
    const root = document.documentElement;

    if (window.visualViewport) {
      const vv = window.visualViewport;
      root.style.setProperty("--vv-top", `${vv.offsetTop || 0}px`);
      root.style.setProperty("--vvh", `${vv.height || window.innerHeight}px`);
    } else {
      root.style.setProperty("--vv-top", "0px");
      root.style.setProperty("--vvh", `${window.innerHeight}px`);
    }
  } catch {}
}

// ------------------------------------------------------------
// Scroll Jail (Android focus/keyboard scroll drift killer)
// Keeps the PAGE pinned at (0,0) so ONLY #transcriptBox scrolls.
// ------------------------------------------------------------

// ---> NEW: moved up so Scroll Jail can safely reference it during initial install
const MS_TRANSCRIPT_NEAR_BOTTOM_SLACK_PX = 32; // ~2 lines cushion

let __msScrollJailInstalled = false;

function installScrollJail() {
  if (__msScrollJailInstalled) return;
  __msScrollJailInstalled = true;

  let raf = 0;

  const isTranscriptNearBottom = () => {
    if (!transcriptBox) return false;
    const distanceFromBottom =
      transcriptBox.scrollHeight - transcriptBox.scrollTop - transcriptBox.clientHeight;
    return distanceFromBottom <= MS_TRANSCRIPT_NEAR_BOTTOM_SLACK_PX;
  };

  const snapTranscriptToBottom = () => {
    if (!transcriptBox) return;
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  };

  const scheduleSnap = () => {
    if (raf) return;

    // Capture whether the player was “at the bottom” BEFORE the keyboard/viewport shift.
    const wasNearBottom = isTranscriptNearBottom();

    raf = requestAnimationFrame(() => {
      raf = 0;
      syncVisualViewportVars();
      forceViewportTop();

      // If they were reading the latest line, keep them there after keyboard settles.
      if (wasNearBottom) {
        snapTranscriptToBottom();
      }
    });
  };

  window.addEventListener(
    "scroll",
    () => {
      if (window.scrollX !== 0 || window.scrollY !== 0) scheduleSnap();
    },
    { passive: true }
  );

  document.addEventListener("focusin", scheduleSnap, true);
  document.addEventListener("focusout", scheduleSnap, true);

  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scheduleSnap, { passive: true });
    window.visualViewport.addEventListener("scroll", scheduleSnap, { passive: true });
  }

  scheduleSnap();
}

function appendTranscriptLine(line = "") {
  if (!transcriptBox) return;

  transcriptBox.textContent += String(line) + "\n";

  requestAnimationFrame(() => {
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  });
}

// Install immediately (app.js runs after DOM nodes exist)
installScrollJail();

// ------------------------------------------------------------
// Phase 2.8 — Timing profile
// Preserves ALL lines exactly, including blank lines.
// ------------------------------------------------------------
const MS_TIMING_MODE = "TESTING";

const MS_TIMING_DELAYS_MS = Object.freeze({
  TESTING: 1000,
  SHIPPING: 2500,
});

const GAME_LINE_DELAY_MS = MS_TIMING_DELAYS_MS[MS_TIMING_MODE];
const GAME_INITIAL_BURST = 1;    // print at least 1 line instantly (prevents “blank screen” feel)

let __msPrintQueue = [];
let __msPrinting = false;

// ---> NEW (Phase 2.4): strict turn-based input gate (engine prompt must be visible)
let __msAwaitingInput = false;

function maybeUnlockTurnInput() {
  // Only unlock if:
  // 1) engine is currently asking for input
  // 2) there is no paced printing still happening
  // 3) there is no queued transcript waiting to print
  const noPendingPrint = (!__msPrinting) && (__msPrintQueue.length === 0);

  if (__msAwaitingInput && noPendingPrint) {
    // ---> NEW (Phase 2.8.C.54): consume a NEW timed-choice allowance exactly
    // once, at the moment the fully printed choice becomes playable.
    if (
      MS_choiceTimerActive === false &&
      MS_latestChoiceTimerContinues === false &&
      MS_latestChoiceTimeoutSeconds !== null
    ) {
      const timeoutSeconds = MS_latestChoiceTimeoutSeconds;
      MS_latestChoiceTimeoutSeconds = null;
      MS_startChoiceTimer(timeoutSeconds);
    }

    setGameplayInputEnabled(true);
    focusGameplayInput();
    return;
  }

  // Otherwise: keep it locked and keep OS keyboard away
  setGameplayInputEnabled(false);

  if (gameInput && document.activeElement === gameInput) {
    try {
      gameInput.blur();
    } catch {}
  }
}

// NEW: Lock/unlock gameplay input while transcript is printing.
// Prevents player from racing ahead of paced narrative output.
function setGameplayInputEnabled(enabled) {
  try {
    if (gameInput) {
      gameInput.disabled = !enabled;
      gameInput.style.pointerEvents = enabled ? "auto" : "none";
    }

    if (btnEnter) {
      btnEnter.disabled = !enabled;
      btnEnter.style.pointerEvents = enabled ? "auto" : "none";
    }

    // ---> Phase 3.1 micro-step: VKBD auto-summon ONLY on the player's turn
    if (vkbd) {
      const shouldShowVkbd =
        (__msUseVirtualKeyboard === true) &&
        (enabled === true) &&
        (__msAwaitingInput === true);

      vkbd.style.display = shouldShowVkbd ? "flex" : "none";
      vkbd.setAttribute("aria-hidden", shouldShowVkbd ? "false" : "true");

      // Keep layout padding in sync with actual VKBD visibility.
      // (Fixes: transcript box staying "small" when VKBD is hidden.)
      document.body.classList.toggle("ms-vkbd-on", shouldShowVkbd);

      // ---> Phase 3.0: VKBD lock visuals + hard-disable
      vkbd.setAttribute("aria-disabled", enabled ? "false" : "true");
      vkbd.style.pointerEvents = enabled ? "auto" : "none";

      if (!enabled) {
        vkbd.querySelectorAll("button").forEach((b) => {
          b.disabled = true;
        });
      } else {
        vkbd.dataset.mode = "";
        vkbEnsureScaffold();

        // ---> NEW (Phase 2.8.C.54.3D): showing the VKBD contracts the
        // transcript viewport. Re-anchor after that layout change settles.
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (transcriptBox) {
              transcriptBox.scrollTop = transcriptBox.scrollHeight;
            }
          });
        });
      }
    }
  } catch {}
}

function enqueueTranscriptLines(
  lines,
  { delayMs = GAME_LINE_DELAY_MS, initialBurst = GAME_INITIAL_BURST } = {}
) {
  const arr = Array.isArray(lines) ? lines : [];
  if (!arr.length) return;

  // Enqueue lines exactly as received (including "")
  __msPrintQueue.push(...arr.map((x) => (x === undefined || x === null) ? "" : String(x)));

  // Phase 2.4: STRICT turn-based behavior.
  // While ANY paced output is pending/printing, input must be locked.
  setGameplayInputEnabled(false);

  // Kick the printer if it’s idle
  if (!__msPrinting) {
    drainTranscriptQueue({ delayMs, initialBurst });
  }
}

function drainTranscriptQueue({ delayMs, initialBurst } = {}) {
  if (__msPrinting) return;
  __msPrinting = true;

  // Print a “burst” immediately (helps avoid perceived blank screen)
  let burstLeft = Math.max(0, Number(initialBurst) || 0);
  while (burstLeft > 0 && __msPrintQueue.length) {
    appendTranscriptLine(__msPrintQueue.shift());
    burstLeft--;
  }

  const finish = () => {
    __msPrinting = false;

    // Unlock ONLY if engine is awaiting input AND nothing else is pending
    maybeUnlockTurnInput();
  };

  const tick = () => {
    if (!__msPrintQueue.length) {
      finish();
      return;
    }

    appendTranscriptLine(__msPrintQueue.shift());
    setTimeout(tick, Math.max(0, Number(delayMs) || 0));
  };

  // If queue still has more, pace it out
  if (__msPrintQueue.length) {
    setTimeout(tick, Math.max(0, Number(delayMs) || 0));
  } else {
    finish();
  }
}

function focusGameplayInput() {
  if (!gameInput) return;

  // Phase 3.0: when virtual keyboard is in charge, NEVER focus the input
  // (focusing triggers OS keyboard + viewport drift on mobile).
  if (__msUseVirtualKeyboard) {
    try { gameInput.blur(); } catch {}
    return;
  }

  // ---> NEW: don't pop keyboard / trigger viewport drift while input is locked
  if (gameInput.disabled) return;

  // If we already have focus, DON'T re-focus (this is what triggers drift over time).
  if (document.activeElement === gameInput) return;

  try {
    gameInput.focus({ preventScroll: true });
  } catch {
    // Fallback for browsers that don't support preventScroll
    gameInput.focus();
  }

  // One gentle snap AFTER focus (not before + after)
  requestAnimationFrame(() => {
    forceViewportTop();
  });
}

// Phase 2.4: input wiring guard (prevents double-binding)
let __msGameplayInputWired = false;

function wireGameplayInput() {
  if (__msGameplayInputWired) return;
  if (!gameInput || !btnEnter || !gameScreen) return;

  __msGameplayInputWired = true;

  try {
    gameInput.readOnly = true;
    gameInput.setAttribute("readonly", "readonly");
    gameInput.inputMode = "none";
    gameInput.autocapitalize = "off";
    gameInput.autocomplete = "off";
    gameInput.spellcheck = false;

    gameInput.addEventListener("focus", () => {
      try { gameInput.blur(); } catch {}
    }, { passive: true });
  } catch {}

  vkbSyncToDisplay();

  if (__msUseVirtualKeyboard) {
    vkbEnsureScaffold();
    // VKBD visibility + layout padding is controlled by setGameplayInputEnabled()
    if (vkbd) vkbd.style.display = "none";
  } else {
    if (vkbd) vkbd.style.display = "none";
  }

  const submitInput = async () => {
    if (gameInput.disabled || btnEnter.disabled) return;

    const s = __msUseVirtualKeyboard
      ? vkbConsumeTrimmed()
      : String(gameInput.value || "").trim();

    if (!s) return;

    // ---> NEW (Phase 2.8.C.40): only a VALID answer ends an active
    // timed-choice lifetime. Junk input leaves the same clock running.
    if (
      MS_choiceTimerActive === true &&
      (s === "1" || s === "2")
    ) {
      MS_cancelChoiceTimer();
    }

    appendTranscriptLine(`> ${s}`);

    if (__msUseVirtualKeyboard) vkbClearBuffer();
    else gameInput.value = "";

    setGameplayInputEnabled(false);
    __msAwaitingInput = false;

    try {
      await ensureMsPySession();
      await msPySendInput(s);
    } catch (e) {
      appendTranscriptLine("[JS ERR] " + (e && e.message ? e.message : String(e)));
      setGameplayInputEnabled(true);
    }

    focusGameplayInput();
  };

  // Phase 3.1: VKBD Enter uses the shared active-submit funnel.
  __msActiveSubmitFn = submitInput;

  btnEnter.onclick = (ev) => {
    if (btnEnter.disabled || gameInput.disabled) {
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }

    submitInput();
  };

  gameInput.onkeydown = (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      submitInput();
    }
  };

  gameScreen.addEventListener(
    "click",
    () => {
      if (gameInput.disabled) return;
      focusGameplayInput();
    },
    { passive: true }
  );
}

function showAudioGate() {
  buildAudioGateIfNeeded();

  gateShowing = true;
  audioGateEl.style.display = "flex";

  // Keep the underlying loading screen dark/blank
  loadingText.textContent = "";
}

function hideAudioGate() {
  gateShowing = false;
  if (audioGateEl) audioGateEl.style.display = "none";
}

async function unlockAudio() {
  if (audioUnlocked) return;

  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) {
      audioCtx = audioCtx || new AC();
      if (audioCtx.state !== "running") {
        await audioCtx.resume();
      }

      // “Warm” the audio graph with a near-silent tick.
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      gain.gain.value = 0.00001;
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.02);
    }

    audioUnlocked = true;
  } catch (err) {
    console.warn("Audio unlock failed:", err);
    audioUnlocked = false;
  }
}

// ============================================================
// Phase 1.3 — Audio Recovery Safety Nets
// ============================================================

function ensureRecoverStyles() {
  if (document.getElementById("msAudioRecoverStyles")) return;

  const style = document.createElement("style");
  style.id = "msAudioRecoverStyles";
  style.textContent = `
    #msAudioRecover {
      position: fixed;
      inset: 0;
      background: #000;
      color: #fff;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      box-sizing: border-box;
      z-index: 10000; /* above gate just in case */
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    #msAudioRecoverInner {
      width: 100%;
      max-width: 720px;
      text-align: center;
    }
    #msRecoverPlayBox {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid #fff;
      padding: 12px 18px;
      border-radius: 10px;
      cursor: pointer;
      user-select: none;
      font-size: 18px;
      letter-spacing: 0.5px;
    }
    #msRecoverPlayBox:active {
      transform: translateY(1px);
    }
    #msRecoverHint {
      margin-top: 12px;
      opacity: 0.7;
      font-size: 12px;
      user-select: none;
    }
  `;
  document.head.appendChild(style);
}

function buildAudioRecoverIfNeeded() {
  if (audioRecoverEl) return;

  ensureRecoverStyles();

  audioRecoverEl = document.createElement("div");
  audioRecoverEl.id = "msAudioRecover";

  const inner = document.createElement("div");
  inner.id = "msAudioRecoverInner";

  const play = document.createElement("div");
  play.id = "msRecoverPlayBox";
  play.textContent = "Play >";

  const hint = document.createElement("div");
  hint.id = "msRecoverHint";
  hint.textContent = "(Tap to resume audio)";

  play.addEventListener("click", async () => {
    await attemptAudioRecovery({ forceOverlayTap: true });
  });

  inner.appendChild(play);
  inner.appendChild(hint);
  audioRecoverEl.appendChild(inner);
  document.body.appendChild(audioRecoverEl);
}

function showAudioRecoverOverlay() {
  buildAudioRecoverIfNeeded();
  recoverShowing = true;
  audioRecoverEl.style.display = "flex";
}

function hideAudioRecoverOverlay() {
  recoverShowing = false;
  if (audioRecoverEl) audioRecoverEl.style.display = "none";
}

let __msGameplayTimersPaused = false; // ---> NEW (Phase 2.8): fairness timing state

function pauseGameplayTimers() {
  __msGameplayTimersPaused = true; // ---> NEW: future gameplay timers must stop while this is true
}

function resumeGameplayTimersAndResetFairly() {
  __msGameplayTimersPaused = false; // ---> NEW: future timer implementation will reset its full allowance here
}

function shouldAttemptAutoRecovery() {
  // Don’t fight the gate, and don’t spam attempts.
  if (!audioUnlocked) return false;
  if (gateShowing) return false;
  if (!bgMusicEl) return false;

  // Respect explicit user choice: if menu music is OFF, never auto-recover it.
  if (!MS_isMenuMusicOn()) return false;

  // Only care after we've reached the real app screen.
  const appVisible = appScreen && appScreen.style.display !== "none";
  if (!appVisible) return false;

  // If music is already playing, we're good.
  if (!bgMusicEl.paused) return false;

  // Throttle attempts.
  const now = Date.now();
  if (now - lastRecoverAttemptMs < 800) return false;

  return true;
}

async function attemptAudioRecovery({ forceOverlayTap = false } = {}) {
  lastRecoverAttemptMs = Date.now();

  // If we’re in a forced tap, we can hide overlay *after* success.
  try {
    await unlockAudio();

    // Try to resume music (route through canonical starter so loop/currentTime are enforced)
    if (bgMusicEl && bgMusicEl.paused) {
      await startMenuMusic(); // ---> NEW
    }

    // Success
    if (recoverShowing) hideAudioRecoverOverlay();
    resumeGameplayTimersAndResetFairly();
  } catch (err) {
    // Still blocked -> show overlay + pause “timers”
    console.warn("Audio recovery blocked:", err);
    pauseGameplayTimers();
    showAudioRecoverOverlay();
  }
}

function installAudioRecoverySafetyNets() {
  if (!bgMusicEl) return;

  // ---> NEW: prevent duplicate listener installs if this function is called more than once
  if (installAudioRecoverySafetyNets._installed) return;
  installAudioRecoverySafetyNets._installed = true;

  // ---> NEW: force-loop fallback for browsers that ignore <audio loop> / .loop
  bgMusicEl.addEventListener("ended", async () => {
    if (!audioUnlocked) return;
    if (gateShowing) return;

    const raw = localStorage.getItem("ms_menu_music_on");
    const wantsMusic = (raw === null) ? true : (raw === "1");
    if (!wantsMusic) return;

    const appVisible = appScreen && appScreen.style.display !== "none";
    if (!appVisible) return;

    try {
      // Some browsers fire a pause event as the track ends.
      // Suppress the overlay for this "natural end" restart.
      __msSuppressNextPauseOverlay = true; // ---> NEW

      await startMenuMusic(); // ---> NEW: route through canonical starter (enforces loop + currentTime)
    } catch (err) {
      console.warn("Menu music restart blocked after ended:", err);
      pauseGameplayTimers();
      showAudioRecoverOverlay();
    }
  });

  // If audio drops (pause/ended) while app is visible, show overlay.
  bgMusicEl.addEventListener("pause", () => {
    // If we intentionally paused (e.g., user toggled music OFF),
    // do NOT show the recovery overlay.
    if (__msSuppressNextPauseOverlay) {
      __msSuppressNextPauseOverlay = false;
      return;
    }

    if (!audioUnlocked) return;
    if (gateShowing) return;

    // If the user preference is music OFF, a pause is expected.
    const raw = localStorage.getItem("ms_menu_music_on");
    const wantsMusic = (raw === null) ? true : (raw === "1");
    if (!wantsMusic) return;

    const appVisible = appScreen && appScreen.style.display !== "none";
    if (!appVisible) return;

    // If it paused and we didn't explicitly cause it, show overlay.
    // (We don't have a "user paused" control, so this is fine.)
    pauseGameplayTimers();
    showAudioRecoverOverlay();
  });

  // Any “gesture-ish” interaction tries to restore audio first.
  const gestureHandler = () => {
    if (!shouldAttemptAutoRecovery()) return;
    attemptAudioRecovery();
  };

  window.addEventListener("keydown", gestureHandler, { passive: true });
  window.addEventListener("mousedown", gestureHandler, { passive: true });
  window.addEventListener("touchstart", gestureHandler, { passive: true });

  // If tab/app comes back, try to restore.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (!shouldAttemptAutoRecovery()) return;
      attemptAudioRecovery();
    }
  });
}

// ---> NEW: actually install the listeners (this was missing)
installAudioRecoverySafetyNets();

// ============================================================
// Phase 1.1 tick loop
// ============================================================

function tick() {
  if (loadingFatal) return;

  // Phase 2.3: once runtime + source are ready, BOOT the engine harness exactly once
  if (runtimeReady && msSourceReady && !msEngineReady && !msBootRequested) {
    msBootRequested = true;

    ensureMsPySession().catch((e) => {
      console.error("Engine BOOT failed:", e);
      showLoadingFatalError();
    });
  }

  // Phase 2.3: only proceed when runtime + source + engine BOOT are all ready
  if (runtimeReady && msSourceReady && msEngineReady) {
    proceedAfterLoading();
    return;
  }

  if (inBlackout) {
    // blackout beat finished -> loop back to line 1
    inBlackout = false;
    idx = 0;
    showLine(idx);
    idx += 1;
    return;
  }

  // Show next line
  if (idx < MAX_LINES) {
    showLine(idx);
    idx += 1;
    return;
  }

  // After line 10 -> full black screen for a brief beat, then loop
  inBlackout = true;
  setBlackScreen(true);

  setTimeout(() => {
    if (runtimeReady && msSourceReady && msEngineReady) {
      proceedAfterLoading();
      return;
    }
    setBlackScreen(false);
  }, BLACKOUT_MS);
}

// ============================================================
// Phase 1 — Manual Runtime Control (DEV ONLY)
// ============================================================
// Allows testing the transition without Pyodide wired yet.
// Usage in DevTools:
//   MS_setRuntimeReady(true)
window.MS_setRuntimeReady = function (value = true) {
  runtimeReady = !!value;

  // Match tick() Phase 2.3 gate exactly:
  // runtime + source -> BOOT engine once -> proceed only after BOOT ready.
  if (runtimeReady && msSourceReady && !msEngineReady && !msBootRequested) {
    msBootRequested = true;

    ensureMsPySession().catch((e) => {
      console.error("Engine BOOT failed:", e);
      showLoadingFatalError();
    });
  }

  if (runtimeReady && msSourceReady && msEngineReady) {
    proceedAfterLoading();
  }
};

// ============================================================
// Phase 1.1 — Loading Ritual Timeout Fail-Safe
// ============================================================

const LOADING_TIMEOUT_MS = 15000; // 15s hard stop (dev + player safety)
let loadingTimeoutId = null;

function showLoadingFatalError() {
  loadingFatal = true;
  stopLoadingLoop();

  // Phase 2.2: ensure fatal state is single-fire (no duplicate timeout triggers)
  if (loadingTimeoutId !== null) {
    clearTimeout(loadingTimeoutId);
    loadingTimeoutId = null;
  }

  loadingText.textContent =
`Black box detected.
Memory playback interrupted.
Awaiting signal. Reload required.`;

  loadingText.style.whiteSpace = "pre";
  loadingText.style.textAlign = "left";
  loadingText.style.margin = "0 auto";
  loadingText.style.maxWidth = "32ch";
}

function armLoadingTimeout() {
  if (loadingTimeoutId !== null) return;

  loadingTimeoutId = setTimeout(() => {
    // Phase 2.3: require runtime + source + engine BOOT
    if (!(runtimeReady && msSourceReady && msEngineReady)) {
      showLoadingFatalError();
    }
  }, LOADING_TIMEOUT_MS);
}

function startLoadingScreen() {
  MS_initDefaultLanguage();

  // Always on first load & refresh
  idx = 0;
  inBlackout = false;
  showLine(idx);
  idx += 1;

  intervalId = setInterval(tick, LINE_INTERVAL_MS);
  armLoadingTimeout();
}

// ============================================================
// Phase 2.1 — Pyodide runtime init (Web Worker)
// ============================================================

let pyWorker = null;

// Simple request/response bridge for running Python in the worker
let pyReqId = 1;
const pyPending = new Map();

// ------------------------------------------------------------
// Phase 2.3 — Engine message contract (BOOT / START / STEP)
// ------------------------------------------------------------
// ---> NEW: stable engine-level messages (separate from generic "run")
let engineReqId = 1;
const enginePending = new Map();

function engineCall(type, payload = {}, { timeoutMs = 20000 } = {}) {
  if (!pyWorker) {
    return Promise.reject(new Error("Py worker not started yet."));
  }

  const id = engineReqId++;

  return new Promise((resolve, reject) => {
    enginePending.set(id, { resolve, reject });

    pyWorker.postMessage({
      type,
      id,
      ...payload,
    });

    setTimeout(() => {
      if (!enginePending.has(id)) return;
      enginePending.delete(id);
      reject(new Error(`${type} timed out.`));
    }, timeoutMs);
  });
}

function workerEngineBoot(code, { timeoutMs = 20000 } = {}) {
  return engineCall("engine_boot", { code: String(code || "") }, { timeoutMs });
}

function workerEngineStart({ timeoutMs = 20000 } = {}) {
  return engineCall("engine_start", {}, { timeoutMs });
}

function workerEngineStep(input, { timeoutMs = 20000 } = {}) {
  return engineCall("engine_step", { input: String(input ?? "") }, { timeoutMs });
}

function pyRun(code, { timeoutMs = 15000 } = {}) {
  if (!pyWorker) {
    return Promise.reject(new Error("Py worker not started yet."));
  }

  const id = pyReqId++;

  return new Promise((resolve, reject) => {
    pyPending.set(id, { resolve, reject });

    pyWorker.postMessage({
      type: "run",
      id,
      code: String(code || ""),
    });

    setTimeout(() => {
      if (!pyPending.has(id)) return;
      pyPending.delete(id);
      reject(new Error("Python run timed out."));
    }, timeoutMs);
  });
}

// Optional: dev helper
window.MS_pyRun = (code) => pyRun(code);

function initPyodideRuntimeWorker() {
  // Phase 2.3: if the worker dies, immediately reject all pending calls
  // so UI doesn't "hang" until timeouts.
  const rejectAllPending = (reason) => {
    const err = new Error(String(reason || "Py worker failure."));

    for (const [, p] of setSourcePending) {
      try { p.reject(err); } catch {}
    }
    setSourcePending.clear();

    for (const [, p] of pyPending) {
      try { p.reject(err); } catch {}
    }
    pyPending.clear();

    for (const [, p] of enginePending) {
      try { p.reject(err); } catch {}
    }
    enginePending.clear();
  };

  const fatalWorkerFailure = (reason) => {
    runtimeReady = false;
    rejectAllPending(reason);
    showLoadingFatalError(); // same canonical failure screen
  };

  try {
    pyWorker = new Worker("py_worker.js");

    pyWorker.onmessage = (ev) => {
      const msg = ev.data || {};

      if (msg.type === "ready") {
        // Pyodide runtime is ready, but engine readiness is gated separately.
        // Do NOT advance loading ritual here.
        runtimeReady = true;
        return;
      }

      // ✅ REQUIRED for preload completion
      if (msg.type === "set_source_ok") {
        const pending = setSourcePending.get(msg.id);
        if (!pending) return;
        setSourcePending.delete(msg.id);

        pending.resolve({
          name: msg.name || "",
          size: msg.size || 0,
          head: msg.head || "",
        });
        return;
      }

      if (msg.type === "py_result") {
        const pending = pyPending.get(msg.id);
        if (!pending) return;
        pyPending.delete(msg.id);
        pending.resolve({ out: msg.out || "", err: msg.err || "" });
        return;
      }

      if (msg.type === "py_error") {
        const pending = pyPending.get(msg.id);
        if (!pending) return;
        pyPending.delete(msg.id);
        pending.reject(new Error(msg.error || "Unknown python worker error."));
        return;
      }

      // ---> Phase 2.3 engine contract messages
      if (msg.type === "engine_out") {
        const pending = enginePending.get(msg.id);
        if (!pending) return;
        enginePending.delete(msg.id);
        pending.resolve({ out: msg.out || "", err: msg.err || "" });
        return;
      }

      if (msg.type === "engine_err") {
        const pending = enginePending.get(msg.id);
        if (!pending) return;
        enginePending.delete(msg.id);
        pending.reject(new Error(msg.error || "Unknown engine error."));
        return;
      }

      // Worker-level fatal
      if (msg.type === "error") {
        console.error("Pyodide worker error:", msg.error);
        fatalWorkerFailure(msg.error || "Pyodide worker error.");
      }
    };

    pyWorker.onerror = (err) => {
      console.error("Pyodide worker crashed:", err);
      fatalWorkerFailure("Pyodide worker crashed.");
    };
  } catch (err) {
    console.error("Failed to start Pyodide worker:", err);
    fatalWorkerFailure("Failed to start Pyodide worker.");
  }
}

// Phase 1.3 — install audio recovery safety nets
installAudioRecoverySafetyNets();

// Start Phase 1.1 ritual immediately (excuses scroll no matter what)
startLoadingScreen();

// Begin runtime initialization in the background worker
initPyodideRuntimeWorker();

// IMPORTANT: preload mind_song_engine.py during the Excuses ritual (single loading round)
preloadMindSongSource();

