const settingsKeys = [
  "COIN_PAPRIKA_API_KEY",
  "OPENAI_API_KEY",
  "LLM_PROVIDER",
  "LLM_MODEL",
  "LLM_BASE_URL",
  "EMAIL_FROM",
  "EMAIL_TO",
  "SMTP_SERVER",
  "SMTP_USERNAME",
  "SMTP_PASSWORD",
  "AURORA_HOST",
  "AURORA_PORT",
  "AURORA_DB",
  "AURORA_USER",
  "AURORA_PASSWORD"
];

const $ = (id) => document.getElementById(id);

const state = {
  selectedArtifact: null,
  artifacts: []
};

function setActiveTab(tab) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === tab));
}

function appendLog(el, line) {
  el.textContent += `${line}`;
  if (!line.endsWith("\n")) el.textContent += "\n";
  el.scrollTop = el.scrollHeight;
}

function formatObj(obj) {
  return JSON.stringify(obj, null, 2);
}

function readSettingsForm() {
  const payload = {};
  settingsKeys.forEach((k) => {
    payload[k] = $(`env_${k}`).value || "";
  });
  return payload;
}

function writeSettingsForm(env) {
  settingsKeys.forEach((k) => {
    $(`env_${k}`).value = env?.[k] || "";
  });
}

function buildSettingsGrid() {
  const grid = $("settingsGrid");
  grid.innerHTML = "";
  settingsKeys.forEach((key) => {
    const label = document.createElement("label");
    label.textContent = key;
    const input = document.createElement("input");
    input.id = `env_${key}`;
    if (key.includes("PASSWORD") || key.includes("API_KEY")) input.type = "password";
    grid.appendChild(label);
    grid.appendChild(input);
  });
}

async function refreshDashboard() {
  const data = await window.cryptoPanda.getDashboard();
  $("dashboardContent").textContent = formatObj(data);
  $("metricHistoryCount").textContent = String(data.historyCount || 0);
  $("metricQueueSize").textContent = String(data.queueSize || 0);
  $("metricRunningCount").textContent = String((data.running || []).length);
  $("metricEnvironment").textContent = data.inVenv ? "Venv" : "Global";

  $("chipInterpreter").textContent = `Interpreter: ${data.interpreter || "--"}`;
  $("chipQueue").textContent = `Queue: ${data.queueSize || 0}`;
  $("chipRunning").textContent = `Running: ${(data.running || []).join(", ") || "none"}`;
  $("chipLastJob").textContent = `Last Job: ${data.lastJob ? data.lastJob.job_type : "--"}`;
}

async function loadEnv() {
  const res = await window.cryptoPanda.loadEnv();
  if (res.error) {
    $("settingsMsg").textContent = formatObj(res.error);
    return;
  }
  writeSettingsForm(res.env || {});
  $("settingsMsg").textContent = "Da tai .env";
}

async function saveEnv() {
  const payload = readSettingsForm();
  await window.cryptoPanda.saveEnv(payload);
  $("settingsMsg").textContent = "Da luu .env";
}

async function saveSecret() {
  const payload = readSettingsForm();
  const secretPayload = {};
  Object.keys(payload).forEach((k) => {
    if (k.includes("PASSWORD") || k.includes("API_KEY")) secretPayload[k] = payload[k];
  });
  await window.cryptoPanda.saveSecret(secretPayload);
  $("settingsMsg").textContent = "Da luu secret cache";
}

async function runDaily() {
  await window.cryptoPanda.runJob({
    type: "daily",
    args: {
      universe: $("dailyUniverse").value,
      topCoins: Number($("dailyTop").value || 200),
      minWeightedScore: Number($("dailyMinScore").value || 35)
    },
    maxRetries: 2,
    backoffMs: 3000
  });
}

