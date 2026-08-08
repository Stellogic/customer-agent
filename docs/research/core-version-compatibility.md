# 核心技术版本与兼容基线

> 调研日期：2026-08-09  
> 对应决策票：[GitHub Issue #9](https://github.com/Stellogic/customer-agent/issues/9)  
> 证据范围：仅采用官方文档、官方发布页、官方仓库和 PyPI 官方项目元数据。  
> 结论边界：本文核对的是**发布状态、声明的运行条件和依赖元数据**。尚未在本机创建项目、解析完整锁文件、构建镜像或运行跨服务集成测试，因此不能把推荐组合称为“已运行验证”。

## 结论摘要

建议把第一轮最小构建基线定为：

| 层次 | 建议基线 | 结论性质 |
|---|---|---|
| React 前端 | React `19.2.7`、Node.js `24.19.0` LTS、TypeScript `6.0.3`，用 Vite 8.x 的 React 模板起步 | 版本均已正式发布；组合仍需最小构建验证 |
| Spring 后端 | Spring Boot `4.1.0`、Java `25` LTS（当前补丁 `25.0.4`） | Spring 官方确认 Boot 4.1 支持 Java 17–26；Java 25 为 LTS |
| Agent 服务 | Python `3.13.15`、LangGraph `1.2.10` | LangGraph 官方元数据明确支持 Python >=3.10，并显式分类到 3.13；选择 3.13 是兼容性优先建议 |
| Checkpointer | `langgraph-checkpoint-postgres==3.1.2`，解析到 `langgraph-checkpoint` 4.x；PostgreSQL `18.4` | Python 包依赖区间官方可核对；数据库主版本没有官方兼容矩阵，必须实测 |

这里没有把“绝对最新”机械地等同于“项目基线”：Java 当前功能版为 26，但 25 是 LTS；Python 当前功能版为 3.14.7，但 LangGraph 1.2.10 的 PyPI 分类器只显式列到 3.13。对个人项目第一版，优先选择有更直接兼容证据的 Java 25 与 Python 3.13。

## 1. 前端基线

### 1.1 React

**官方确认**

- React 官方版本页将 `19.2` 标为最新版本，并列出最新补丁 `19.2.7`（2026 年 6 月）。[React Versions](https://react.dev/versions)
- React 19.2 已正式发布；不是 RC、beta 或实验通道。[React 19.2 发布说明](https://react.dev/blog/2025/10/01/react-19-2)

**合理建议**

- 新项目直接采用 `react@19.2.7` 与同补丁线的 `react-dom@19.2.7`，不要回退到 React 18，也不要采用 canary。
- React 官方已弃用 Create React App，并建议新项目选择框架或 Vite、Parcel、Rsbuild 一类构建工具；本项目是独立 React 展示层，使用 Vite 与既定架构相符。[Sunsetting Create React App](https://react.dev/blog/2025/02/14/sunsetting-create-react-app)

**尚需本机验证**

- `@types/react`、测试库、路由库和 UI 依赖对 React 19.2 的 peer dependency 是否无冲突。
- 开发构建、生产构建、基础组件测试和浏览器运行是否通过。

### 1.2 Node.js 与 Vite

**官方确认**

- Node.js 官方发布页显示：`24.19.0` 是 Latest LTS，24.x 代号 Krypton；26.x 是 Current。Node 官方明确建议生产应用只使用 Active LTS 或 Maintenance LTS。[Node.js Releases](https://nodejs.org/en/about/previous-releases)
- Vite 8 已正式发布，要求 Node.js `20.19+` 或 `22.12+`；因此 Node 24.19.0 高于其最低版本要求。[Vite 8 发布说明](https://vite.dev/blog/announcing-vite8)
- Vite 官方发布策略说明：非 LTS Node 版本不进入其 CI 测试；这进一步支持使用 Node 24 LTS，而不是 Node 26 Current。[Vite Releases](https://vite.dev/releases)

**合理建议**

- 固定 Node 主次版本为 `24.19.x`，在仓库中用 `.nvmrc`、`.node-version` 或 `package.json#engines` 表达；具体方式留给实现票决定。
- 用 Vite 8.x 官方 React + TypeScript 模板生成最小前端；Vite 当前已进入 8.1 版本线，但具体补丁应在创建项目当天由包管理器解析后写入锁文件，而不是在 Wayfinder 文档中猜测。[Vite Blog](https://vite.dev/blog)

**尚需本机验证**

- Windows 本机的 Node 24、包管理器和 Vite 8 原生依赖能否安装。
- 依赖安装后实际锁定的 Vite、`@vitejs/plugin-react` 及 Rolldown 原生包版本。

### 1.3 TypeScript

**官方确认**

- TypeScript 官方仓库把 `6.0.3` 标为 Latest，并明确它是 Stable 修复版。[TypeScript 6.0.3](https://github.com/microsoft/TypeScript/releases/tag/v6.0.3)
- TypeScript 6.0 官方说明称它保持对 5.9 的 API 兼容，但包含默认值变化、弃用和破坏性调整，例如默认启用 `strict`、`rootDir` 行为变化等。[TypeScript 6.0 Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- Vite 官方说明其 TypeScript 类型可能在 minor 版本变化，并建议 TypeScript 用户锁定 Vite 当前 minor、人工升级。[Vite Releases](https://vite.dev/releases)

**合理建议**

- 绿地项目可以从 `typescript@6.0.3` 开始，并显式保留 `strict: true`；由于 Vite 8 与 TypeScript 6 的组合没有一张官方端到端兼容矩阵，必须以实际模板构建结果为准。
- 锁文件中固定精确版本；自动依赖更新应分批进行，避免 React、Vite 和 TypeScript 同时跨 minor。

**尚需本机验证**

- Vite React 模板、React 类型声明、ESLint 插件与 TypeScript 6.0.3 的类型检查和生产构建。

## 2. Spring Boot 与 Java 基线

### 2.1 Spring Boot

**官方确认**

- Spring 官方项目页当前显示 Spring Boot `4.1.0`。[Spring Boot 项目页](https://spring.io/projects/spring-boot/)
- Spring 官方公告确认 `4.1.0` 已在 2026-06-10 正式发布到 Maven Central。[Spring Boot 4.1.0 available now](https://spring.io/blog/2026/06/10/spring-boot-4/)
- Spring Boot 4.1.0 系统要求：最低 Java 17，最高兼容 Java 26；要求 Spring Framework 7.0.8+；显式支持 Maven 3.6.3+，或 Gradle 8.14+/9.x。[Spring Boot System Requirements](https://docs.spring.io/spring-boot/system-requirements.html)

**合理建议**

- 第一版采用 `org.springframework.boot:4.1.0`，依赖版本尽量由 Spring Boot BOM 管理，不自行覆盖 Spring Framework、Jackson、Hibernate 等受管依赖。
- Maven 与 Gradle 都官方支持；具体构建工具不属于本票结论。

**尚需本机验证**

- Spring Initializr 生成项目后能否在选定 JDK 和构建工具上完成测试、打包与启动。
- 计划采用的 Spring Security、Data/JPA、Validation、Flyway 和 PostgreSQL 驱动是否均由 4.1 BOM 正常解析。

### 2.2 Java

**官方确认**

- OpenJDK 25 已于 2025-09-16 GA；OpenJDK 页面说明多数厂商会把它作为 LTS。[OpenJDK 25](https://openjdk.org/projects/jdk/25/)
- Oracle 支持路线图明确把 Java 25 列为 LTS，Java 26 列为非 LTS；下一计划 LTS 是 Java 29。[Oracle Java SE Support Roadmap](https://www.oracle.com/java/technologies/java-se-support-roadmap.html)
- Oracle 当前 Java 下载信息显示 Java SE `25.0.4` 是最新的 Java 25 更新。[Oracle Java SE](https://www.oracle.com/java/technologies/java-se-glance.html)
- Spring Boot 4.1 官方兼容 Java 17–26，因此 Java 25 位于明确支持区间内。[Spring Boot System Requirements](https://docs.spring.io/spring-boot/system-requirements.html)

**合理建议**

- 项目编译与运行基线采用 Java 25 LTS；不要仅因 Java 26 数字更大而选择非 LTS。
- 锁定语言级别 25，避免使用 Java 26 特性，从而保持与 LTS 工具链一致。

**尚需本机验证**

- 本机实际 JDK 发行版、`java -version`、构建工具识别的 toolchain，以及容器镜像是否一致。

## 3. Python、LangGraph 与 checkpointer 基线

### 3.1 Python

**官方确认**

- Python `3.14.7` 是 2026-08-05 发布的当前 3.14 维护版。[Python 3.14.7](https://www.python.org/downloads/release/python-3147/)
- Python `3.13.15` 同日发布，仍是 3.13 的维护版。[Python 3.13.15](https://www.python.org/downloads/release/python-31315/)
- LangGraph 的安装文档和发布策略均写明 Python `3.10+`；LangGraph 1.2.10 PyPI 元数据也声明 `Requires-Python >=3.10`，并显式列出 Python 3.10、3.11、3.12、3.13 分类器。[LangGraph Install](https://docs.langchain.com/oss/python/langgraph/install) / [LangGraph 1.2.10 PyPI](https://pypi.org/project/langgraph/1.2.10/)

**合理建议**

- 第一版采用 Python `3.13.15`。原因不是 3.14 不受支持，而是 LangGraph 当前项目元数据只显式列到 3.13，且官方发布 wheel 是纯 Python；3.13 有更直接的生态兼容证据。
- Python 3.14.7 可作为后续兼容性 CI 目标；在实际安装、测试全部通过前，不把它写成主基线。

**尚需本机验证**

- 在 Python 3.13.15 下解析并安装全部依赖；尤其核对模型提供商 SDK、`psycopg` 二进制包和测试工具。
- 如果希望直接使用 3.14.7，必须额外跑相同测试矩阵，不能仅凭 `Requires-Python >=3.10` 推断所有传递依赖均已适配。

### 3.2 LangGraph

**官方确认**

- PyPI 显示 `langgraph==1.2.10` 是 2026-07-28 的最新正式版，Development Status 为 Production/Stable，要求 Python >=3.10。[LangGraph PyPI](https://pypi.org/project/langgraph/)
- LangGraph 1.2.10 的官方包元数据要求 `langgraph-checkpoint>=4.1.0,<5.0.0`，同时约束 `langchain-core<2,>=1.4.7`、`langgraph-prebuilt<1.2.0,>=1.1.0` 和 `langgraph-sdk<0.5.0,>=0.4.2`。[LangGraph 1.2.10 JSON metadata](https://pypi.org/pypi/langgraph/1.2.10/json)
- LangGraph 1.x 按官方政策属于当前 LTS 主版本，遵循语义化版本；1.0 在 2.0 发布前保持 Active。[LangChain/LangGraph Versioning](https://docs.langchain.com/oss/python/versioning)

**合理建议**

- 第一轮 spike 固定 `langgraph==1.2.10`，使用 lock 文件完整记录传递依赖；不要只写 `langgraph>=1`。
- 升级时先阅读 release notes，并重新执行 interrupt、resume、stream、checkpoint 恢复和幂等测试。

**尚需本机验证**

- 最小图在进程重启后能从 PostgreSQL checkpoint 恢复。
- interrupt 节点、`Command(resume=...)`、异步流和异常恢复在固定锁文件下的真实行为。

### 3.3 PostgreSQL checkpointer

**官方确认**

- LangGraph 持久化文档将 `langgraph-checkpoint-postgres` 描述为用于生产的高级 Postgres checkpointer，并说明 PostgreSQL/SQLite 的同步与异步实现。[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- PyPI 显示 `langgraph-checkpoint-postgres==3.1.2` 是 2026-08-07 的最新正式版，要求 Python >=3.10；首次使用必须执行 `.setup()`，手工连接还必须正确配置 `autocommit` 和 `row_factory`。[Checkpoint Postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/)
- 该包官方 `pyproject.toml` 约束 `langgraph-checkpoint>=4.1.0,<5.0.0`、`psycopg>=3.2.0`、`psycopg-pool>=3.2.0`。[官方仓库 pyproject.toml](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/pyproject.toml)
- `langgraph==1.2.10` 与 `langgraph-checkpoint-postgres==3.1.2` 对 `langgraph-checkpoint` 的依赖区间相同，都是 `>=4.1.0,<5.0.0`；官方 PyPI 当前最新 `langgraph-checkpoint` 为 `4.2.0`。因此三者在**声明的包依赖区间**上相容。[LangGraph metadata](https://pypi.org/pypi/langgraph/1.2.10/json) / [Checkpoint PyPI](https://pypi.org/project/langgraph-checkpoint/)
- PostgreSQL 官方当前稳定主版本是 18，当前 minor 为 `18.4`；19 仍为 beta。PostgreSQL 官方建议始终运行所选主版本的当前 minor。[PostgreSQL Versioning Policy](https://www.postgresql.org/support/versioning/)

**合理建议**

- 生产式 MVP 采用 `langgraph-checkpoint-postgres==3.1.2`，让解析器在允许区间内选定 `langgraph-checkpoint==4.2.0`，随后把整个解析结果写入 lock 文件。
- 数据库可从 PostgreSQL `18.4` 开始；Spring 业务数据库与 LangGraph checkpoint 可以部署在同一 PostgreSQL 实例的不同 database/schema，但这只是减少本地基础设施的建议，不表示它们共享事务或数据所有权。
- 新应用按 checkpointer 官方安全提示启用 `LANGGRAPH_STRICT_MSGPACK=true`，或显式限制允许反序列化的模块。[Checkpoint Postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/)

**尚需本机验证**

- `langgraph-checkpoint-postgres 3.1.2` 没有公布 PostgreSQL 18 的主版本兼容矩阵；必须用 PostgreSQL 18.4 实际执行 `.setup()`、写入、读取、列举、删除、并发和重启恢复测试。
- 需要验证同步还是 `AsyncPostgresSaver` 更适合最终 Agent 服务，并验证连接池关闭、迁移重复执行及失败恢复。
- checkpoint 表结构应由官方 `.setup()` 管理；在没有源码与迁移审计前，不应让 Spring 直接读写这些内部表。

## 4. 跨技术栈兼容关系

这三个运行时不会加载到同一个进程，因此不存在一张把 React、Java 与 Python 逐版本配对的官方兼容矩阵。真正需要验证的关系如下：

| 关系 | 已有证据 | 当前判断 |
|---|---|---|
| React 19.2.7 ↔ Node 24.19 ↔ Vite 8 | Vite 8 的 Node 最低要求低于 Node 24；React 19.2 和 Vite 8 都是稳定版 | 合理组合，需实际 scaffold/build |
| TypeScript 6.0.3 ↔ Vite/React 工具链 | TypeScript 6 稳定；Vite 提醒 TS 类型可随 minor 变化 | 无官方端到端矩阵，需 `tsc` 与生产构建 |
| Spring Boot 4.1 ↔ Java 25 | Spring 官方明确支持 Java 17–26 | 官方确认兼容 |
| LangGraph 1.2.10 ↔ Python 3.13 | PyPI 要求 >=3.10，并显式列出 3.13 | 官方元数据支持；仍需安装/运行 |
| LangGraph 1.2.10 ↔ checkpoint-postgres 3.1.2 | 两者对 `langgraph-checkpoint` 的区间交集为完整 4.x `>=4.1,<5` | 包元数据确认相容；运行行为需测试 |
| checkpoint-postgres 3.1.2 ↔ PostgreSQL 18.4 | 官方称该组件支持 Postgres，但未列数据库主版本矩阵 | 合理建议，必须集成验证 |
| React ↔ Spring ↔ LangGraph | 独立服务间依赖 HTTP/流式协议、认证、超时和错误契约 | 与语言版本无直接二进制关系；需契约和端到端测试 |

## 5. 建议写入后续实现票的最小验证门槛

1. **前端：** 在 Node 24.19.x 下创建 Vite React + TypeScript 工程，执行依赖安装、类型检查、单元测试和生产构建。
2. **Spring：** 用 Java 25 创建 Spring Boot 4.1.0 最小工程，执行测试、打包和启动，确认 PostgreSQL/Flyway/Security 依赖解析。
3. **Agent：** 在 Python 3.13.15 下安装精确锁定的 LangGraph/checkpointer 组合，运行一个固定图。
4. **持久化：** PostgreSQL 18.4 中执行 `.setup()`；运行 `invoke → interrupt → 停止进程 → 重启 → resume`，核对 checkpoint 与最终状态。
5. **失败测试：** 在恢复前后模拟响应丢失和重复调用，证明业务副作用由 Spring 幂等保护，而不是误把 checkpointer 当成业务幂等系统。
6. **跨服务：** Spring 调用 Agent、Agent 调用 Spring 工具 API，验证认证、超时、取消、错误映射和一次完整物流延迟调查流程。

只有以上验证通过后，才能把该版本组合从“建议基线”升级为“项目已验证基线”。

## 6. 验证限制

- 本文已在 2026-08-09 核对官方网页与官方包元数据；版本信息是时间快照，后续创建项目时应重新查询并记录锁文件。
- 没有在本机执行 `npm install`、`npm run build`、Maven/Gradle 构建、Python 依赖解析、Docker 拉取或 PostgreSQL 集成测试。
- 没有核对尚未决定的前端路由、状态管理、UI 组件库、Java 数据访问方式、Python Web 框架、模型提供商 SDK 等传递依赖。
- “依赖区间相容”只表示包元数据存在可解析交集，不等同于该组合没有运行时缺陷。
- Spring Boot 4.1 与 Java 25 的兼容性是官方明确声明；其余跨服务兼容性最终由项目协议与真实端到端测试决定。
