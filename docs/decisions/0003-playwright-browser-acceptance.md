# ADR 0003：Playwright 真实浏览器验收

## 状态

已接受，对应 #80；浏览器安全分组与 worker 决策由 #182 补充。

## 背景

Issue #80 要求以真实浏览器验证 React、Spring 与 PostgreSQL 的身份、资源授权、SSE 撤权和恢复边界，并对 Vite production bundle 形成可失败的结构门禁。既有 Vitest/jsdom 适合快速组件回归，但不会启动真实浏览器和全栈服务，无法单独证明这些行为。

## 决策

- 精确锁定 `@playwright/test@1.62.1` 为前端 devDependency，提交 npm lockfile，并由同版包安装对应 Chromium revision。
- 浏览器及其系统依赖只存在于一次性 `browser-acceptance` 镜像；普通 React/Nginx 发布镜像不包含 Playwright、浏览器或 PostgreSQL 客户端。
- 验收保持零用例重试。#182 起，显式清单中经静态约束证明不创建 Session、不写共享数据库的两个匿名 UI 文件使用 `workers=2` 连续资格运行三次；任一次失败立即终止，不作为失败后的用例重试。Session、SSE、数据库、审批/竞态、重启恢复及其他状态型文件仍固定 `workers=1`。镜像下载/构建允许最多五次有界重试。每次运行使用唯一 Compose project、端口、镜像标签和专用卷，并精确回读清理结果。
- Chromium 只访问隔离 Compose 内本项目自建 HTTPS 页面。数据库超级用户仅注入一次性验收容器，用于制造 assignment、lease 与版本撤权竞态，不进入前端 bundle 或生产服务，也不增加 HTTP 测试后门。
- 版本升级必须同步 npm 包、浏览器 revision、系统依赖和容器缓存，并重跑完整规范化门禁；Firefox/WebKit 不在本票已验证范围内。

## 证据与取舍

- Playwright 提供 TypeScript 测试运行器、隔离 BrowserContext、Locator 自动等待、网络响应观察和 trace，与当前 TypeScript/Vite 工程自然适配。[官方浏览器文档](https://playwright.dev/docs/browsers) / [官方 Docker 文档](https://playwright.dev/docs/docker)
- Playwright 使用 [Apache License 2.0](https://github.com/microsoft/playwright/blob/main/LICENSE)，官方仓库持续发布带浏览器 revision 的版本。[官方 releases](https://github.com/microsoft/playwright/releases)
- 精确版本降低包与浏览器不匹配风险，但冷构建下载体积和代理波动成本明显；因此只重试外部下载/构建，不用重试掩盖产品测试不稳定。
- 详细版本、容器安全、等待、隔离和 bundle 测量依据记录在[调研文档](../research/issue-80-browser-bundle-evidence.md)，实际用例和数值记录在[验收证据](../verification/issue-80-acceptance.md)。

## 被否决的方案

- Selenium WebDriver：标准成熟且覆盖主流浏览器，但需要组合语言绑定、浏览器与 driver；当前切片不需要 Grid 或多语言优势，引入后运维面大于 Playwright。[Selenium WebDriver](https://www.selenium.dev/documentation/webdriver/) / [官方入门](https://www.selenium.dev/documentation/webdriver/getting_started/)
- 仅使用 Vitest/jsdom：保留为快速组件测试，但不能证明真实 Cookie、Nginx/Spring、跨标签和 SSE 网络行为。
- 手写 Chromium/CDP 驱动：会重复实现隔离、自动等待、trace 和浏览器版本协调，维护成本高于成熟测试依赖。

## 影响

规范化检查会增加浏览器镜像冷构建和约 1 分钟 Session 到期场景的耗时；换来的是身份与授权边界进入真实全栈门禁。Playwright API 构成测试代码锁定点，但业务断言仍基于标准 HTTP、Cookie、DOM 与 SSE，未来迁移不需要修改生产协议。
