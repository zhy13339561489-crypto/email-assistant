const state = {
  days: "30",
  category: "all",
  mailbox: "inbox",
  query: "",
  emails: [],
  categories: [],
};

const els = {
  daysSelect: document.querySelector("#daysSelect"),
  inboxBtn: document.querySelector("#inboxBtn"),
  spamBtn: document.querySelector("#spamBtn"),
  searchInput: document.querySelector("#searchInput"),
  processBtn: document.querySelector("#processBtn"),
  reportBtn: document.querySelector("#reportBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  totalCount: document.querySelector("#totalCount"),
  actionCount: document.querySelector("#actionCount"),
  confidenceAvg: document.querySelector("#confidenceAvg"),
  attachmentCount: document.querySelector("#attachmentCount"),
  categoryTabs: document.querySelector("#categoryTabs"),
  categoryChart: document.querySelector("#categoryChart"),
  actionList: document.querySelector("#actionList"),
  reportBox: document.querySelector("#reportBox"),
  emailTable: document.querySelector("#emailTable"),
  resultMeta: document.querySelector("#resultMeta"),
  statusPill: document.querySelector("#statusPill"),
  detailPanel: document.querySelector("#detailPanel"),
  detailCategory: document.querySelector("#detailCategory"),
  detailSubject: document.querySelector("#detailSubject"),
  detailSender: document.querySelector("#detailSender"),
  detailDate: document.querySelector("#detailDate"),
  detailAccount: document.querySelector("#detailAccount"),
  detailRecipient: document.querySelector("#detailRecipient"),
  detailAttachments: document.querySelector("#detailAttachments"),
  detailRawBody: document.querySelector("#detailRawBody"),
  detailRawHeaders: document.querySelector("#detailRawHeaders"),
  detailSummary: document.querySelector("#detailSummary"),
  detailReason: document.querySelector("#detailReason"),
  detailActions: document.querySelector("#detailActions"),
  replySection: document.querySelector("#replySection"),
  replyStatus: document.querySelector("#replyStatus"),
  replyReason: document.querySelector("#replyReason"),
  replyAiReview: document.querySelector("#replyAiReview"),
  replySubject: document.querySelector("#replySubject"),
  replyBody: document.querySelector("#replyBody"),
  replyNotes: document.querySelector("#replyNotes"),
  saveReplyBtn: document.querySelector("#saveReplyBtn"),
  reviseReplyBtn: document.querySelector("#reviseReplyBtn"),
  sendReplyBtn: document.querySelector("#sendReplyBtn"),
  replyMessage: document.querySelector("#replyMessage"),
  closeDetailBtn: document.querySelector("#closeDetailBtn"),
};

let searchTimer = null;
let selectedEmail = null;

function setStatus(text, mode = "") {
  els.statusPill.textContent = text;
  els.statusPill.className = `status-pill ${mode}`.trim();
}

async function loadDashboard() {
  setStatus("同步中");
  const params = new URLSearchParams({
    days: state.days,
    category: state.category,
    mailbox: state.mailbox,
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
    loadLatestReport();
    setStatus("已同步", "ok");
  } catch (error) {
    setStatus("加载失败", "error");
    els.emailTable.innerHTML = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.appendChild(emptyState(`无法加载数据：${error.message}`));
    row.appendChild(cell);
    els.emailTable.appendChild(row);
  }
}

async function loadLatestReport() {
  try {
    const response = await fetch("/api/reports/latest", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    renderLatestReport(data.report);
  } catch (error) {
    console.error(error);
  }
}

async function generateDailyReport() {
  setStatus("生成日报");
  els.reportBtn.disabled = true;
  try {
    const response = await fetch("/api/reports/daily", { method: "POST" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const text = await response.text();
    let result = {};
    try {
      result = text ? JSON.parse(text) : {};
    } catch {
      result = { error: text || `HTTP ${response.status}` };
    }
    if (result.error) {
      throw new Error(result.error);
    }
    setStatus("日报完成", "ok");
    await loadLatestReport();
  } catch (error) {
    setStatus("日报失败", "error");
    console.error(error);
  } finally {
    els.reportBtn.disabled = false;
  }
}

async function processNow() {
  setStatus("处理中");
  els.processBtn.disabled = true;
  try {
    const response = await fetch("/api/process", { method: "POST" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    if (result.error) {
      throw new Error(result.error);
    }
    setStatus(result.running ? "已在运行" : `处理 ${result.processed || 0} 封`, "ok");
    await loadDashboard();
  } catch (error) {
    setStatus("处理失败", "error");
    console.error(error);
  } finally {
    els.processBtn.disabled = false;
  }
}

async function deleteEmail(emailId) {
  if (!window.confirm("确认删除这封邮件吗？")) {
    return;
  }
  await deleteEntity(`/api/emails/${emailId}/delete`, "邮件已删除");
  if (selectedEmail?.id === emailId) {
    selectedEmail = null;
    els.detailPanel.classList.remove("open");
  }
}

async function deleteActionItem(actionId) {
  if (!window.confirm("确认删除这个待办事项吗？")) {
    return;
  }
  await deleteEntity(`/api/actions/${actionId}/delete`, "待办事项已删除");
}

async function deleteEntity(url, successText) {
  setStatus("删除中");
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const result = await response.json();
    if (!response.ok || result.ok === false) {
      throw new Error(result.error || result.message || `HTTP ${response.status}`);
    }
    setStatus(result.message || successText, "ok");
    await loadDashboard();
  } catch (error) {
    setStatus("删除失败", "error");
    console.error(error);
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
  const mailboxName = state.mailbox === "spam" ? "垃圾邮件箱" : "普通邮件箱";
  els.resultMeta.textContent = `${mailboxName} · ${data.emails?.length || 0} 封邮件，更新于 ${generated}`;
}

function renderCategoryTabs(categories) {
  els.categoryTabs.innerHTML = "";
  const total = categories.reduce((sum, item) => sum + item.count, 0);
  const allLabel = state.mailbox === "spam" ? "垃圾邮件" : "全部";
  const allButton = categoryButton(allLabel, "all", total);
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

function setMailbox(mailbox) {
  state.mailbox = mailbox;
  state.category = "all";
  els.inboxBtn.classList.toggle("active", mailbox === "inbox");
  els.spamBtn.classList.toggle("active", mailbox === "spam");
  loadDashboard();
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

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "delete-button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteActionItem(item.id));

    card.append(action, source, deadline, deleteButton);
    els.actionList.appendChild(card);
  });
}

function renderLatestReport(report) {
  els.reportBox.innerHTML = "";
  if (!report) {
    els.reportBox.appendChild(emptyState("暂无日报"));
    return;
  }

  const meta = document.createElement("div");
  meta.className = "report-meta";
  meta.textContent = `${formatDateTime(report.window_start)} 至 ${formatDateTime(report.window_end)} · ${report.email_count || 0} 封`;

  const content = document.createElement("div");
  content.className = "report-content";
  content.textContent = report.content || "日报内容为空";

  els.reportBox.append(meta, content);
}

function renderEmails(emails) {
  els.emailTable.innerHTML = "";
  if (!emails.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
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
    row.appendChild(replyCell(email.reply));
    row.appendChild(emailActionsCell(email));
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

function replyCell(reply) {
  const td = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `reply-badge ${reply?.status || "none"}`;
  badge.textContent = replyLabel(reply);
  td.appendChild(badge);
  return td;
}

function emailActionsCell(email) {
  const td = document.createElement("td");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "delete-button";
  button.textContent = "删除";
  button.addEventListener("click", () => deleteEmail(email.id));
  td.appendChild(button);
  return td;
}

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value || "-";
  return td;
}

function openDetail(email) {
  selectedEmail = email;
  els.detailCategory.textContent = email.category || "未分类";
  els.detailSubject.textContent = email.subject || "(无主题)";
  els.detailSender.textContent = `${email.sender_name || email.sender || "-"}${email.sender ? ` <${email.sender}>` : ""}`;
  els.detailDate.textContent = formatDateTime(email.date);
  els.detailAccount.textContent = email.account || "-";
  els.detailRecipient.textContent = email.recipient || "-";
  els.detailAttachments.textContent = formatAttachments(email.attachment_names);
  els.detailRawBody.textContent = email.raw_body_text || email.body_text || "-";
  els.detailRawHeaders.textContent = email.raw_headers || "-";
  els.detailSummary.textContent = email.summary || "-";
  els.detailReason.textContent = email.category_reason || "-";
  els.detailActions.textContent = email.action_preview
    ? email.action_preview.split(" || ").join("\n")
    : "-";
  renderReplyReview(email.reply);
  els.detailPanel.classList.add("open");
}

function renderReplyReview(reply) {
  els.replyMessage.textContent = "";
  els.replyStatus.textContent = replyLabel(reply);
  els.replyStatus.className = `reply-status ${reply?.status || "none"}`;
  els.replyReason.textContent = reply?.reason || "该邮件还没有回复路由结果。";
  els.replyAiReview.textContent = formatAiReview(reply);
  els.replySubject.value = reply?.subject || "";
  els.replyBody.value = reply?.body || "";
  els.replyNotes.value = reply?.reviewer_notes || "";

  const canEdit = Boolean(reply?.id && reply.needs_reply && reply.status !== "sent");
  els.replySubject.disabled = !canEdit;
  els.replyBody.disabled = !canEdit;
  els.replyNotes.disabled = !canEdit;
  els.saveReplyBtn.disabled = !canEdit;
  els.reviseReplyBtn.disabled = !canEdit;
  els.sendReplyBtn.disabled = !canEdit;
}

async function saveReplyDraft() {
  await submitReplyAction("save");
}

async function reviseReplyDraft() {
  if (!els.replyNotes.value.trim()) {
    els.replyMessage.textContent = "请先填写修改意见。";
    return;
  }
  await submitReplyAction("revise");
}

async function sendReplyDraft() {
  if (!window.confirm("确认审核通过并发送这封回复邮件吗？")) {
    return;
  }
  await submitReplyAction("send");
}

async function submitReplyAction(action) {
  const reply = selectedEmail?.reply;
  if (!reply?.id) {
    els.replyMessage.textContent = "当前邮件没有可操作的回复草稿。";
    return;
  }

  setReplyBusy(true);
  els.replyMessage.textContent = action === "send" ? "正在发送..." : "正在处理...";
  try {
    const response = await fetch(`/api/replies/${reply.id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        subject: els.replySubject.value,
        body: els.replyBody.value,
        reviewer_notes: els.replyNotes.value,
      }),
    });
    const text = await response.text();
    let result = {};
    try {
      result = text ? JSON.parse(text) : {};
    } catch {
      result = { error: text || `HTTP ${response.status}` };
    }
    if (!response.ok || result.error || result.ok === false) {
      throw new Error(result.error || `HTTP ${response.status}`);
    }

    if (action === "revise") {
      els.replySubject.value = result.subject || els.replySubject.value;
      els.replyBody.value = result.body || els.replyBody.value;
    }

    els.replyMessage.textContent = result.message || "完成";
    selectedEmail.reply = {
      ...reply,
      subject: els.replySubject.value,
      body: els.replyBody.value,
      reviewer_notes: els.replyNotes.value,
      ai_review_notes: result.ai_review_notes || reply.ai_review_notes || "",
      ai_review_rounds: result.ai_review_rounds ?? reply.ai_review_rounds ?? 0,
      ai_review_passed: result.ai_review_passed ?? reply.ai_review_passed ?? false,
      status: action === "send" ? "sent" : "pending_review",
      send_error: "",
    };
    renderReplyReview(selectedEmail.reply);
    await loadDashboard();
  } catch (error) {
    els.replyMessage.textContent = formatRequestError(error);
  } finally {
    setReplyBusy(false);
  }
}

function formatRequestError(error) {
  const message = error?.message || "请求失败";
  if (
    message.includes("NetworkError") ||
    message.includes("Failed to fetch") ||
    message.includes("Load failed")
  ) {
    return "无法连接后端，请确认后端服务正在运行，然后重试。";
  }
  return message;
}

function setReplyBusy(isBusy) {
  const reply = selectedEmail?.reply;
  const canEdit = Boolean(reply?.id && reply.needs_reply && reply.status !== "sent");
  els.saveReplyBtn.disabled = isBusy || !canEdit;
  els.reviseReplyBtn.disabled = isBusy || !canEdit;
  els.sendReplyBtn.disabled = isBusy || !canEdit;
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

function formatAttachments(value) {
  if (!Array.isArray(value) || !value.length) {
    return "-";
  }
  return value.join("\n");
}

function replyLabel(reply) {
  if (!reply) return "未判断";
  if (!reply.needs_reply) {
    return reply.status === "route_failed" ? "路由失败" : "无需回复";
  }
  const labels = {
    pending_review: "待审核",
    approved: "发送中",
    sent: "已发送",
    send_failed: "发送失败",
  };
  return labels[reply.status] || "待审核";
}

function formatAiReview(reply) {
  if (!reply?.ai_review_notes) {
    return "-";
  }
  const status = reply.ai_review_passed ? "审阅通过" : "审阅未完全通过";
  const rounds = reply.ai_review_rounds ? ` · ${reply.ai_review_rounds} 轮` : "";
  return `${status}${rounds}\n${reply.ai_review_notes}`;
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
els.processBtn.addEventListener("click", processNow);
els.reportBtn.addEventListener("click", generateDailyReport);
els.inboxBtn.addEventListener("click", () => setMailbox("inbox"));
els.spamBtn.addEventListener("click", () => setMailbox("spam"));
els.saveReplyBtn.addEventListener("click", saveReplyDraft);
els.reviseReplyBtn.addEventListener("click", reviseReplyDraft);
els.sendReplyBtn.addEventListener("click", sendReplyDraft);
els.closeDetailBtn.addEventListener("click", () => els.detailPanel.classList.remove("open"));

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    els.detailPanel.classList.remove("open");
  }
});

loadDashboard();
