const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cryptoPanda", {
  getDashboard: () => ipcRenderer.invoke("app:get-dashboard"),
  loadEnv: () => ipcRenderer.invoke("env:load"),
  saveEnv: (payload) => ipcRenderer.invoke("env:save", payload),
  saveSecret: (payload) => ipcRenderer.invoke("secret:save", payload),
  runJob: (payload) => ipcRenderer.invoke("job:run", payload),
  stopJob: (type) => ipcRenderer.invoke("job:stop", type),
  getHistory: () => ipcRenderer.invoke("job:history"),
  listArtifacts: () => ipcRenderer.invoke("artifact:list"),
  previewArtifact: (path) => ipcRenderer.invoke("artifact:preview", path),
  openArtifact: (path) => ipcRenderer.invoke("artifact:open", path),
  healthApi: () => ipcRenderer.invoke("health:api"),
  healthDb: () => ipcRenderer.invoke("health:db"),
  healthSmtp: () => ipcRenderer.invoke("health:smtp"),
  registerSchedule: (payload) => ipcRenderer.invoke("scheduler:register", payload),
  listSchedule: () => ipcRenderer.invoke("scheduler:list"),
  classifyError: (line) => ipcRenderer.invoke("error:classify", line),
  onJobLog: (handler) => ipcRenderer.on("job-log", (_evt, payload) => handler(payload)),
  onJobDone: (handler) => ipcRenderer.on("job-done", (_evt, payload) => handler(payload))
});

