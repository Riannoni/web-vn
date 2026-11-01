"use strict";
const $ = id => document.getElementById(id);
let models = [], jobs = [], currentView = "", updating = false, toastTimer = null;
let llmMessages = [], llmBusy = false;
const labels = {
  queued:"В очереди",working:"Генерация",done:"Готово",
  error:"Ошибка",interrupted:"Прервано",canceled:"Отменено"
};

async function api(path, body = undefined) {
  const opts = {credentials:"same-origin", headers:{"Accept":"application/json"}};
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const response = await fetch(path, opts);
  let data = {};
  try { data = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) throw new Error(data.error || "Ошибка HTTP " + response.status);
  return data;
}

function notify(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4700);
}
function text(tag, content, cls = "") {
  const el = document.createElement(tag);
  el.textContent = content || "";
  if (cls) el.className = cls;
  return el;
}
function addButton(parent, label, action, id, extraClass = "") {
  const el = text("button", label, extraClass);
  el.type = "button";
  el.dataset.action = action;
  el.dataset.id = id;
  parent.append(el);
  return el;
}
function getModel(id) {
  return models.find(m => m.id === id) || {name:id || "Модель",family:""};
}
function randomSeed() {
  return Math.floor(Math.random() * 2147483646) + 1;
}
function promptPayload() {
  const dims = $("size").value.split("x").map(Number);
  const v = $("seed").value.trim();
  if (v && (!Number.isSafeInteger(Number(v)) || Number(v) < 0))
    throw new Error("Seed должен быть целым положительным числом.");
  const prompt = $("prompt").value.trim();
  if (prompt.length < 2) throw new Error("Введите описание сцены.");
  return {prompt, negative:$("negative").value.trim(),
          width:dims[0], height:dims[1], seed:v ? Number(v) : null};
}
function updateModelInfo() {
  const m = getModel($("model").value);
  $("model-note").textContent = m.family + " · " +
    (m.negative ? "поддерживает негативный промпт" : "не использует негативный промпт");
  $("negative-note").textContent = m.negative ?
    "Можно указать нежелательные объекты, артефакты и композиции." :
    "У этой быстрой архитектуры отрицательное описание не используется. Полезные ограничения лучше вписать прямо в основной промпт.";
}
function renderModels() {
  const selected = $("model").value || "pony";
  const sel = $("model");
  sel.replaceChildren();
  $("compare-options").replaceChildren();
  const filter = $("filter");
  filter.replaceChildren(new Option("Все модели", "all"));
  for (const m of models) {
    const option = new Option(m.name + (m.ready ? "" : " · недоступна"), m.id);
    option.disabled = !m.ready;
    sel.add(option);
    filter.add(new Option(m.name, m.id));
    const label = document.createElement("label");
    if (!m.ready) label.classList.add("disabled");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = m.id;
    cb.disabled = !m.ready;
    cb.checked = m.ready && ["pony","anima","wai"].includes(m.id);
    label.append(cb, text("span", m.name));
    $("compare-options").append(label);
  }
  sel.value = models.some(m => m.id === selected && m.ready) ? selected :
              models.some(m => m.id === "pony" && m.ready) ? "pony" :
              (models.find(m => m.ready) || {}).id || "";
  updateModelInfo();
}
function formatDate(ts) {
  return new Date(ts * 1000).toLocaleString("ru-RU",{
    day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit"
  });
}
function statusClass(s) {
  if (s === "done") return "done";
  if (s === "error" || s === "interrupted") return "error";
  if (s === "working") return "working";
  return "";
}
function createCard(j) {
  const article = document.createElement("article");
  article.className = "result-card";
  article.setAttribute("role","listitem");

  const media = document.createElement("div");
  media.className = "card-media";
  if (j.status === "done") {
    const image = document.createElement("img");
    image.src = "/api/image/" + j.id;
    image.alt = "Сгенерировано: " + getModel(j.model).name;
    image.loading = "lazy";
    image.addEventListener("click", () => openViewer(j));
    media.append(image);
  } else {
    media.classList.add("loading");
    const wrap = document.createElement("div");
    wrap.className = "progress-note";
    if (j.status === "working" || j.status === "queued")
      wrap.append(text("span","","spinner"));
    else wrap.append(text("span",j.status === "error" ? "⚠" : "◌", "empty-symbol"));
    wrap.append(text("span",j.stage || labels[j.status] || "Обработка"));
    media.append(wrap);
  }
  const body = document.createElement("div");
  body.className = "card-body";
  const titleRow = document.createElement("div");
  titleRow.className = "card-top";
  titleRow.append(text("strong",j.model_name || getModel(j.model).name,"card-title"),
                  text("span",labels[j.status] || j.status,"status "+statusClass(j.status)));
  body.append(titleRow);
  const meta = document.createElement("div");
  meta.className = "card-meta";
  const parts = [String(j.width) + "×" + String(j.height),
                 "Seed " + String(j.seed),
                 j.duration ? String(j.duration) + " с" : formatDate(j.created)];
  for (const p of parts) meta.append(text("span",p));
  body.append(meta);
  body.append(text("div",j.prompt,"card-excerpt"));
  if (j.error) body.append(text("div",j.error,"card-error"));

  const actions = document.createElement("div");
  actions.className = "card-actions";
  if (j.status === "done") {
    const download = text("a","Сохранить PNG");
    download.href = "/api/download/" + j.id;
    download.download = "";
    actions.append(download);
  }
  const repeat = addButton(actions,"Повторить","reuse",j.id);
  if (!models.some(m => m.id === j.model && m.ready)) {
    repeat.disabled = true;
    repeat.title = "Модель удалена; промпт можно скопировать.";
  }
  addButton(actions,"Копировать текст","copy",j.id);
  if (j.status === "queued") addButton(actions,"Отменить","cancel",j.id);
  if (!["queued","working"].includes(j.status))
    addButton(actions,"Удалить","delete",j.id);
  body.append(actions);
  article.append(media,body);
  return article;
}
function renderJobs() {
  const filtered = jobs.filter(j => $("filter").value === "all" ||
                                  $("filter").value === j.model);
  $("empty").hidden = filtered.length > 0;
  const active = jobs.filter(j => j.status === "working" || j.status === "queued");
  const summary = $("queue-summary");
  summary.hidden = active.length === 0;
  if (active.length) {
    const generating = active.filter(j => j.status === "working").length;
    summary.textContent = "В обработке: " + active.length +
      " · генерируется: " + generating +
      " · ожидают: " + (active.length-generating) +
      ". Задачи выполняются последовательно.";
  }
  $("gallery").replaceChildren();
  let group = null;
  for (const j of filtered) {
    if (j.group && j.group !== group) {
      group = j.group;
      const count = jobs.filter(x => x.group === group).length;
      const header = text("div","▦ Сравнение · " + count + " моделей · Seed " + j.seed,
                          "group-label");
      $("gallery").append(header);
    } else if (!j.group) group = null;
    $("gallery").append(createCard(j));
  }
}
async function refreshJobs(force = false) {
  if (updating) return;
  updating = true;
  try {
    const result = await api("/api/jobs");
    const newJobs = result.jobs || [];
    const signature = newJobs.map(j => [j.id,j.status,j.updated,j.error].join(":")).join("|");
    if (force || signature !== currentView) {
      jobs = newJobs;
      currentView = signature;
      renderJobs();
    }
  } catch (err) {
    console.warn("Cannot poll jobs:",err.message);
  } finally { updating = false; }
}
async function refreshHealth() {
  const el = $("health");
  try {
    const status = await api("/api/health");
    el.classList.toggle("online",!!status.online);
    el.classList.toggle("offline",!status.online);
    el.lastChild.textContent = status.online ?
      "ComfyUI онлайн" + (status.running ? " · GPU занят" : " · GPU свободен") :
      "ComfyUI недоступен";
  } catch (_) {
    el.classList.add("offline");
    el.lastChild.textContent = "Нет соединения";
  }
}
function openViewer(j) {
  $("viewer-download").hidden = false;
  $("viewer").hidden = false;
  $("viewer-image").src = "/api/image/" + j.id;
  $("viewer-name").textContent = j.model_name || getModel(j.model).name;
  $("viewer-meta").textContent = j.width + "×" + j.height +
    " · Seed " + j.seed + " · " + (j.duration || "—") + " с";
  $("viewer-download").href = "/api/download/" + j.id;
}
async function loadMiraPack() {
  const panel = $("mira-pack");
  try {
    const data = await api("/api/mira-pack");
    const ids = (data.assets || []).map(a => a.id);
    const choices = $("mira-pack-choices");
    choices.replaceChildren();
    for (const id of ids) {
      const button = text("button", id, "subtle");
      button.type = "button";
      button.addEventListener("click", () => {
        $("viewer").hidden = false;
        $("viewer-image").src = "/api/mira-pack/" + encodeURIComponent(id);
        $("viewer-name").textContent = id;
        $("viewer-meta").textContent = "PROVISIONAL / NOT REVIEWED";
        $("viewer-download").hidden = true;
      });
      choices.append(button);
    }
    panel.hidden = ids.length === 0;
  } catch (_) { panel.hidden = true; }
}
function closeViewer() {
  $("viewer").hidden = true;
  $("viewer-image").removeAttribute("src");
}
async function copyText(value) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try { await navigator.clipboard.writeText(value);return true; } catch (_) { }
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const okay = document.execCommand("copy");
  area.remove();
  return okay;
}
async function actionClicked(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const j = jobs.find(row => row.id === button.dataset.id);
  if (!j) return;
  const type = button.dataset.action;
  if (type === "reuse") {
    $("model").value = j.model;
    $("prompt").value = j.prompt;
    $("negative").value = j.negative;
    $("size").value = j.width + "x" + j.height;
    $("seed").value = j.seed;
    $("prompt-count").textContent = $("prompt").value.length + " / 3000";
    updateModelInfo();
    window.scrollTo({top:0,behavior:"smooth"});
    notify("Параметры загружены для повторной генерации.");
  } else if (type === "copy") {
    notify(await copyText(j.prompt) ? "Промпт скопирован." :
                                          "Копирование недоступно в этом браузере.");
  } else if (type === "cancel") {
    const data = await api("/api/cancel",{id:j.id});
    notify(data.ok ? "Ожидающая задача отменена." : "Задача уже выполняется.");
    await refreshJobs(true);
  } else if (type === "delete") {
    if (!confirm("Удалить этот результат и его локальную копию?")) return;
    const data = await api("/api/delete",{id:j.id});
    notify(data.ok ? "Результат удалён." : "Нельзя удалить выполняемую задачу.");
    await refreshJobs(true);
  }
}
async function submit(isComparison) {
  let modelIds = isComparison ?
    [...$("compare-options").querySelectorAll("input:checked")].map(x => x.value) :
    [$("model").value];
  if (!modelIds.length) throw new Error("Выбери хотя бы одну модель для сравнения.");
  const payload = promptPayload();
  payload.models = modelIds;
  $("generate").disabled = true;
  $("compare").disabled = true;
  try {
    const answer = await api("/api/generate",payload);
    $("seed").value = answer.seed;
    notify(modelIds.length > 1 ?
      "Запущено сравнение " + modelIds.length + " моделей." :
      "Задача добавлена в очередь ComfyUI.");
    await refreshJobs(true);
  } finally {
    $("generate").disabled = false;
    $("compare").disabled = false;
  }
}
function renderLLMHistory() {
  const area = $("llm-history");
  area.replaceChildren();
  if (!llmMessages.length) {
    area.append(text("div","Контекст пуст. Отправь первое сообщение.","llm-empty"));
    return;
  }
  for (const msg of llmMessages) {
    const entry = document.createElement("div");
    entry.className = "llm-bubble " + (msg.role === "user" ? "llm-user" : "llm-assistant");
    entry.append(text("small",msg.role === "user" ? "Ты" : "Модель"));
    entry.append(text("div",msg.content));
    area.append(entry);
  }
  area.scrollTop = area.scrollHeight;
}
async function loadLLMOptions() {
  try {
    const list = await api("/api/llm-models");
    const select = $("llm-model");
    select.replaceChildren();
    for (const m of list.models) {
      const backendLabel = m.backend === "koboldcpp-rocm" ? " · GPU/ROCm" :
        m.backend === "koboldcpp-cpu" ? " · CPU" : "";
      const option = new Option(m.name + backendLabel + (m.ready ? "" : " · недоступна"),m.id);
      option.disabled = !m.ready;
      select.add(option);
    }
    const q = [...select.options].find(x => !x.disabled);
    if (q) select.value = q.value;
    $("llm-send").disabled = !q;
  } catch(e) { $("llm-status").textContent = e.message; }
  renderLLMHistory();
}
async function sendLLM() {
  if (llmBusy) return;
  const prompt = $("llm-prompt").value.trim();
  if (!prompt) {notify("Введите текст для модели.");return;}
  const chosen = $("llm-model").value;
  const next = [...llmMessages,{role:"user",content:prompt}].slice(-12);
  llmBusy=true;
  $("llm-send").disabled=true;
  $("llm-status").textContent="Запуск локальной модели и генерация ответа…";
  try {
    const output = await api("/api/llm-chat",{model:chosen,messages:next,max_tokens:280,temperature:0.8});
    llmMessages=[...next,{role:"assistant",content:output.text}].slice(-12);
    $("llm-prompt").value="";
    renderLLMHistory();
    $("llm-status").textContent="Готово за "+output.total_seconds+" с · ответ "+
      (output.output_tokens||"—")+" токенов · загрузка "+output.load_seconds+" с"+
      (output.backend === "koboldcpp-rocm" ? " · GPU/ROCm" :
       output.backend === "koboldcpp-cpu" ? " · CPU (резерв)" : "");
  } catch(e) {
    $("llm-status").textContent="Ошибка: "+e.message;
  } finally {llmBusy=false;$("llm-send").disabled=false;}
}
async function enter() {
  $("auth").hidden = true;
  $("shell").hidden = false;
  const results = await api("/api/models");
  models = results.models || [];
  renderModels();
  await Promise.all([refreshJobs(true),refreshHealth(),loadLLMOptions(),loadMiraPack()]);
  setInterval(() => {
    if (!$("shell").hidden) refreshJobs();
  },2300);
  setInterval(() => {
    if (!$("shell").hidden) refreshHealth();
  },8000);
}
function showLogin() {
  $("auth").hidden = false;
  $("shell").hidden = true;
  $("password").value = "";
}
document.addEventListener("DOMContentLoaded",async () => {
  $("login-form").addEventListener("submit",async event => {
    event.preventDefault();
    const btn = $("login-button");
    btn.disabled = true;
    try {
      await api("/api/login",{username:"lab",password:$("password").value});
      $("login-error").textContent = "";
      await enter();
    } catch (err) {
      $("login-error").textContent = err.message;
    } finally { btn.disabled = false; }
  });
  $("llm-send").addEventListener("click",()=>sendLLM().catch(e=>notify(e.message)));
  $("llm-clear").addEventListener("click",()=>{
    llmMessages=[];
    renderLLMHistory();
    $("llm-status").textContent="История контекста очищена";
  });
  $("llm-model").addEventListener("change",()=>{
    llmMessages=[];renderLLMHistory();
    $("llm-status").textContent="Модель изменена; контекст беседы сброшен.";
  });
  $("logout").addEventListener("click",async () => {
    try { await api("/api/logout",{}); } catch (_) { }
    closeViewer();
    showLogin();
  });
  $("model").addEventListener("change",updateModelInfo);
  $("prompt").addEventListener("input",() => {
    $("prompt-count").textContent = $("prompt").value.length + " / 3000";
  });
  $("generate-form").addEventListener("submit",async event => {
    event.preventDefault();
    try { await submit(false); } catch(err) { notify(err.message); }
  });
  $("compare").addEventListener("click",async () => {
    try { await submit(true); } catch(err) { notify(err.message); }
  });
  $("random-seed").addEventListener("click",() => { $("seed").value = randomSeed(); });
  $("refresh").addEventListener("click",() => refreshJobs(true));
  $("filter").addEventListener("change",renderJobs);
  $("gallery").addEventListener("click",event => {
    actionClicked(event).catch(err => notify(err.message));
  });
  $("close-viewer").addEventListener("click",closeViewer);
  $("viewer").addEventListener("click",event => {
    if (event.target === $("viewer")) closeViewer();
  });
  document.addEventListener("keydown",event => {
    if (event.key === "Escape") closeViewer();
  });
  $("prompt-count").textContent = $("prompt").value.length + " / 3000";
  try {
    const session = await api("/api/session");
    if (session.authenticated) await enter();
    else showLogin();
  } catch (err) {
    showLogin();
    $("login-error").textContent = "Не удалось подключиться: " + err.message;
  }
});
