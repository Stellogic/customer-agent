# [文档] 固化 #149 领域与架构基线

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/150](https://github.com/Stellogic/customer-agent/issues/150)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:24:34Z
> 最后更新时间：2026-08-27T17:32:56Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

把 #149 已确认的领域词汇、架构决定、轻量中文 RAG 调研和规格正文正式纳入主线，使后续实现 Agent 能从仓库读取同一份权威边界，而不是依赖聊天历史或未提交工作树。

## Acceptance criteria

- [ ] 主线包含本轮确认后的领域词汇，包括受理对话、共同受理记录、事实充分、订单工单组、自动解决候选、知识条目与混合知识检索。
- [ ] 主线包含高保真 UI、Spring 中转对话、L2 自治、自然语言受理、有依据自然回复和轻量中文 RAG 的已接受 ADR。
- [ ] 主线包含仅采用官方资料的轻量中文 RAG 调研，并明确 ONNX、中文词法召回和资源占用仍需实测。
- [ ] 主线保留与 GitHub #149 正文一致的仓库 Spec 镜像。
- [ ] 文档之间的相对链接、ADR 编号和术语引用有效，`git diff --check` 与文档相关门禁通过。
- [ ] 本票不修改业务代码、数据库契约或运行行为。

## Blocked by

- None — can start immediately.
