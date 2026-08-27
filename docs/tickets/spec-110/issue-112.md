# [B0] 建立调查判断模型 seam 与固定假模型实现

> 父规格：[#110 规格 将固定模型基线演进为 DeepSeek 驱动的自主客服 Agent](../../specs/issue-110.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/112](https://github.com/Stellogic/customer-agent/issues/112)
> Issue 状态：CLOSED
> 创建时间：2026-08-24T14:48:38Z
> 最后更新时间：2026-08-24T16:55:43Z
> 关闭时间：2026-08-24T16:55:43Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#110

## What to build

建立小而稳定的调查判断模型接口，把当前固定假模型迁入该接口，并让普通运行与 CI 默认继续使用确定性 fake。调用者只接触领域输入、受控结论或稳定失败，不感知供应商 HTTP、解析和重试细节。

## Acceptance criteria

- [ ] 固定假模型通过新的公共接口产生与当前一致的调查结果。
- [ ] 模型接口只返回受控判断字段，不返回或复述权威补偿金额、方式和订单事实。
- [ ] 默认配置和普通 CI 不访问外部模型，也不要求任何 API key。
- [ ] 接口契约测试覆盖成功、受控失败和证据白名单校验，并通过完整门禁。

## Blocked by

- #111
