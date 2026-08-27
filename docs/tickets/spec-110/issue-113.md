# [B0] 实现受控 DeepSeek Responses adapter

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/113](https://github.com/Stellogic/customer-agent/issues/113)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:48:46Z
> 最后更新时间：2026-08-24T17:54:35Z
> 关闭时间：2026-08-24T17:54:35Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

实现仅面向调查判断模型的 DeepSeek adapter，使用 OpenAI 兼容 Responses API 和严格结构化输出。adapter 负责配置、允许参数、响应状态解析、超时、有限重试、最小调用审计和稳定失败归类；选择 DeepSeek 但配置缺失时显式失败，绝不回退 fake。

## Acceptance criteria

- [ ] adapter 只发送合成最小结构化事实，并使用受控请求参数与严格 schema。
- [ ] 能够区分完成、失败、不完整、拒绝、空正文、非法 JSON、schema 不匹配和截断。
- [ ] 具有连接、读取、整体截止时间和最大尝试预算；确定性错误不重试，暂时性错误只有限重试。
- [ ] 调用记录包含必要追踪、模型、版本、耗时和 usage 元数据，但不保存密钥、原始输入输出或思维链。
- [ ] 本票不要求真实 API key；通过模拟传输测试和仓库完整门禁。

## Blocked by

- #112
