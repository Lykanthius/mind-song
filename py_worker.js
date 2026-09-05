// py_worker.js
// Loads Pyodide off the main thread so the loading ritual can animate smoothly.

let pyodideReadyPromise = null;

function asErrorString(err) {
  return (err && (err.stack || err.message)) ? (err.stack || err.message) : String(err);
}

async function ensurePyodideReady() {
  if (!pyodideReadyPromise) {
    pyodideReadyPromise = (async () => {
      importScripts("https://cdn.jsdelivr.net/pyodide/v0.29.2/full/pyodide.js");
      self.pyodide = await loadPyodide({
        indexURL: "https://cdn.jsdelivr.net/pyodide/v0.29.2/full/",
      });
      return self.pyodide;
    })();
  }
  return pyodideReadyPromise;
}

async function runPythonCaptureStdout(code) {
  const py = await ensurePyodideReady();

  // Pass JS string into Python safely
  py.globals.set("__ms_code", code);

  // Capture stdout + traceback
  await py.runPythonAsync(`
import sys, io, traceback

_buf = io.StringIO()
_old = sys.stdout
sys.stdout = _buf
_err = ""

try:
    exec(__ms_code, globals())
except Exception:
    _err = traceback.format_exc()
finally:
    sys.stdout = _old

_out = _buf.getvalue()
`);

  const out = String(py.globals.get("_out") || "");
  const err = String(py.globals.get("_err") || "");

  // Cleanup
  try { py.globals.delete("_out"); } catch {}
  try { py.globals.delete("_err"); } catch {}
  try { py.globals.delete("__ms_code"); } catch {}

  return { out, err };
}

async function fetchTextFile(path, { timeoutMs = 25000 } = {}) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(path, {
      cache: "no-cache",
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`fetch(${path}) failed: ${res.status} ${res.statusText}`);
    }

    return await res.text();
  } catch (e) {
    // Normalize abort errors into a readable message
    if (e && (e.name === "AbortError" || String(e).includes("AbortError"))) {
      throw new Error(`fetch(${path}) aborted after ${timeoutMs}ms`);
    }
    throw e;
  } finally {
    clearTimeout(t);
  }
}

// Handle commands from main thread
const SOURCE_CACHE = Object.create(null);

// Track what we've written into the Pyodide filesystem to avoid redundant writes
const SOURCE_FS_STAMP = Object.create(null);

function _makeStamp(text) {
  // Cheap change detector (good enough for our use case)
  const s = String(text || "");
  return `${s.length}:${s.slice(0, 80)}`;
}

async function syncSourceToFS(name, text) {
  const py = await ensurePyodideReady();

  const fileName = String(name || "").trim();
  if (!fileName) return;

  const stamp = _makeStamp(text);
  if (SOURCE_FS_STAMP[fileName] === stamp) return;

  // Write into Pyodide FS so normal Python imports work
  py.FS.writeFile(fileName, String(text || ""), { encoding: "utf8" });

  SOURCE_FS_STAMP[fileName] = stamp;
}

async function syncAllSourcesToFS() {
  const entries = Object.entries(SOURCE_CACHE);
  for (const [name, text] of entries) {
    await syncSourceToFS(name, text);
  }
}

self.onmessage = async (ev) => {
  const msg = ev.data || {};

  if (msg.type === "set_source") {
    const id = msg.id;
    const name = String(msg.name || "");
    const text = String(msg.text || "");

    SOURCE_CACHE[name] = text;

    // NEW: also mirror into Pyodide FS so Python can import it later
    try {
      await syncSourceToFS(name, text);
    } catch {
      // If FS sync fails (rare), keep cache anyway; run() will retry syncAllSourcesToFS().
    }

    self.postMessage({
      type: "set_source_ok",
      id,
      name,
      size: text.length,
      head: text.slice(0, 240),
    });
    return;
  }

  if (msg.type === "fetch_text") {
    const id = msg.id;
    const path = String(msg.path || "");
    try {
      const text = await fetchTextFile(path);
      self.postMessage({
        type: "fetch_text_result",
        id,
        path,
        size: text.length,
        head: text.slice(0, 240),
      });
    } catch (e) {
      self.postMessage({
        type: "fetch_text_error",
        id,
        path,
        error: asErrorString(e),
      });
    }
    return;
  }

  // ------------------------------------------------------------
  // Phase 2.3 — Engine contract handlers
  // ------------------------------------------------------------
  const normalizeOutErr = (result) => {
    const out = (result && result.out != null) ? String(result.out) : "";
    const err = (result && result.err != null) ? String(result.err) : "";
    return { out, err };
  };

  if (msg.type === "engine_boot") {
    const id = msg.id;
    try {
      await syncAllSourcesToFS();
      const code = String(msg.code || "");
      const { out, err } = normalizeOutErr(await runPythonCaptureStdout(code));
      self.postMessage({ type: "engine_out", id, out, err });
    } catch (e) {
      self.postMessage({ type: "engine_err", id, error: asErrorString(e) });
    }
    return;
  }

  if (msg.type === "engine_start") {
    const id = msg.id;
    try {
      await syncAllSourcesToFS();
      const { out, err } = normalizeOutErr(await runPythonCaptureStdout("ms_start()\n"));
      self.postMessage({ type: "engine_out", id, out, err });
    } catch (e) {
      self.postMessage({ type: "engine_err", id, error: asErrorString(e) });
    }
    return;
  }

  if (msg.type === "engine_step") {
    const id = msg.id;
    try {
      await syncAllSourcesToFS();

      const payload = JSON.stringify(String(msg.input ?? ""));
      const code = `_s = ${payload}\nms_handle_input(_s)\n`;

      const { out, err } = normalizeOutErr(await runPythonCaptureStdout(code));
      self.postMessage({ type: "engine_out", id, out, err });
    } catch (e) {
      self.postMessage({ type: "engine_err", id, error: asErrorString(e) });
    }
    return;
  }

  // Legacy generic runner (still used by dev helpers / anything non-engine)
  if (msg.type === "run") {
    const id = msg.id;
    try {
      // NEW: ensure all cached sources exist in Pyodide FS before executing code
      await syncAllSourcesToFS();

      const { out, err } = normalizeOutErr(
        await runPythonCaptureStdout(String(msg.code || ""))
      );

      self.postMessage({ type: "py_result", id, out, err });
    } catch (e) {
      self.postMessage({ type: "py_error", id, error: asErrorString(e) });
    }
    return;
  }
};

// Boot immediately so we can still signal readiness for the ritual gate logic
(async function boot() {
  try {
    await ensurePyodideReady();
    self.postMessage({ type: "ready" });
  } catch (err) {
    self.postMessage({ type: "error", error: asErrorString(err) });
  }
})();
