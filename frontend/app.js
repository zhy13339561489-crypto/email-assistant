const state = {
  days: "30",
  category: "all",
  query: "",
  emails: [],
  categories: [],
};

const els = {
  daysSelect: document.querySelector("#daysSelect"),
  searchInput: document.querySelector("#searchInput"),
  refreshBtn: document.querySelector("#refreshBtn"),
  totalCount: document.querySelector("#totalCount"),
  actionCount: document.querySelector("#actionCount"),
  confidenceAvg: document.querySelector("#confidenceAvg"),
  attachmentCount: document.querySelector("#attachmentCount"),
  categoryTabs: document.querySelector("#categoryTabs"),
  categoryChart: document.querySelector("#categoryChart"),
  actionList: document.querySelector("#actionList"),
  emailTable: document.querySelector("#emailTable"),
  resultMeta: document.querySelector("#resultMeta"),
  statusPill: document.querySelector("#statusPill"),
  detailPanel: document.querySelector("#detailPanel"),
  detailCategory: document.querySelector("#detailCategory"),
  detailSubject: document.querySelector("#detailSubject"),
  detailSender: document.querySelector("#detailSender"),
  detailDate: document.querySelector("#detailDate"),
  detailAccount: document.querySelector("#detailAccount"),
  detailSummary: document.querySelector("#detailSummary"),
  detailReason: document.querySelector("#detailReason"),
  detailActions: document.querySelector("#detailActions"),
  closeDetailBtn: document.querySelector("#closeDetailBtn"),
};

let searchTimer = null;

function setStatus(text, mode = "") {
  els.statusPill.textContent = text;
  els.statusPill.className = `status-pill ${mode}`.trim();
}

async function loadDashboard() {
  setStatus("同步中");
  const params = new URLSearchParams({
    days: state.days,
    category: state.category,
    q: state.query,
  });

  try {
    const response = await fetch(`/api/dashboard?${params.toString()}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    state.emails = data.emails || [];
    state.categories = data.categories || [];
    renderDashboard(data);
    setStatus("已同步", "ok");
  } catch (error) {
    setStatus("加载失败", "error");
    els.emailTable.innerHTML = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.appendChild(emptyState(`无法加载数据：${error.message}`));
    row.appendChild(cell);
    els.emailTable.appendChild(row);
  }
}

function renderDashboard(data) {
  const stats = data.stats || {};
  els.totalCount.textContent = stats.total ?? 0;
  els.actionCount.textContent = stats.with_actions ?? 0;
  els.confidenceAvg.textContent = formatPercent(stats.avg_confidence || 0);
  els.attachmentCount.textContent = stats.attachments ?? 0;

  renderCategoryTabs(data.categories || []);
  renderCategoryChart(data.categories || []);
  renderActions(data.action_items || []);
  renderEmails(data.emails || []);

  const generated = formatDateTime(data.meta?.generated_at);
  els.resultMeta.textContent = `${data.emails?.length || 0} 封邮件，更新于 ${generated}`;
}

function renderCategoryTabs(categories) {
  els.categoryTabs.innerHTML = "";
  const total = categories.reduce((sum, item) => sum + item.count, 0);
  const allButton = categoryButton("全部", "all", total);
  els.categoryTabs.appendChild(allButton);

  categories.forEach((item) => {
    els.categoryTabs.appendChild(categoryButton(item.category, item.category, item.count));
  });
}

function categoryButton(label, value, count) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = value === state.category ? "segment active" : "segment";
  button.textContent = `${label} ${count}`;
  button.addEventListener("click", () => {
    state.category = value;
    loadDashboard();
  });
  return button;
}

function renderCategoryChart(categories) {
  els.categoryChart.innerHTML = "";
  if (!categories.length) {
    els.categoryChart.appendChild(emptyState("暂无分类数据"));
    return;
  }

  const max = Math.max(...categories.map((item) => item.count), 1);
  categories.forEach((item) => {
    const row = document.createElement("div");
    row.className = "bar-row";

    const label = document.createElement("div");
    label.className = "bar-label";
    label.appendChild(textNode("span", item.category));
    label.appendChild(textNode("span", String(item.count)));

    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max((item.count / max) * 100, 4)}%`;
    track.appendChild(fill);

    row.append(label, track);
    els.categoryChart.appendChild(row);
  });
}

