// PROTOTYPE — User-confirmed split: public help center + private staff portal.
// The bottom evaluator is not product navigation. It only switches authenticated surfaces for review.

const params = new URLSearchParams(location.search);
const state = {
  surface: params.get("surface") || "customer",
  role: params.get("role") || "approver",
  moment: params.get("moment") || "investigating",
  connection: "online",
  syncNotice: "",
  lease: "unclaimed",
  decision: "none",
  rejectReason: "",
  chatOpen: true,
  clarificationAnswered: false,
};

const moments = [
  ["created", "工单创建"],
  ["investigating", "公开调查"],
  ["clarification", "客户澄清"],
  ["approval", "等待审批"],
  ["unknown", "自动对账"],
  ["succeeded", "最终结果"],
  ["handoff", "转人工"],
];

const publicState = {
  created: ["已受理", "我们已创建工单 CS-1042，正在安排自动调查。"],
  investigating: ["调查中", "我们正在核查与本次投诉相关的订单和物流信息。页面关闭后处理仍会继续。"],
  clarification: ["等待你回复", "为了确认投诉对应的订单，请选择本次物流延迟的订单。"],
  approval: ["等待处理", "已完成相关情况核查，补偿建议正在等待人工审批。最终结果将在处理完成后通知你。"],
  unknown: ["正在确认结果", "补偿请求已提交，系统正在自动核对处理结果。请勿重复提交。"],
  succeeded: ["已解决", "模拟原路部分退款 26.80 CNY 已完成。"],
  handoff: ["人工处理中", "当前情况需要人工进一步核查。客服接手后会在此工单中回复你。"],
};

function updateQuery(patch) {
  const url = new URL(location.href);
  Object.entries(patch).forEach(([key, value]) => url.searchParams.set(key, value));
  history.replaceState({}, "", url);
}

function publicMessages() {
  const common = [
    { side: "customer", label: "你", time: "14:08", body: "订单已经超过预计时间三天了，物流一直没有更新，可以帮我查一下吗？" },
    { side: "support", label: "澄途客服", time: "14:08", body: "已收到你的问题，工单 CS-1042 已创建。" },
  ];
  const extra = {
    created: [],
    investigating: [{ side: "system", label: "处理进度", time: "14:09", body: "正在核查订单与物流信息" }],
    clarification: [{ side: "support", label: "澄途客服", time: "14:09", body: "我们找到了两个可能相关的订单。请选择本次投诉对应的订单尾号。", action: "clarification" }],
    approval: [
      { side: "system", label: "处理进度", time: "14:09", body: "相关情况已核查" },
      { side: "support", label: "澄途客服", time: "14:10", body: publicState.approval[1] },
    ],
    unknown: [
      { side: "support", label: "澄途客服", time: "14:10", body: publicState.approval[1] },
      { side: "system", label: "处理进度", time: "14:11", body: "正在确认补偿结果，不会重复发起补偿", tone: "warning" },
    ],
    succeeded: [
      { side: "system", label: "处理进度", time: "14:11", body: "处理结果已确认" },
      { side: "support", label: "澄途客服", time: "14:11", body: "你的模拟原路部分退款已经完成。", result: true },
    ],
    handoff: [{ side: "support", label: "澄途客服", time: "14:10", body: publicState.handoff[1], tone: "warning" }],
  };
  if (state.clarificationAnswered) {
    common.push({ side: "customer", label: "你", time: "14:10", body: "尾号 4281 · 268.00 CNY" });
    common.push({ side: "system", label: "处理进度", time: "14:10", body: "已收到补充信息，继续调查" });
  }
  return [...common, ...(extra[state.moment] || [])];
}

function renderMessage(item) {
  if (item.side === "system") {
    return `<div class="system-message ${item.tone || ""}"><span>${item.body}</span><small>${item.time}</small></div>`;
  }
  const action = item.action === "clarification" ? `<div class="order-choices"><button data-order="4281"><b>尾号 4281</b><span>268.00 CNY · 配送至上海</span></button><button data-order="9910"><b>尾号 9910</b><span>86.00 CNY · 配送至杭州</span></button></div>` : "";
  const result = item.result ? `<div class="public-result"><span>模拟原路部分退款</span><strong>¥26.80</strong><small>原支付方式 · 尾号 4281 · 已完成</small></div>` : "";
  return `<article class="chat-message ${item.side}"><div class="message-meta"><b>${item.label}</b><time>${item.time}</time></div><div class="message-bubble">${item.body}${action}${result}</div></article>`;
}

