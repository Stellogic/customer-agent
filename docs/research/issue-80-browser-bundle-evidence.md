# Issue #80：真实浏览器验收与生产 bundle 门禁的官方依据

> 调研日期：2026-08-22
>
> 对应实施票：[GitHub Issue #80](https://github.com/Stellogic/customer-agent/issues/80)
>
> 证据范围：仅使用 Playwright、Vite 的官方文档、官方源码、npm 官方包元数据和 Microsoft Artifact Registry 官方标签清单。
> 结论边界：本文给出实施所需的依赖、容器、等待、隔离和测量依据；没有把官方默认 warning 推断成项目已经具备的硬门禁，也没有把静态资料核对写成运行验证。

## 结论

1. **真实浏览器全栈验收应使用 `@playwright/test`，并让 npm 包与浏览器二进制来自同一精确版本。** Playwright 每个版本对应特定浏览器 revision；可使用同版官方镜像，也可按官方“build your own image”路径在锁定的 Node 基础镜像中执行 `playwright install --with-deps`。[Browsers](https://playwright.dev/docs/browsers) / [Docker](https://playwright.dev/docs/docker)
2. **截至调研日可采用的稳定候选是 `@playwright/test@1.62.1` 与 `mcr.microsoft.com/playwright:v1.62.1-noble`。** npm 官方元数据把 `1.62.1` 标为 `latest`，Microsoft Artifact Registry 官方清单同时存在精确的 `v1.62.1-noble` 标签；两者仍须在 lockfile、镜像拉取和实际验收中共同验证。[npm：`@playwright/test`](https://www.npmjs.com/package/%40playwright/test?activeTab=versions) / [MCR tags API](https://mcr.microsoft.com/v2/playwright/tags/list)
3. **Docker 默认只应访问本项目受控页面。** 官方镜像用于测试和开发，不建议访问不可信网站；可信 E2E 可以按官方说明使用 root，但这会禁用 Chromium sandbox。若输入会把浏览器带到不可信页面，则应改用非 root 用户与官方 seccomp profile，不能沿用 root 便利模式。[Playwright Docker](https://playwright.dev/docs/docker#usage)
4. **等待应基于可观察条件，隔离应覆盖浏览器态和后端共享态。** Locator、web-first assertion 和 `webServer.url` 承担条件等待；每个测试默认获得新的 BrowserContext，但数据库记录、端口、容器名和输出文件仍须唯一化或显式串行，不能靠固定 sleep 或测试顺序。[Auto-waiting](https://playwright.dev/docs/actionability) / [Web server](https://playwright.dev/docs/test-webserver) / [Isolation](https://playwright.dev/docs/browser-contexts) / [Parallelism](https://playwright.dev/docs/test-parallel#avoiding-shared-state-in-parallel-tests)
5. **bundle 门禁必须测量 `vite build` 的生产产物。** Vite 默认报告每个输出文件的原始大小和 gzip 大小，但 `chunkSizeWarningLimit` 只是 warning 阈值；若 Issue #80 要求超预算失败，项目必须在构建后自行统计并以非零退出码执行硬断言。[Building for Production](https://vite.dev/guide/build) / [Build Options](https://vite.dev/config/build-options.html#build-reportcompressedsize)

## 1. Playwright 版本、浏览器与镜像

### 1.0 依赖评估（正式决策见 [ADR 0003](../decisions/0003-playwright-browser-acceptance.md)）

| 维度 | 结论与证据 |
|---|---|
| 自然适配 | 前端已经使用 TypeScript/Vite/Vitest；`@playwright/test` 提供同语言测试运行器、隔离 BrowserContext、Locator 自动等待、网络响应观察和 trace，能够直接表达 Issue #80 的真实登录、跨标签与 SSE 验收。 |
| 许可证 | Playwright 仓库使用 [Apache License 2.0](https://github.com/microsoft/playwright/blob/main/LICENSE)，允许本项目在遵守许可证与 NOTICE 条件下用于测试依赖。 |
| 维护状态 | Microsoft 官方仓库持续发布带浏览器 revision 的版本；本票核对 npm `latest`、MCR 精确标签与[官方 releases](https://github.com/microsoft/playwright/releases)，不使用无人维护 fork。 |
| 兼容与运维 | 精确固定 `@playwright/test@1.62.1`、Node 24.19.0 与由同版包下载的 Chromium；一次性容器承担系统库和浏览器安装，不污染 Spring/React 生产镜像。代价是冷构建下载较大、代理波动时耗时明显，因此只对构建下载做有界重试，浏览器用例零重试。 |
| 安全 | 浏览器只访问隔离 Compose 中本项目自建 HTTPS 站点；数据库超级用户仅注入一次性 browser-acceptance 容器，用于制造撤权竞态，不进入前端 bundle、普通 frontend 容器或生产服务，也不暴露 HTTP 测试后门。 |
| 锁定成本 | 测试 API 属于 Playwright；每次升级必须同步 npm 包、浏览器 revision、系统依赖与容器缓存并重跑全套验收。业务协议断言仍使用标准 HTTP/DOM，可迁移，但 trace、locator 与 BrowserContext 驱动代码需要改写。 |

**被拒方案。** Selenium WebDriver 是 W3C 标准、覆盖主流浏览器，但官方入门仍要求组合语言绑定、浏览器与相应 driver；对当前 TypeScript 单仓会增加驱动版本和等待/测试运行器的运维面，本票不需要其 Grid 或多语言优势，因此不引入。[Selenium WebDriver](https://www.selenium.dev/documentation/webdriver/) / [Getting started](https://www.selenium.dev/documentation/webdriver/getting_started/) 现有 Vitest/jsdom 保留为快速组件回归，但它不启动真实浏览器、Nginx、Spring 与 PostgreSQL，不能单独满足 Issue #80。手写 Chromium/CDP 驱动会重复实现隔离、自动等待、trace 与浏览器版本协调，维护成本高于引入一个成熟测试依赖，也予以拒绝。

**决策。** 在 Issue #80 验收切片引入精确版本 `@playwright/test@1.62.1`，只作为 devDependency 和隔离浏览器容器使用；后续跨浏览器或版本升级另行形成有证据的变更，不自动扩大本票范围。

### 1.1 三者必须来自同一精确版本

- Playwright 官方说明每个版本只支持特定浏览器二进制；更新 Playwright 后通常需要重新执行 `npx playwright install`。因此，复用旧浏览器缓存并不能证明新包可运行。[Browsers](https://playwright.dev/docs/browsers)
- 官方 Docker 镜像包含浏览器和浏览器系统依赖，**不包含项目使用的 Playwright npm 包**；项目仍需单独安装依赖。[Docker introduction](https://playwright.dev/docs/docker#introduction)
- 官方建议镜像固定到具体版本，并明确指出镜像版本与项目/测试版本不匹配时，Playwright 无法定位浏览器可执行文件；远程 Playwright Server 模式同样要求测试端与容器端版本一致。[Image tags](https://playwright.dev/docs/docker#image-tags) / [Connecting to the server](https://playwright.dev/docs/docker#connecting-to-the-server)
- 截至 2026-08-22，npm 官方包页把 `1.62.1` 标为稳定 `latest`；MCR 官方标签清单存在 `v1.62.1-noble`、`v1.62.1-jammy`、`v1.62.1-resolute` 等精确标签。因此 Issue #80 可以把 `1.62.1` 作为同版候选，而不使用 `latest`、`next` 或只固定 major/minor。[npm versions](https://www.npmjs.com/package/%40playwright/test?activeTab=versions) / [MCR tags API](https://mcr.microsoft.com/v2/playwright/tags/list)

首选的官方镜像版本约束是：

```text
frontend/package.json + package-lock.json: @playwright/test = 1.62.1
browser image:                         mcr.microsoft.com/playwright:v1.62.1-noble
```

若 MCR 在当前网络不可达，可采用官方自建镜像路径：精确锁定 `@playwright/test`，执行该版本随包提供的 `npx playwright install-deps chromium` 与 `npx playwright install chromium`，并在真实验收中验证。升级时必须重新安装对应浏览器并重跑验收，不能复用不明版本的浏览器缓存。

### 1.2 浏览器覆盖边界

Playwright Test 官方包同时提供 Chromium、Firefox、WebKit 驱动能力，并把每个测试置于新的浏览器上下文。[npm package metadata](https://www.npmjs.com/package/%40playwright/test) 对本票若只把 Chromium 作为必需的全栈验收浏览器，应明确记录这是项目门禁范围，而不是声称已经验证所有 Playwright 浏览器；后续增加 Firefox/WebKit 时仍需匹配同一 Playwright 版本的对应二进制。

## 2. Docker 安全与运行参数

### 2.1 信任边界与运行用户

- 官方将 Playwright 镜像定位为测试/开发镜像，并明确不建议用它访问不可信网站。[Docker usage](https://playwright.dev/docs/docker#usage)
- 镜像默认以 root 启动浏览器，此时 Chromium sandbox 被禁用。官方允许可信代码、可信站点的 E2E 为简化运行而使用 root；这不是对任意 URL 的安全背书。[End-to-end tests](https://playwright.dev/docs/docker#end-to-end-tests)
- 对爬取或不可信页面，官方建议创建独立用户，并使用 `--user pwuser --security-opt seccomp=seccomp_profile.json`；该 profile 在默认 Docker seccomp 基础上额外允许 `clone`、`setns`、`unshare`，使 Chromium sandbox 能工作。[Crawling and scraping](https://playwright.dev/docs/docker#crawling-and-scraping) / [官方 seccomp profile](https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json)

因此，本项目 root 模式的前提必须是验收只访问自己启动、自己控制的 Spring/React 页面，且测试数据不能诱导浏览器跳转到任意外部 URL。若该前提不成立，应切换到非 root + seccomp，而不是继续扩大容器权限。

### 2.2 推荐参数及边界

| 参数 | 官方依据 | 本项目使用边界 |
|---|---|---|
| `--rm` | 官方示例均在一次性运行后移除容器。[Docker](https://playwright.dev/docs/docker) | 验收容器应是临时资源，失败路径也要清理；持久业务数据不应放入该容器。 |
| `--init` | 官方推荐避免 PID 1 特殊处理造成僵尸进程。[Recommended Docker Configuration](https://playwright.dev/docs/docker#recommended-docker-configuration) | 默认启用。 |
| `--ipc=host` | 官方建议 Chromium 使用；否则可能因共享内存不足而崩溃。[Recommended Docker Configuration](https://playwright.dev/docs/docker#recommended-docker-configuration) | Chromium 容器运行时启用，并将其视为稳定性参数而非应用授权。 |
| `--cap-add=SYS_ADMIN` | 官方只建议在本地开发遇到异常 Chromium 启动错误时尝试。[Recommended Docker Configuration](https://playwright.dev/docs/docker#recommended-docker-configuration) | 不作为 CI/规范化验收默认值；只有复现并确认需要时临时诊断。 |
| `--add-host=hostmachine:host-gateway` | 官方远程 server 示例用它让容器访问宿主本地服务，并要求测试使用 `hostmachine` 而非容器内的 `localhost`。[Network Configuration](https://playwright.dev/docs/docker#network-configuration) | 仅当浏览器容器确需访问宿主端口时使用；若服务都在同一 Docker network，则应使用明确服务名。 |

`--ipc=host` 和 host-gateway 都扩大容器与宿主的共享面，因此命令必须保持目标服务、网络和临时容器名称明确；它们不能替代应用层鉴权，也不授权清理共享 Docker 资源。

## 3. 等待、ready 判定与隔离

### 3.1 不使用固定 sleep 表达业务完成

- Locator action 会自动等待唯一定位、可见、稳定、能接收事件、启用等 actionability 条件；相关条件在超时内不能满足才失败。[Auto-waiting](https://playwright.dev/docs/actionability)
- Playwright 的 web-first assertions 会自动重试，官方最佳实践推荐 `await expect(locator).toBeVisible()` 等形式，而不是先调用 `isVisible()` 再做立即断言。[Best Practices](https://playwright.dev/docs/best-practices#use-web-first-assertions)
- 应优先按用户可见角色、标签、文本或显式 test id 定位，不依赖易变的 CSS/DOM 结构。[Locators](https://playwright.dev/docs/locators)

因此，页面交互和异步结果等待应表达为“按钮可操作”“状态文本最终出现”“URL 变为目标值”等条件；固定 `waitForTimeout` 只能用于确有时间语义的测试，不应承担一般就绪判定。

### 3.2 服务启动需要独立的 bounded readiness

Playwright `webServer` 支持先启动本地服务，再等待 `url` 可用；URL 返回 2xx、3xx、400、401、402 或 403 时会被视为 ready，默认启动超时是 60 秒。官方配置示例通常让 `reuseExistingServer` 在本地为 true、CI 为 false。[Web server](https://playwright.dev/docs/test-webserver)

对本项目的含义是：

1. readiness URL 应只证明进程已可接受请求，不应把一次页面 200 当作完整业务验收；登录、授权和业务结果仍由测试步骤断言。
2. CI/规范化门禁应禁用复用已有服务，避免误连上一次残留进程；端口冲突应明确失败。
3. 服务启动、单个测试、expect 和整个验收都应有有限超时。Playwright 默认 test timeout 为 30 秒、expect timeout 为 5 秒，并支持 global timeout 限制整套测试运行。[Timeouts](https://playwright.dev/docs/test-timeouts)

### 3.3 浏览器上下文隔离不等于全栈数据隔离

- Playwright Test 默认每个测试创建新的 BrowserContext，隔离 cookies、localStorage 和 sessionStorage。官方指出“测试后清理”容易漏掉状态，甚至有些状态无法清理，因此优先从全新上下文开始。[Isolation](https://playwright.dev/docs/browser-contexts)
- 并行 worker 是独立 OS 进程和独立浏览器，但数据库记录、服务端状态和共享文件仍在上下文之外。官方建议后端记录使用 `testInfo.testId` 派生唯一标识，输出文件使用 `testInfo.outputPath()`，测试不得依赖另一测试的副作用。[Parallelism](https://playwright.dev/docs/test-parallel#avoiding-shared-state-in-parallel-tests)
- 官方不推荐用 serial 依赖测试顺序；若共享资源确实无法并行，可以把 worker 限制为 1，但仍应让每个测试自行建立前置状态。[Parallelism](https://playwright.dev/docs/test-parallel#serial-mode)
- 认证状态文件可能包含足以冒充用户的 cookie 和 header，官方强烈反对把它提交到仓库。[Authentication](https://playwright.dev/docs/auth#core-concepts)

Issue #80 的验收资源应使用每次运行唯一的业务标识、容器/网络名和输出目录，并在失败路径执行精确清理。BrowserContext 解决的是浏览器态串扰，不解决数据库、Docker、端口和服务端会话的共享冲突。

## 4. Vite production bundle 与 chunk 测量

### 4.1 测量对象必须是 production build

Vite 官方定义 `vite build` 为 production build：默认以 `<root>/index.html` 为入口并生成适合静态托管的应用 bundle。[Building for Production](https://vite.dev/guide/build) 开发服务器的模块请求数、预构建缓存和源码尺寸不等于最终生产产物，因此 bundle 门禁只能测 `vite build` 成功后的 `dist` 文件。

当前 Vite 8 使用 `build.rolldownOptions` 自定义底层构建，旧名 `build.rollupOptions` 已是 deprecated alias；chunk 拆分可通过 `build.rolldownOptions.output.codeSplitting` 调整。[Customizing the Build](https://vite.dev/guide/build#customizing-the-build) / [Chunking Strategy](https://vite.dev/guide/build#chunking-strategy) 本票若只要求测量，不应为了压低单 chunk 数字而先手工拆包；先记录真实入口闭包和最大 chunk，再针对实际问题决定策略。

### 4.2 官方提供的两种尺寸语义

- `build.reportCompressedSize` 默认 `true`，构建时报告 gzip 压缩大小；关闭它只是减少大型项目的构建耗时。[`build.reportCompressedSize`](https://vite.dev/config/build-options.html#build-reportcompressedsize)
- `build.chunkSizeWarningLimit` 默认 500 kB，并与 **未压缩** JavaScript chunk 比较；官方解释未压缩 JS 大小本身与执行时间相关。[`build.chunkSizeWarningLimit`](https://vite.dev/config/build-options.html#build-chunksizewarninglimit)
- Vite 官方源码同样把默认值定义为 `reportCompressedSize: true` 和 `chunkSizeWarningLimit: 500`，二者分别只是 boolean 与 number 配置。[Vite build defaults](https://github.com/vitejs/vite/blob/main/packages/vite/src/node/build.ts)

所以建议门禁同时记录：

1. 每个 JavaScript chunk 的未压缩 bytes，和最大单 chunk；
2. 每个 chunk 的 gzip bytes；
3. HTML 入口静态可达的 JS chunk 集合总量；
4. 所有延迟加载 dynamic chunk，单独列出而不混入首屏静态闭包。

未压缩数与 Vite warning 的语义一致，gzip 数与默认 build report 一致；两者都应保留，不能用 gzip 达标掩盖执行成本，也不能把全站所有懒加载 chunk 简单相加冒充首屏成本。

### 4.3 稳定识别 entry 与 dynamic chunk

启用 `build.manifest: true` 会生成 `.vite/manifest.json`，把非 hash 源名映射到 hash 产物；官方后端集成文档给出的 manifest 结构包含 `isEntry`、静态 `imports` 和 `dynamicImports`。[`build.manifest`](https://vite.dev/config/build-options.html#build-manifest) / [Backend Integration](https://vite.dev/guide/backend-integration.html)

Vite 官方 Features 文档说明动态 `import()` 在构建时会拆为独立 chunk；`import.meta.glob` 默认也是 lazy，并以动态 import 形成独立 chunk。[Dynamic Import](https://vite.dev/guide/features.html#dynamic-import) 因此可以从 manifest 的 HTML entry 开始只递归 `imports` 得到入口静态闭包，再另行列出 `dynamicImports`；实际 bytes 仍以 `dist` 中对应文件为准。

### 4.4 warning 不是硬门禁

`chunkSizeWarningLimit` 的官方定义是“产生 chunk size warning 的阈值”，没有承诺超限后 `vite build` 非零退出。[Build Options](https://vite.dev/config/build-options.html#build-chunksizewarninglimit) 因此，Issue #80 若要求“超过预算必须失败”，实现应在 production build 后读取 manifest/输出文件、计算上述指标并显式非零退出。把 warning limit 调高只会隐藏问题，把它调低也不能代替可测试的 CI 断言。

## 5. 实施与验证边界

Issue #80 可以据此采用以下最小门槛：

1. 精确安装 `@playwright/test@1.62.1` 并提交 lockfile；优先使用同版 MCR 镜像，网络不可达时使用锁定 Node 镜像并由同一 npm 包安装 Chromium 与系统依赖，禁止 floating tag 和不明浏览器缓存。
2. 真实验收只访问本项目受控页面；运行命令默认包含 `--rm --init --ipc=host`，不默认增加 `SYS_ADMIN`。
3. 使用 locator、web-first assertion 和有界的服务 readiness；CI 不复用既有服务。
4. 每次运行唯一化浏览器外部状态，并对失败路径做精确、可验证的临时资源清理。
5. 先执行 `vite build`，再对实际 `dist` 文件统计未压缩和 gzip bytes；用 manifest 区分入口静态闭包与 dynamic chunks。
6. bundle 超预算必须由专用断言非零退出；Vite 自带 warning 仅作为诊断信号。

## 验证范围与限制

- 本文核对了 2026-08-22 可访问的 Playwright/Vite 官方文档、官方源码、npm 官方包元数据和 MCR 官方标签清单。
- 实施阶段已精确安装 `@playwright/test@1.62.1`，并在 `node:24.19.0-bookworm-slim` 中通过该包安装 Chromium 与系统依赖；MCR 拉取因当前网络代理出现 EOF，未将其误判为镜像不存在。
- 实施阶段已启动 Chromium 并运行真实 React/Spring/PostgreSQL 验收，也已运行 `vite build`；最终运行结果和 bundle 数值记录在 `docs/verification/issue-80-acceptance.md`。
