# [收缩] 删除旧 v1 单工单契约

> 父规格：[#149 规格 重塑自然语言多工单客服 Agent 与知识工作台](../../specs/issue-149.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/172](https://github.com/Stellogic/customer-agent/issues/172)
> Issue 状态：OPEN
> 创建时间：2026-08-27T17:25:33Z
> 最后更新时间：2026-08-27T17:33:44Z
> 关闭时间：—
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

Part of #149

## What to build

在所有正式 API、前端、浏览器验收、smoke、脚本和测试夹具完成迁移后执行 contract：删除旧 v1 直接建单、固定问题选择和单工单投影，不保留无消费者的兼容代码，并证明最终系统只使用 v2 产品接缝。

## Acceptance criteria

- [ ] 建立消费者清单，至少覆盖客户与内部前端、Spring 控制器、Agent adapter、Playwright、集成 smoke、验收脚本、测试夹具和文档示例。
- [ ] 每个消费者在删除前已通过 v2 真实行为验收，不以搜索替代运行证明。
- [ ] 删除旧直接建单请求、固定问题选择、v1 snapshot/event schema、旧解析器和只服务旧契约的兼容分支。
- [ ] 数据迁移或历史记录读取保持明确兼容；不得通过破坏性清库绕过旧数据处理。
- [ ] 仓库扫描证明不存在 v1 schema、旧端点、旧问题选择 UI 和废弃响应字段的非历史消费者。
- [ ] 浏览器 bundle、网络、Spring/Agent 日志和迁移历史仍满足敏感内容边界。
- [ ] 完整规范化门禁在最终 v2-only 形态通过；失败时本票只修契约收缩范围内问题，不顺手实现新功能。

## Blocked by

- #150
- #155
- #156
- #157
- #158
- #159
- #161
- #163
- #164
- #169
- #170
- #171