function connectionNotice() {
  if (state.connection === "offline") return `<div class="sync-banner offline"><span><b>连接已中断</b> 当前消息可能不是最新状态。</span><button data-action="resync">重新同步</button></div>`;
  if (state.syncNotice) return `<div class="sync-banner recovered"><span><b>状态已恢复</b> 已从最新权威状态继续。</span><button data-action="dismiss-sync">关闭</button></div>`;
  return "";
}

function customerSurface() {
  const [status, summary] = publicState[state.moment] || publicState.investigating;
  return `<main class="customer-site">
    <header class="public-header"><a class="public-brand"><span>澄</span><b>澄途帮助中心</b></a><nav><a>帮助文章</a><a class="active">我的工单</a><button>林晓 · 退出</button></nav></header>
    ${connectionNotice()}
    <section class="help-hero"><p>客户支持</p><h1>今天需要什么帮助？</h1><label><span>⌕</span><input placeholder="搜索帮助文章、订单或工单" /></label></section>
    <section class="help-content">
      <div class="help-main"><div class="section-heading"><div><span>我的工单</span><h2>物流延迟投诉</h2></div><button class="outline-button">查看全部工单</button></div>
      <article class="ticket-card"><div class="ticket-summary"><span class="status-dot"></span><div><small>CS-1042 · 今天 14:08</small><h3>${status}</h3><p>${summary}</p></div><b>›</b></div><div class="public-steps">${moments.slice(0, 6).map(([key, label], index) => `<span class="${key === state.moment ? "current" : index < Math.max(0, moments.findIndex(m => m[0] === state.moment)) ? "done" : ""}"><i>${index + 1}</i>${label}</span>`).join("")}</div></article>
      <div class="article-list"><h3>也许能帮到你</h3><a><b>物流状态长时间未更新怎么办？</b><span>了解物流轨迹更新与预计送达时间 ›</span></a><a><b>补偿处理需要多长时间？</b><span>了解人工审批与处理结果通知 ›</span></a></div></div>
      <aside class="help-aside"><span>常用入口</span><a>查询订单状态 <b>›</b></a><a>补偿政策说明 <b>›</b></a><a>联系人工客服 <b>›</b></a><p>客服工单会在这里持续更新，关闭页面不会中断处理。</p></aside>
    </section>
    <button class="chat-launcher ${state.chatOpen ? "open" : ""}" data-action="toggle-chat" aria-label="打开或关闭客服会话"><span>✦</span>${state.chatOpen ? "关闭" : "获得帮助"}</button>
    <aside class="chat-panel ${state.chatOpen ? "open" : ""}" aria-label="客服会话">
      <header><div><span class="support-avatar">澄</span><div><b>澄途客服</b><small><i></i>${status} · CS-1042</small></div></div><button data-action="toggle-chat" aria-label="关闭">×</button></header>
      <div class="chat-privacy">这里只显示公开沟通和处理结果</div>
      <div class="message-list">${publicMessages().map(renderMessage).join("")}</div>
      <form class="chat-composer" data-form="chat"><textarea aria-label="回复客服" placeholder="${state.moment === "clarification" ? "选择订单或输入补充信息…" : "回复这张工单…"}"></textarea><button type="submit" aria-label="发送">↑</button><small>发送内容会成为工单的公开沟通</small></form>
    </aside>
  </main>`;
}

function staffHeader() {
  const name = state.role === "approver" ? "周宁 · 审批人" : "陈嘉 · 客服";
  return `<header class="staff-header"><a><span>澄</span><b>澄途工作台</b></a><div class="staff-search">⌕ 搜索工单、提案或订单</div><button class="notification">●</button><button class="staff-user">${name}<i>⌄</i></button></header>`;
}

