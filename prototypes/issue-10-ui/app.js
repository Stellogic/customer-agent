// PROTOTYPE — Three UI variants for Issue 10, switchable via ?variant=A|B|C.
// Read-only synthetic state only. This is intentionally not production React code.

const variants = {
  A: { name: "双舞台", note: "旅程与当前动作并列" },
  B: { name: "事件剧场", note: "一次聚焦一个关键时刻" },
  C: { name: "克制操作台", note: "高密度核对与明确边界" },
};

const moments = [
  { id: "created", short: "建单", title: "工单已受理", publicStatus: "新建", kicker: "00:00" },
  { id: "investigating", short: "调查", title: "正在核查订单与物流", publicStatus: "调查中", kicker: "00:18" },
  { id: "approval", short: "待审批", title: "补偿建议等待人工审批", publicStatus: "调查中", kicker: "01:36" },
  { id: "unknown", short: "对账", title: "正在确认补偿结果", publicStatus: "调查中", kicker: "02:24" },
  { id: "succeeded", short: "完成", title: "模拟部分退款已完成", publicStatus: "已解决", kicker: "02:52" },
];

const state = {
  variant: new URLSearchParams(location.search).get("variant")?.toUpperCase() || "A",
  role: "customer",
  moment: "created",
  connection: "online",
  syncNotice: "",
  lease: "unclaimed",
  decision: "none",
  rejectionReason: "",
  clarificationText: "",
};

if (!variants[state.variant]) state.variant = "A";

const publicCopy = {
  created: {
    eyebrow: "我们已经收到你的问题",
    message: "物流延迟工单 CS-1042 已创建。首次响应目标为 15 分钟。",
    action: "开始自动调查",
  },
  investigating: {
    eyebrow: "处理正在进行",
    message: "我们正在核查与本次投诉相关的信息。页面可以关闭，处理会继续。",
    action: "查看公开进度",
  },
  clarification: {
    eyebrow: "需要你补充一项信息",
    message: "我们找到两个可能相关的订单。请选择本次投诉对应的订单尾号。",
    action: "提交并继续调查",
  },
  approval: {
    eyebrow: "相关情况已核查",
    message: "补偿建议正在等待人工审批。最终结果将在处理完成后通知你。",
    action: "无需操作",
  },
  unknown: {
    eyebrow: "正在确认最终结果",
    message: "补偿请求已提交，系统正在自动核对处理结果。请勿重复提交。",
    action: "自动对账中",
  },
  succeeded: {
    eyebrow: "处理完成",
    message: "模拟原路部分退款 26.80 CNY 已完成，工单进入已解决状态。",
    action: "查看处理结果",
  },
  handoff: {
    eyebrow: "已转交人工处理",
    message: "当前情况需要人工进一步核查。客服接手后会在此工单中回复你。",
    action: "等待客服接手",
  },
  rejected: {
    eyebrow: "已转交人工处理",
    message: "补偿建议未直接执行，工单已进入人工处理队列。",
    action: "等待客服接手",
  },
};

function currentMomentIndex() {
  return Math.max(0, moments.findIndex((item) => item.id === state.moment));
}

function customerTimeline() {
  const active = currentMomentIndex();
  return moments.map((item, index) => {
    const status = index < active ? "done" : index === active ? "active" : "future";
    return `<li class="timeline-item ${status}">
      <span class="timeline-mark">${status === "done" ? "✓" : index + 1}</span>
      <span><strong>${item.short}</strong><small>${index <= active ? item.title : "等待前一步完成"}</small></span>
    </li>`;
  }).join("");
}

function roleTabs() {
  const roles = [
    ["customer", "客户", "CUSTOMER_PUBLIC"],
    ["approver", "审批人", "APPROVAL_VIEW"],
    ["support", "客服队列", "SUPPORT_WORKBENCH · 最小摘要"],
  ];
  return `<nav class="role-tabs" aria-label="授权视图">${roles.map(([key, label, detail]) => `
    <button class="role-tab ${state.role === key ? "selected" : ""}" data-role="${key}">
      <span>${label}</span><small>${detail}</small>
    </button>`).join("")}</nav>`;
}

