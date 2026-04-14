const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const os = require("os");
const crypto = require("crypto");
const { ErrorCodes } = require("./error-codes");

const workspace = path.resolve(__dirname, "..");
const logsDir = path.resolve(workspace, "..", "logs");
const envPath = path.join(workspace, ".env");
const historyPath = path.join(workspace, "electron", "data", "job-history.json");
const secretPath = path.join(workspace, "electron", "data", ".secrets.enc");

let mainWindow = null;
const runningJobs = new Map();
const queue = [];
let queueBusy = false;
const scheduled = [];

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function nowIso() {
  return new Date().toISOString();
}

function readJson(file, fallback) {
  try {
    if (!fs.existsSync(file)) return fallback;
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (_) {
    return fallback;
  }
}

function writeJson(file, value) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, JSON.stringify(value, null, 2), "utf-8");
}

function emit(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function loadEnv() {
  const out = {};
  if (!fs.existsSync(envPath)) return { env: out, raw: [] };
  const raw = fs.readFileSync(envPath, "utf-8").split(/\r?\n/);
  for (let i = 0; i < raw.length; i += 1) {
    const line = raw[i];
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    if (!line.includes("=")) {
      return {
        error: {
          error_code: ErrorCodes.E_ENV_PARSE_INVALID,
          scope: "env.load",
          next_action: `Sua dong ${i + 1} theo KEY=VALUE`,
          detail: line
        }
      };
    }
    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    const val = line.slice(idx + 1).trim();
    out[key] = val;
  }
  return { env: out, raw };
}

function saveEnv(payload) {
  const lines = Object.entries(payload).map(([k, v]) => `${k}=${v ?? ""}`);
  fs.writeFileSync(envPath, `${lines.join("\n")}\n`, "utf-8");
}

function maskSensitive(obj) {
  const out = { ...obj };
  Object.keys(out).forEach((k) => {
    if (k.includes("PASSWORD") || k.includes("API_KEY")) {
      out[k] = out[k] ? "***" : "";
    }
  });
  return out;
}

function buildCommand(type, args = {}) {
  if (type === "daily") {
    return [
      "python",
      [
        "daily_scanner.py",
        "--universe",
        args.universe || "small",
        "--top-coins",
        String(args.topCoins || 200),
        "--min-weighted-score",
        String(args.minWeightedScore || 35)
      ]
    ];
  }
  if (type === "backtest") {
    return [
      "python",
      [
        "backtester.py",
        "--universe",
        args.universe || "small",
        "--weeks",
        String(args.weeks || 24),
        "--top-coins",
        String(args.topCoins || 50)
      ]
    ];
  }
  return ["python", ["monitor.py"]];
}

function appendHistory(record) {
  const arr = readJson(historyPath, []);
  arr.push(record);
  writeJson(historyPath, arr.slice(-500));
}

function classifyError(line) {
  const text = (line || "").toLowerCase();
  if (text.includes("403") && text.includes("coinpaprika")) return ErrorCodes.E_API_403_COINPAPRIKA;
  if (text.includes("rate") && text.includes("limit")) return ErrorCodes.E_API_RATE_LIMIT;
  if (text.includes("smtp") && text.includes("auth")) return ErrorCodes.E_SMTP_AUTH_FAIL;
  if (text.includes("aurora") && text.includes("connect")) return ErrorCodes.E_DB_CONNECT_FAIL;
  return ErrorCodes.E_SCRIPT_EXIT_NONZERO;
}

function runJob(type, args = {}, timeoutMs = 60 * 60 * 1000) {
  return new Promise((resolve) => {
    if (runningJobs.has(type)) {
      resolve({
        ok: false,
        error: {
          error_code: ErrorCodes.E_JOB_ALREADY_RUNNING,
          scope: "job.run",
          next_action: "Dung job hien tai truoc khi chay lai."
        }
      });
      return;
    }

    const [cmd, cmdArgs] = buildCommand(type, args);
    const startedAt = nowIso();
    const commandText = `${cmd} ${cmdArgs.join(" ")}`;
    const child = spawn(cmd, cmdArgs, { cwd: workspace, shell: true });
    const record = {
      job_id: crypto.randomUUID(),
      job_type: type,
      command: commandText,
      started_at: startedAt,
      status: "running",
      exit_code: null,
      error_code: null
    };

    runningJobs.set(type, child);
    emit("job-log", { type, line: `[RUN] ${commandText}` });

    let timeoutId = setTimeout(() => {
      if (!child.killed) child.kill();
      record.status = "failed";
      record.error_code = ErrorCodes.E_RUNTIME_TIMEOUT;
    }, timeoutMs);

    child.stdout.on("data", (buf) => {
      const line = String(buf);
      emit("job-log", { type, line });
    });
    child.stderr.on("data", (buf) => {
      const line = String(buf);
      emit("job-log", { type, line });
    });

    child.on("close", (code) => {
      clearTimeout(timeoutId);
      runningJobs.delete(type);
      record.finished_at = nowIso();
      record.exit_code = code;
      if (record.error_code) {
        record.status = "failed";
      } else if (code === 0) {
        record.status = "success";
      } else {
        record.status = "failed";
        record.error_code = ErrorCodes.E_SCRIPT_EXIT_NONZERO;
      }
      appendHistory(record);
      emit("job-done", { type, record });
      resolve({ ok: record.status === "success", record });
    });
  });
}

async function enqueue(task) {
  queue.push(task);
  processQueue();
}

async function processQueue() {
  if (queueBusy) return;
  queueBusy = true;
  while (queue.length > 0) {
    const item = queue.shift();
    let success = false;
    for (let i = 0; i <= item.maxRetries; i += 1) {
      const res = await runJob(item.type, item.args, item.timeoutMs);
      success = !!res.ok;
      if (success) break;
      await new Promise((r) => setTimeout(r, item.backoffMs * (i + 1)));
    }
  }
  queueBusy = false;
}

function scheduleDaily(jobId, hour, minute, type, args) {
  scheduled.push({ jobId, hour, minute, type, args, enabled: true, lastRun: "" });
}

setInterval(() => {
  const now = new Date();
  const key = `${now.getUTCFullYear()}-${now.getUTCMonth()}-${now.getUTCDate()}-${now.getUTCHours()}-${now.getUTCMinutes()}`;
  scheduled.forEach((s) => {
    if (!s.enabled) return;
    if (s.hour === now.getUTCHours() && s.minute === now.getUTCMinutes() && s.lastRun !== key) {
      s.lastRun = key;
      enqueue({ type: s.type, args: s.args || {}, maxRetries: 2, backoffMs: 3000, timeoutMs: 60 * 60 * 1000 });
      emit("job-log", { type: s.type, line: `[SCHEDULE] trigger ${s.jobId}` });
    }
  });
}, 10000);

function listArtifacts() {
  if (!fs.existsSync(logsDir)) return [];
  const allow = new Set([".log", ".csv", ".json", ".png", ".xlsx"]);
  const files = fs
    .readdirSync(logsDir)
    .map((name) => path.join(logsDir, name))
    .filter((p) => allow.has(path.extname(p).toLowerCase()))
    .map((p) => ({ path: p, mtime: fs.statSync(p).mtimeMs }));
  return files.sort((a, b) => b.mtime - a.mtime).map((f) => f.path);
}

function previewArtifact(filePath) {
  if (!fs.existsSync(filePath)) {
    return {
      error: {
        error_code: ErrorCodes.E_ARTIFACT_NOT_FOUND,
        scope: "artifact.preview",
        next_action: "Chay job de tao artifact."
      }
    };
  }
  const ext = path.extname(filePath).toLowerCase();
  if ([".log", ".csv", ".json"].includes(ext)) {
    const txt = fs.readFileSync(filePath, "utf-8");
    return { content: txt.slice(0, 20000) };
  }
  return { content: `Khong ho tro preview truc tiep: ${path.basename(filePath)}` };
}

function openArtifact(filePath) {
  if (!fs.existsSync(filePath)) {
    return {
      error: {
        error_code: ErrorCodes.E_ARTIFACT_NOT_FOUND,
        scope: "artifact.open",
        next_action: "Kiem tra duong dan file."
      }
    };
  }
  shell.openPath(filePath);
  return { ok: true };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

function runPythonSnippet(script) {
  return new Promise((resolve) => {
    const child = spawn("python", ["-c", script], { cwd: workspace, shell: true });
    let output = "";
    let err = "";
    child.stdout.on("data", (d) => (output += String(d)));
    child.stderr.on("data", (d) => (err += String(d)));
    child.on("close", (code) => resolve({ code, output, err }));
  });
}

async function healthApi() {
  try {
    const res = await fetch("https://api.coinpaprika.com/v1/global");
    if (res.status === 403) {
      return {
        ok: false,
        error: {
          error_code: ErrorCodes.E_API_403_COINPAPRIKA,
          scope: "health.api",
          next_action: "Kiem tra mang/VPN hoac fallback CoinGecko."
        }
      };
    }
    return { ok: true, status: `http_${res.status}` };
  } catch (e) {
    return {
      ok: false,
      error: {
        error_code: ErrorCodes.E_API_403_COINPAPRIKA,
        scope: "health.api",
        next_action: "Kiem tra internet.",
        detail: String(e)
      }
    };
  }
}

async function healthDb() {
  const script = `
import os, psycopg2
conn = psycopg2.connect(host=os.getenv("AURORA_HOST"), database=os.getenv("AURORA_DB"), user=os.getenv("AURORA_USER"), password=os.getenv("AURORA_PASSWORD"), port=int(os.getenv("AURORA_PORT","5432")))
conn.close()
print("ok")
`;
  const r = await runPythonSnippet(script);
  if (r.code === 0) return { ok: true, status: "ok" };
  return {
    ok: false,
    error: {
      error_code: ErrorCodes.E_DB_CONNECT_FAIL,
      scope: "health.db",
      next_action: "Kiem tra AURORA_* trong .env.",
      detail: r.err.slice(0, 1000)
    }
  };
}

async function healthSmtp() {
  const script = `
import os, smtplib
s=smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT","587")), timeout=15)
s.starttls()
s.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
s.quit()
print("ok")
`;
  const r = await runPythonSnippet(script);
  if (r.code === 0) return { ok: true, status: "ok" };
  return {
    ok: false,
    error: {
      error_code: ErrorCodes.E_SMTP_AUTH_FAIL,
      scope: "health.smtp",
      next_action: "Kiem tra SMTP_SERVER/USERNAME/PASSWORD.",
      detail: r.err.slice(0, 1000)
    }
  };
}

ipcMain.handle("app:get-dashboard", async () => {
  const history = readJson(historyPath, []);
  return {
    workspace,
    logsDir,
    interpreter: process.env.PYTHON || "python",
    inVenv: (process.env.VIRTUAL_ENV || "").length > 0,
    queueSize: queue.length,
    running: Array.from(runningJobs.keys()),
    historyCount: history.length,
    lastJob: history.length > 0 ? history[history.length - 1] : null
  };
});

ipcMain.handle("env:load", async () => {
  return loadEnv();
});

ipcMain.handle("env:save", async (_e, payload) => {
  saveEnv(payload);
  return { ok: true };
});

ipcMain.handle("secret:save", async (_e, payload) => {
  ensureDir(path.dirname(secretPath));
  const rows = [];
  Object.entries(payload).forEach(([k, v]) => {
    const hash = crypto.createHash("sha256").update(k).digest();
    const plain = Buffer.from(String(v || ""), "utf-8");
    const out = Buffer.alloc(plain.length);
    for (let i = 0; i < plain.length; i += 1) out[i] = plain[i] ^ hash[i % hash.length];
    rows.push(`${k}=${out.toString("base64")}`);
  });
  fs.writeFileSync(secretPath, `${rows.join("\n")}\n`, "utf-8");
  return { ok: true };
});

ipcMain.handle("job:run", async (_e, payload) => {
  const type = payload?.type || "monitor";
  const args = payload?.args || {};
  const maxRetries = Number(payload?.maxRetries ?? 2);
  const backoffMs = Number(payload?.backoffMs ?? 3000);
  const timeoutMs = Number(payload?.timeoutMs ?? 60 * 60 * 1000);
  await enqueue({ type, args, maxRetries, backoffMs, timeoutMs });
  return { ok: true };
});

ipcMain.handle("job:stop", async (_e, type) => {
  const proc = runningJobs.get(type);
  if (proc) proc.kill();
  return { ok: true };
});

ipcMain.handle("job:history", async () => {
  return readJson(historyPath, []);
});

ipcMain.handle("artifact:list", async () => listArtifacts());
ipcMain.handle("artifact:preview", async (_e, p) => previewArtifact(p));
ipcMain.handle("artifact:open", async (_e, p) => openArtifact(p));

ipcMain.handle("health:api", healthApi);
ipcMain.handle("health:db", healthDb);
ipcMain.handle("health:smtp", healthSmtp);

ipcMain.handle("scheduler:register", async (_e, payload) => {
  scheduleDaily(payload.jobId, payload.hour, payload.minute, payload.type, payload.args || {});
  return { ok: true };
});

ipcMain.handle("scheduler:list", async () => scheduled);

ipcMain.handle("error:classify", async (_e, line) => ({ error_code: classifyError(line || "") }));

app.whenReady().then(() => {
  ensureDir(path.dirname(historyPath));
  ensureDir(path.dirname(secretPath));
  ensureDir(logsDir);

  scheduleDaily("daily_auto_utc", 7, 0, "daily", { universe: "small", topCoins: 200, minWeightedScore: 35 });
  scheduleDaily("monitor_auto_utc", 8, 0, "monitor", {});

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