function staffNav() {
  const approver = state.role === "approver";
  return `<aside class="staff-nav"><div class="workspace-label">当前工作区<small>${approver ? "补偿审批" : "客户支持"}</small></div><nav>
    ${approver ? `<a class="active"><i>▤</i>审批队列<span>1</span></a><a><i>✓</i>我的审批</a>` : `<a class="active"><i>▤</i>客服共享队列<span>1</span></a><a><i>◫</i>我的工单</a>`}
    <p>参考</p><a><i>◇</i>补偿政策</a><a><i>?</i>帮助与快捷键</a></nav><footer><span>角色权限</span><b>${approver ? "APPROVER" : "SUPPORT"}</b><small>菜单和数据由服务端权限决定</small></footer></aside>`;
}

function evidenceTable() {
  return `<dl class="evidence-table"><div><dt>补偿方式</dt><dd>模拟原路部分退款</dd></div><div><dt>最终金额</dt><dd class="money">26.80 CNY</dd></div><div><dt>提案版本</dt><dd>Revision 1 · 不可变</dd></div><div><dt>延迟事实</dt><dd>80 小时 · 物流仍在运输中</dd></div><div><dt>政策依据</dt><dd>实付金额 10% · 上限 50.00 CNY</dd></div><div><dt>资格核对</dt><dd><span class="check">✓</span>已付款　<span class="check">✓</span>未取消　<span class="check">✓</span>无既有补偿</dd></div><div><dt>证据快照</dt><dd>订单、物流、政策与额度引用 · 5 项</dd></div></dl>`;
}

function approvalDecisionPanel() {
  if (state.decision !== "none") return `<div class="access-terminated"><span>✓</span><h2>${state.decision === "approved" ? "审批已提交" : "提案已拒绝"}</h2><p>本次职责已经结束，租约和提案证据访问权已立即失效。</p><button data-action="reset-approval">重置原型</button></div>`;
  if (state.lease === "unclaimed") return `<div class="claim-box"><span>待领取</span><h3>领取后才能查看完整审批证据</h3><p>领取会创建只属于当前审批人的 15 分钟临时租约。</p><button data-action="claim">领取提案</button></div>`;
  return `<div class="decision-box"><div class="lease"><span>审批租约剩余</span><strong>14:42</strong><small>按服务端时间计算</small></div><label>拒绝原因（拒绝时必填）<textarea id="rejectReason" placeholder="仅内部可见">${state.rejectReason}</textarea></label><div><button class="reject" data-action="reject">拒绝并转人工</button><button class="approve" data-action="approve">批准 26.80 CNY</button></div><p>批准会授权唯一补偿执行；审批人不能执行、重试、对账或撤销。</p></div>`;
}

function approverWorkspace() {
  if (state.decision !== "none") return `<section class="staff-page"><div class="page-heading"><div><small>补偿审批 / CP-071</small><h1>访问已结束</h1></div></div>${approvalDecisionPanel()}</section>`;
  return `<section class="staff-page"><div class="page-heading"><div><small>补偿审批 / CP-071</small><h1>补偿提案 Revision 1</h1><p>物流延迟 · 提交于今天 14:10 · 24 小时内有效</p></div><span class="state-badge">${state.lease === "claimed" ? "租约有效" : "待领取"}</span></div>
    <div class="work-grid"><article class="evidence-card"><header><div><span>审批证据快照</span><h2>订单与政策核对</h2></div><small>只限当前提案版本</small></header>${state.lease === "claimed" ? evidenceTable() : `<div class="evidence-locked"><span>◇</span><h3>证据尚未授权</h3><p>领取提案后，系统将按当前租约加载不可变证据快照。</p></div>`}</article><aside>${approvalDecisionPanel()}</aside></div>
    <section class="responsibility"><h3>责任链</h3><div><span>14:09</span><b>Agent 提交结构化建议</b><small>不构成审批或执行授权</small></div><div><span>14:10</span><b>Spring 复核提案 Revision 1</b><small>金额、政策、额度与唯一性已重新校验</small></div></section>
  </section>`;
}