function sceneControls() {
  const controls = [
    ["created", "建单"], ["investigating", "调查"], ["clarification", "客户澄清"],
    ["approval", "等待审批"], ["unknown", "UNKNOWN 对账"], ["succeeded", "最终结果"],
    ["handoff", "安全转人工"], ["rejected", "审批拒绝"],
  ];
  return `<div class="scene-controls" aria-label="原型场景">${controls.map(([key, label]) => `
    <button class="scene-chip ${state.moment === key ? "active" : ""}" data-moment="${key}">${label}</button>`).join("")}</div>`;
}

function connectionBanner() {
  if (state.connection === "offline") {
    return `<aside class="connection-banner danger" role="status">
      <span><b>实时连接已中断</b> 页面已停止应用增量更新，当前内容可能不是最新状态。</span>
      <button data-action="resync">重新同步权威状态</button>
    </aside>`;
  }
  if (state.syncNotice) {
    return `<aside class="connection-banner success" role="status"><span><b>状态已恢复</b> ${state.syncNotice}</span><button data-action="dismiss-sync">知道了</button></aside>`;
  }
  return "";
}

function prototypeHeader() {
  return `<header class="prototype-header">
    <a class="brand" href="?variant=${state.variant}" aria-label="澄途客服首页">
      <span class="brand-mark">澄</span><span><b>澄途客服</b><small>物流延迟处理中心</small></span>
    </a>
    <div class="ticket-id"><span>合成演示数据</span><b>CS-1042</b></div>
    <button class="connection-toggle ${state.connection}" data-action="disconnect">
      <i></i>${state.connection === "online" ? "实时状态已连接" : "连接已断开"}
    </button>
  </header>`;
}

function customerCore(mode) {
  const copy = publicCopy[state.moment] || publicCopy.investigating;
  const clarification = state.moment === "clarification" ? `
    <form class="clarification-form" data-form="clarification">
      <label><span>对应订单</span>
        <select name="order"><option value="">请选择</option><option>尾号 4281 · 268.00 CNY</option><option>尾号 9910 · 86.00 CNY</option></select>
      </label>
      <label><span>补充说明（可选）</span><textarea name="clarification" placeholder="例如：是给上海地址的那一单">${state.clarificationText}</textarea></label>
      <button class="primary-action" type="submit">${copy.action}</button>
    </form>` : "";
  const unknown = state.moment === "unknown" ? `
    <div class="reconcile-note"><span class="spinner"></span><div><b>正在自动对账</b><small>不会再次发起补偿；无需刷新或重复操作。</small></div></div>` : "";
  const success = state.moment === "succeeded" ? `
    <div class="result-slip"><span>模拟部分退款</span><strong>¥26.80</strong><small>原支付方式 · 尾号 4281 · 已完成</small></div>` : "";
  const privacy = `<p class="privacy-note">你看到的是公开处理进度。内部调查记录、工具数据、提案草稿与审批过程不会显示在这里。</p>`;

  if (mode === "theatre") {
    return `<section class="customer-theatre">
      <div class="scene-number">${String(Math.max(1, currentMomentIndex() + 1)).padStart(2, "0")}</div>
      <p class="eyebrow">${copy.eyebrow}</p><h1>${copy.message}</h1>
      <div class="theatre-status"><span>${copy.action}</span><i></i><span>${publicCopy[state.moment] ? (moments.find(m => m.id === state.moment)?.publicStatus || "调查中") : "调查中"}</span></div>
      ${clarification}${unknown}${success}${privacy}
    </section>`;
  }

  if (mode === "ops") {
    return `<section class="ops-customer">
      <div class="ops-title"><div><p>${copy.eyebrow}</p><h1>${copy.message}</h1></div><span class="status-stamp">${moments.find(m => m.id === state.moment)?.publicStatus || "调查中"}</span></div>
      <dl class="public-facts"><div><dt>问题类型</dt><dd>物流延迟</dd></div><div><dt>创建时间</dt><dd>今天 14:08</dd></div><div><dt>首次响应</dt><dd>已完成 · 00:18</dd></div></dl>
      ${clarification}${unknown}${success}${privacy}
    </section>`;
  }

  return `<section class="customer-stage">
    <p class="eyebrow">${copy.eyebrow}</p><h1>${copy.message}</h1>
    <div class="public-status-line"><span class="pulse-dot"></span><b>${copy.action}</b><small>${moments.find(m => m.id === state.moment)?.publicStatus || "调查中"}</small></div>
    ${clarification}${unknown}${success}${privacy}
  </section>`;
}