async function runBacktest() {
  await window.cryptoPanda.runJob({
    type: "backtest",
    args: {
      universe: $("btUniverse").value,
      weeks: Number($("btWeeks").value || 24),
      topCoins: Number($("btTop").value || 50)
    },
    maxRetries: 2,
    backoffMs: 3000
  });
}

async function runMonitor() {
  await window.cryptoPanda.runJob({ type: "monitor", args: {}, maxRetries: 2, backoffMs: 3000 });
}

async function refreshArtifacts() {
  state.artifacts = await window.cryptoPanda.listArtifacts();
  const ul = $("artifactList");
  ul.innerHTML = "";
  state.artifacts.forEach((p) => {
    const li = document.createElement("li");
    li.textContent = p;
    li.onclick = async () => {
      document.querySelectorAll("#artifactList li").forEach((x) => x.classList.remove("active"));
      li.classList.add("active");
      state.selectedArtifact = p;
      const preview = await window.cryptoPanda.previewArtifact(p);
      $("artifactPreview").textContent = preview.error ? formatObj(preview.error) : (preview.content || "");
    };
    ul.appendChild(li);
  });
}

async function openArtifact() {
  if (!state.selectedArtifact) return;
  const res = await window.cryptoPanda.openArtifact(state.selectedArtifact);
  if (res.error) {
    $("artifactPreview").textContent = formatObj(res.error);
  }
}

async function refreshHistory() {
  const history = await window.cryptoPanda.getHistory();
  $("historyContent").textContent = formatObj(history.slice(-200).reverse());
}

async function doHealth(kind) {
  let res;
  if (kind === "api") res = await window.cryptoPanda.healthApi();
  if (kind === "db") res = await window.cryptoPanda.healthDb();
  if (kind === "smtp") res = await window.cryptoPanda.healthSmtp();
  appendLog($("healthLog"), `[${kind.toUpperCase()}] ${formatObj(res)}`);
}

function bindEvents() {
  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.onclick = () => setActiveTab(btn.dataset.tab);
  });
  $("refreshDashboard").onclick = refreshDashboard;

  $("runDaily").onclick = runDaily;
  $("stopDaily").onclick = () => window.cryptoPanda.stopJob("daily");
  $("runBacktest").onclick = runBacktest;
  $("stopBacktest").onclick = () => window.cryptoPanda.stopJob("backtest");
  $("runMonitor").onclick = runMonitor;
  $("stopMonitor").onclick = () => window.cryptoPanda.stopJob("monitor");

  $("reloadEnv").onclick = loadEnv;
  $("saveEnv").onclick = saveEnv;
  $("saveSecret").onclick = saveSecret;

  $("refreshArtifacts").onclick = refreshArtifacts;
  $("openArtifact").onclick = openArtifact;

  $("healthApi").onclick = () => doHealth("api");
  $("healthDb").onclick = () => doHealth("db");
  $("healthSmtp").onclick = () => doHealth("smtp");

  $("refreshHistory").onclick = refreshHistory;

  window.cryptoPanda.onJobLog((payload) => {
    const t = payload.type;
    if (t === "daily") appendLog($("dailyLog"), payload.line);
    if (t === "backtest") appendLog($("backtestLog"), payload.line);
    if (t === "monitor") appendLog($("monitorLog"), payload.line);
  });

  window.cryptoPanda.onJobDone(async (payload) => {
    const line = `[DONE] ${payload.type} => ${payload.record.status} exit=${payload.record.exit_code} err=${payload.record.error_code || ""}`;
    if (payload.type === "daily") appendLog($("dailyLog"), line);
    if (payload.type === "backtest") appendLog($("backtestLog"), line);
    if (payload.type === "monitor") appendLog($("monitorLog"), line);
    await refreshDashboard();
    await refreshHistory();
    await refreshArtifacts();
  });
}

async function init() {
  buildSettingsGrid();
  bindEvents();
  await loadEnv();
  await refreshDashboard();
  await refreshArtifacts();
  await refreshHistory();
}

init();