function supportWorkspace() {
  return `<section class="staff-page"><div class="page-heading"><div><small>客户支持</small><h1>客服共享队列</h1><p>未领取前只显示判断是否接手所需的最小摘要。</p></div><span class="state-badge warning">1 个待领取</span></div><div class="filter-row"><button class="active">全部 1</button><button>SLA 风险</button><button>转人工</button><span></span><button>筛选⌄</button></div><div class="queue-table"><div class="table-head"><span>风险</span><span>工单</span><span>状态</span><span>问题类别</span><span>SLA</span><span>转人工原因</span></div><div class="table-row"><span><b class="risk">P1</b></span><span><b>CS-1042</b><small>今天 14:08</small></span><span><b>调查中</b><small>HUMAN</small></span><span>物流延迟</span><span><b>42%</b><small>剩余 13h 55m</small></span><span><b>审批拒绝</b><small>等待客服领取</small></span></div></div><div class="queue-boundary"><span>i</span><p><b>首个纵向切片的权限边界</b>当前只实现共享队列最小摘要；完整对话、调查事实和内部记录要在客服成功领取、获得 active assignment 后才能加载，完整人工处理页不属于本切片。</p></div></section>`;
}

function staffSurface() {
  return `<main class="staff-site">${staffHeader()}${connectionNotice()}<div class="staff-shell">${staffNav()}${state.role === "approver" ? approverWorkspace() : supportWorkspace()}</div></main>`;
}

function evaluator() {
  return `<aside class="prototype-evaluator"><div><small>THROWAWAY PROTOTYPE · 非产品导航</small><b>独立页面与权限验证</b></div><div class="surface-switch"><button class="${state.surface === "customer" ? "active" : ""}" data-surface="customer">客户帮助中心</button><button class="${state.surface === "staff" && state.role === "approver" ? "active" : ""}" data-surface="approver">审批人工作台</button><button class="${state.surface === "staff" && state.role === "support" ? "active" : ""}" data-surface="support">客服队列</button></div><div class="moment-switch">${moments.map(([key, label]) => `<button class="${state.moment === key ? "active" : ""}" data-moment="${key}">${label}</button>`).join("")}</div><button class="connection-test" data-action="disconnect">模拟断线</button><span class="library-note">实现建议：Ant Design X 会话组件 + Ant Design 内部工作台组件</span></aside>`;
}

function render() {
  document.querySelector("#app").innerHTML = `${state.surface === "customer" ? customerSurface() : staffSurface()}${evaluator()}`;
  bind();
}

function bind() {
  document.querySelectorAll("[data-surface]").forEach(button => button.addEventListener("click", () => {
    const target = button.dataset.surface;
    state.surface = target === "customer" ? "customer" : "staff";
    if (target !== "customer") state.role = target;
    updateQuery({surface: state.surface, role: state.role});
    render();
  }));
  document.querySelectorAll("[data-moment]").forEach(button => button.addEventListener("click", () => {
    state.moment = button.dataset.moment;
    updateQuery({moment: state.moment});
    render();
  }));
  document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "toggle-chat") state.chatOpen = !state.chatOpen;
    if (action === "disconnect") { state.connection = "offline"; state.syncNotice = ""; }
    if (action === "resync") { state.connection = "online"; state.syncNotice = "ok"; }
    if (action === "dismiss-sync") state.syncNotice = "";
    if (action === "claim") state.lease = "claimed";
    if (action === "approve") { state.decision = "approved"; state.moment = "unknown"; }
    if (action === "reject") {
      const reason = document.querySelector("#rejectReason")?.value.trim() || "";
      if (!reason) { document.querySelector("#rejectReason")?.classList.add("invalid"); document.querySelector("#rejectReason")?.focus(); return; }
      state.rejectReason = reason; state.decision = "rejected"; state.moment = "handoff";
    }
    if (action === "reset-approval") { state.lease = "unclaimed"; state.decision = "none"; state.rejectReason = ""; state.moment = "approval"; }
    render();
  }));
  document.querySelectorAll("[data-order]").forEach(button => button.addEventListener("click", () => {
    state.clarificationAnswered = true; state.moment = "investigating"; updateQuery({moment: state.moment}); render();
  }));
  document.querySelector("[data-form='chat']")?.addEventListener("submit", event => {
    event.preventDefault();
    const input = event.currentTarget.querySelector("textarea");
    if (!input.value.trim()) { input.focus(); return; }
    state.clarificationAnswered = true; state.moment = "investigating"; updateQuery({moment: state.moment}); render();
  });
}

render();