function approvalEvidence() {
  return `<dl class="evidence-list">
    <div><dt>补偿方式</dt><dd>模拟原路部分退款</dd></div>
    <div><dt>最终金额</dt><dd class="money">26.80 CNY</dd></div>
    <div><dt>提案版本</dt><dd>Revision 1 · 不可变</dd></div>
    <div><dt>政策依据</dt><dd>延迟 80 小时 · 实付金额 10% · 上限 50.00</dd></div>
    <div><dt>资格核对</dt><dd>已付款；未取消；未全额退款；无既有补偿</dd></div>
    <div><dt>证据快照</dt><dd>订单、物流、政策与额度引用 · 5 项</dd></div>
  </dl>`;
}

function approvalActions() {
  if (state.decision !== "none") {
    return `<div class="access-ended"><span>✓</span><h3>${state.decision === "approved" ? "审批已提交" : "提案已拒绝"}</h3><p>本次审批职责已经结束，原租约与审批视图访问权立即失效。</p><button data-action="reset-approval">重置原型</button></div>`;
  }
  if (state.lease === "unclaimed") {
    return `<div class="claim-panel"><p>领取后获得该提案版本的临时排他审批权限。</p><button class="primary-action" data-action="claim">领取提案并开始 15 分钟租约</button></div>`;
  }
  return `<div class="decision-panel">
    <div class="lease-clock"><span>审批租约</span><strong>14:42</strong><small>服务端计时 · 到期后立即撤权</small></div>
    <label class="reject-reason"><span>拒绝原因（拒绝时必填）</span><textarea id="rejectReason" placeholder="仅内部可见">${state.rejectionReason}</textarea></label>
    <div class="decision-buttons"><button class="reject" data-action="reject">拒绝并转人工</button><button class="approve" data-action="approve">批准 26.80 CNY</button></div>
    <p class="decision-note">批准会最终授权唯一补偿执行；审批人不能执行、重试、对账或撤销。</p>
  </div>`;
}

function approverCore(mode) {
  if (state.decision !== "none") {
    return `<section class="approval-access-terminated">
      <div class="access-ended"><span>✓</span><h1>${state.decision === "approved" ? "审批已提交" : "提案已拒绝"}</h1>
      <p>本次审批职责已经结束。原租约与审批视图访问权立即失效，提案证据已从页面移除。</p>
      <button data-action="reset-approval">重置原型</button></div>
    </section>`;
  }
  if (state.moment !== "approval" && state.decision === "none") {
    return `<section class="empty-approval"><span>审批队列</span><h1>当前场景没有待审批提案</h1><p>切换到“等待审批”场景，查看提案领取、租约与批准/拒绝交互。</p><button data-moment="approval">打开等待审批场景</button></section>`;
  }
  if (mode === "theatre") {
    return `<section class="approval-theatre"><div class="proposal-seal">提案<br><b>CP-071</b></div><div class="approval-story"><p class="eyebrow">一次只审一个不可变版本</p><h1>物流延迟 80 小时，建议模拟退款 <em>¥26.80</em></h1>${state.lease === "claimed" ? approvalEvidence() : ""}</div><aside>${approvalActions()}</aside></section>`;
  }
  if (mode === "ops") {
    return `<section class="approval-ops"><header><div><small>审批共享队列 / CP-071</small><h1>补偿提案 Revision 1</h1></div><span class="proposal-state">${state.lease === "claimed" ? "租约有效" : "待领取"}</span></header><div class="approval-ops-body"><div>${approvalEvidence()}</div><aside>${approvalActions()}</aside></div></section>`;
  }
  return `<section class="approval-stage"><div class="proposal-heading"><span>CP-071 · Revision 1</span><h1>先核对证据，再作最终授权</h1><p>审批视图只覆盖当前提案版本，不包含完整工单、完整对话或内部 Agent 轨迹。</p></div><div class="approval-columns"><div>${approvalEvidence()}</div><aside>${approvalActions()}</aside></div></section>`;
}