function renderActions(actions) {
  els.actionList.innerHTML = "";
  if (!actions.length) {
    els.actionList.appendChild(emptyState("暂无待办事项"));
    return;
  }

  actions.slice(0, 8).forEach((item) => {
    const card = document.createElement("article");
    card.className = `action-item ${item.priority || "normal"}`;

    const action = document.createElement("strong");
    action.textContent = item.action || "未命名待办";

    const source = document.createElement("span");
    source.textContent = `${item.subject || "无主题"} · ${item.sender_name || item.sender || "未知发件人"}`;

    const deadline = document.createElement("span");
    deadline.textContent = item.deadline ? `截止：${item.deadline}` : "未设置截止时间";

    card.append(action, source, deadline);
    els.actionList.appendChild(card);
  });
}

function renderEmails(emails) {
  els.emailTable.innerHTML = "";
  if (!emails.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.appendChild(emptyState("暂无匹配邮件"));
    row.appendChild(cell);
    els.emailTable.appendChild(row);
    return;
  }

  emails.forEach((email) => {
    const row = document.createElement("tr");
    row.appendChild(cell(formatDateShort(email.date)));
    row.appendChild(tagCell(email.category));
    row.appendChild(subjectCell(email));
    row.appendChild(cell(email.sender_name || email.sender || "-"));
    row.appendChild(confidenceCell(email.confidence));
    row.appendChild(cell(email.action_count ? String(email.action_count) : "-"));
    els.emailTable.appendChild(row);
  });
}

function subjectCell(email) {
  const td = document.createElement("td");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "row-button";
  button.textContent = email.subject || "(无主题)";
  button.addEventListener("click", () => openDetail(email));

  const summary = document.createElement("span");
  summary.className = "summary-line";
  summary.textContent = email.summary || email.category_reason || "";

  td.append(button, summary);
  return td;
}

function tagCell(value) {
  const td = document.createElement("td");
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = value || "未分类";
  td.appendChild(tag);
  return td;
}

function confidenceCell(value) {
  const td = document.createElement("td");
  td.className = "confidence";
  td.textContent = formatPercent(value || 0);
  return td;
}

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value || "-";
  return td;
}

function openDetail(email) {
  els.detailCategory.textContent = email.category || "未分类";
  els.detailSubject.textContent = email.subject || "(无主题)";
  els.detailSender.textContent = `${email.sender_name || email.sender || "-"}${email.sender ? ` <${email.sender}>` : ""}`;
  els.detailDate.textContent = formatDateTime(email.date);
  els.detailAccount.textContent = email.account || "-";
  els.detailSummary.textContent = email.summary || "-";
  els.detailReason.textContent = email.category_reason || "-";
  els.detailActions.textContent = email.action_preview
    ? email.action_preview.split(" || ").join("\n")
    : "-";
  els.detailPanel.classList.add("open");
}

function emptyState(message) {
  const div = document.createElement("div");
  div.className = "empty";
  div.textContent = message;
  return div;
}

function textNode(tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}

function formatPercent(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

function formatDateShort(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

els.daysSelect.addEventListener("change", () => {
  state.days = els.daysSelect.value;
  loadDashboard();
});

els.searchInput.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.query = els.searchInput.value.trim();
    loadDashboard();
  }, 260);
});

els.refreshBtn.addEventListener("click", loadDashboard);
els.closeDetailBtn.addEventListener("click", () => els.detailPanel.classList.remove("open"));

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    els.detailPanel.classList.remove("open");
  }
});

loadDashboard();
