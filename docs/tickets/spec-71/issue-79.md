# 收缩旧人工身份与旧路由兼容面

> 父规格：[#71 规格 统一客户帮助中心与内部工作台的登录、鉴权及路由](../../specs/issue-71.md)
> 来源：[https://github.com/Stellogic/customer-agent/issues/79](https://github.com/Stellogic/customer-agent/issues/79)
> Issue 状态：CLOSED
> 创建时间：2026-08-16T10:25:56Z
> 最后更新时间：2026-08-22T13:41:39Z
> 关闭时间：2026-08-22T13:41:39Z
> 同步日期：2026-08-28
> 说明：本文件是 GitHub 实施票据正文的只读镜像；GitHub Issue 仍是票据事实源。票据不替代父规格、已接受 ADR 或当前产品契约。

## Parent

#71

## What to build

完成合成人工身份到 Spring Principal 的收缩阶段，删除旧身份和手工路由的产品行为，保留受控的旧 URL 重定向，并用全 API 负向矩阵证明统一工作台不存在混合身份模式。

## Acceptance criteria

- [ ] 产品运行路径不再读取或接受 `X-Synthetic-Customer-Id`、`X-Synthetic-Support-Id` 或 `X-Synthetic-Approver-Id`。
- [ ] 携带任意伪造合成身份头不能改变当前 Principal、角色、capability、客户归属、客服分配或审批租约。
- [ ] 旧合成人工身份入口和页面中的固定身份选择行为被删除；测试改用受控 Spring Security 测试身份。
- [ ] Agent 与补偿执行器等机器身份认证链保持独立且原有最小能力不变。
- [ ] 前端不再通过手工 `pathname` 分支装载客户、客服和审批页面，唯一页面来源是静态 React 路由表。
- [ ] `/support` 与 `/approver` 只重定向到正式内部路由并标记弃用，不保留第二套页面或授权逻辑。
- [ ] 全部人工 API 的负向矩阵证明：未认证为 401、缺少粗粒度能力为 403、不可枚举资源为 404、可见资源的租约或版本冲突为 409。
- [ ] Spring 当前身份响应和错误响应不泄露密码、cookie、CSRF token、内部路由定义或动态资源权限。
- [ ] 仓库代码、测试、演示入口与文档扫描不再把合成人工请求头当作有效产品契约；必要的历史说明必须明确标注为已废弃。

## Blocked by

- #74
- #75
- #76