function supportCore(mode) {
  const tag = state.moment === "rejected" ? "审批拒绝" : "安全转人工";
  const body = `<div class="queue-row"><span class="queue-priority">P1</span><b>CS-1042</b><span>调查中</span><span>物流延迟</span><span>SLA 风险 42%</span><strong>${tag}</strong></div>`;
  const note = `<p class="queue-boundary">首个纵向切片只验证共享队列最小摘要，不实现完整客服工作台，也不在领取前暴露对话、调查事实或内部记录。</p>`;
  if (mode === "theatre") return `<section class="support-theatre"><p class="eyebrow">失败路径只留下一个清晰出口</p><h1>一行摘要，足够发现；领取之前，不足以窥探。</h1>${body}${note}</section>`;
  if (mode === "ops") return `<section class="support-ops"><header><h1>客服共享队列</h1><span>1 个待领取</span></header><div class="queue-head"><span>风险</span><span>工单</span><span>状态</span><span>类别</span><span>SLA</span><span>原因</span></div>${body}${note}</section>`;
  return `<section class="support-stage"><div><p class="eyebrow">客服共享队列</p><h1>只显示接手判断所需的最小摘要</h1></div>${body}${note}</section>`;
}

function roleContent(mode) {
  if (state.role === "approver") return approverCore(mode);
  if (state.role === "support") return supportCore(mode);
  return customerCore(mode);
}

function variantA() {
  return `<main class="variant variant-a">
    ${prototypeHeader()}${connectionBanner()}
    <section class="a-intro"><div><span>方案 A / 双舞台</span><h2>让客户旅程与当前决定同时在场</h2></div>${roleTabs()}</section>
    ${sceneControls()}
    <div class="a-layout">
      <aside class="journey-rail"><span class="rail-label">公开旅程</span><ol>${customerTimeline()}</ol><button data-action="disconnect" class="ghost-action">模拟 SSE 断线</button></aside>
      <div class="a-workspace">${roleContent("stage")}</div>
    </div>
  </main>`;
}

function variantB() {
  return `<main class="variant variant-b">
    ${prototypeHeader()}${connectionBanner()}
    <div class="b-toolbar">${roleTabs()}<button data-action="disconnect" class="ghost-action">制造一次断线</button></div>
    <div class="b-stage">${roleContent("theatre")}</div>
    <footer class="scene-reel"><span>演示章节</span>${moments.map((item, index) => `<button data-moment="${item.id}" class="${state.moment === item.id ? "active" : ""}"><i>${index + 1}</i><b>${item.short}</b><small>${item.kicker}</small></button>`).join("")}<button data-moment="clarification"><i>+</i><b>澄清</b><small>支线</small></button><button data-moment="handoff"><i>!</i><b>转人工</b><small>失败</small></button></footer>
  </main>`;
}

function variantC() {
  return `<main class="variant variant-c">
    ${prototypeHeader()}${connectionBanner()}
    <div class="c-shell">
      <aside class="c-nav"><p>授权视图</p>${roleTabs()}<p>状态索引</p>${sceneControls()}<button data-action="disconnect" class="ghost-action">模拟断线 / 重置</button></aside>
      <section class="c-main"><header class="c-context"><span>方案 C</span><b>克制操作台</b><small>信息密度优先，权限边界始终可见</small></header>${roleContent("ops")}</section>
      <aside class="c-guardrail"><span>当前投影</span><strong>${state.role === "customer" ? "CUSTOMER_PUBLIC" : state.role === "approver" ? "APPROVAL_VIEW" : "SUPPORT_WORKBENCH"}</strong><dl><dt>事实来源</dt><dd>Spring 权威快照</dd><dt>实时体验</dt><dd>${state.connection === "online" ? "SSE 已连接" : "已停止增量"}</dd><dt>隐藏内容</dt><dd>内部 Agent 流<br>原始工具 payload<br>自由形式推理</dd></dl></aside>
    </div>
  </main>`;
}

function switcher() {
  const label = variants[state.variant];
  return `<div class="prototype-switcher" aria-label="原型变体切换器">
    <button data-variant-direction="prev" aria-label="上一个方案">←</button>
    <div><small>THROWAWAY PROTOTYPE</small><b>${state.variant} — ${label.name}</b><span>${label.note}</span></div>
    <button data-variant-direction="next" aria-label="下一个方案">→</button>
  </div>`;
}

function render() {
  const root = document.querySelector("#app");
  root.innerHTML = `${state.variant === "A" ? variantA() : state.variant === "B" ? variantB() : variantC()}${switcher()}`;
  document.body.dataset.variant = state.variant;
  bindEvents();
}

function setVariant(next) {
  state.variant = next;
  const url = new URL(location.href);
  url.searchParams.set("variant", next);
  history.replaceState({}, "", url);
  document.querySelector("#announcer").textContent = `已切换到方案 ${next}，${variants[next].name}`;
  render();
}

function cycleVariant(direction) {
  const keys = Object.keys(variants);
  const current = keys.indexOf(state.variant);
  const next = (current + direction + keys.length) % keys.length;
  setVariant(keys[next]);
}

function bindEvents() {
  document.querySelectorAll("[data-role]").forEach((button) => button.addEventListener("click", () => {
    state.role = button.dataset.role;
    render();
  }));
  document.querySelectorAll("[data-moment]").forEach((button) => button.addEventListener("click", () => {
    state.moment = button.dataset.moment;
    if (state.moment === "rejected") state.role = "support";
    render();
  }));
  document.querySelectorAll("[data-variant-direction]").forEach((button) => button.addEventListener("click", () => cycleVariant(button.dataset.variantDirection === "next" ? 1 : -1)));
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "disconnect") { state.connection = "offline"; state.syncNotice = ""; }
    if (action === "resync") { state.connection = "online"; state.syncNotice = "已丢弃不连续增量，并从当前授权视图的最新快照重新开始。"; }
    if (action === "dismiss-sync") state.syncNotice = "";
    if (action === "claim") state.lease = "claimed";
    if (action === "approve") { state.decision = "approved"; state.moment = "unknown"; }
    if (action === "reject") {
      const reason = document.querySelector("#rejectReason")?.value.trim() || "";
      if (!reason) { document.querySelector("#rejectReason")?.focus(); document.querySelector("#rejectReason")?.classList.add("invalid"); return; }
      state.rejectionReason = reason; state.decision = "rejected"; state.moment = "rejected";
    }
    if (action === "reset-approval") { state.lease = "unclaimed"; state.decision = "none"; state.rejectionReason = ""; state.moment = "approval"; }
    render();
  }));
  document.querySelector("[data-form='clarification']")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (!data.get("order")) { event.currentTarget.querySelector("select").classList.add("invalid"); return; }
    state.clarificationText = data.get("clarification");
    state.moment = "investigating";
    render();
  });
}

window.addEventListener("keydown", (event) => {
  const tag = document.activeElement?.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || document.activeElement?.isContentEditable) return;
  if (event.key === "ArrowLeft") cycleVariant(-1);
  if (event.key === "ArrowRight") cycleVariant(1);
});

render();
