# ADR 0001：跨语言质量门禁

## 状态

已接受。

## 背景

仓库已经具备三端确定性测试和全栈 smoke acceptance，但格式、静态分析、Python
类型检查、Java 架构边界和统一验证入口尚未由机器强制执行。项目会大量使用 AI
Coding，因此需要把可自动验证的规则下沉到本地 canonical check 和 CI。

## 决策

- React/TypeScript 使用 Prettier 统一格式，并使用 ESLint、typescript-eslint typed
  linting 和 React Hooks 规则发现类型相关及 Hooks 问题。
- Python 使用 Ruff 同时承担格式化、lint 和 import 规则，使用 Pyright 执行静态类型检查。
- Java 使用 Spotless 固定格式，使用 Checkstyle 执行源码规则检查，使用 ArchUnit
  固化可由当前包结构真实表达的依赖边界。
- 三端 Docker `test` target 运行各自完整质量门禁；根目录
  `scripts/check.ps1` 是开发者与 CI 共用的唯一规范化入口。
- 完整门禁包含 destructive Compose reset，调用者必须显式提供匹配的唯一
  `customer-agent-gate-*` project、`gate-*` 镜像 tag 与非 baseline 端口；入口在任何 Docker
  操作前读回有效 Compose 配置并 fail closed。组件级 `-SkipAcceptance` 检查不执行该 reset。
- 保留独立的 full-stack acceptance，避免组件检查替代跨服务行为验证。

## 被否决的方案

- 仅依赖 `AGENTS.md`、Skill 或 AI review：属于软约束，无法阻止不合格代码进入主分支。
- Python 组合 Black、Flake8 和 isort：能力可满足需求，但工具与配置数量更多；Ruff
  在当前规模下更简单。
- Python 使用 Mypy：同样可行；当前选择 Pyright，是因为它对渐进式类型检查和编辑器反馈
  的支持与本项目更匹配。
- Java 只使用 Spotless 或只使用 Checkstyle：前者只解决唯一格式，后者不适合作为自动格式器，
  两者职责不同。
- 只运行单元测试：无法覆盖格式、静态类型、包依赖方向和跨服务验收。

## 证据

- [typescript-eslint typed linting](https://typescript-eslint.io/getting-started/typed-linting/)
- [Ruff formatter](https://docs.astral.sh/ruff/formatter/)
- [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md)
- [Spotless Gradle plugin](https://github.com/diffplug/spotless)
- [Checkstyle checks](https://checkstyle.org/checks.html)
- [ArchUnit user guide](https://www.archunit.org/userguide/html/000_Index.html)

## 影响

格式化会产生一次性的大范围源码改动；之后新代码若不满足格式、lint、类型、架构或测试规则，
canonical check 和 CI 将直接失败。GitHub 仓库仍需把对应 Actions checks 配置为 `main`
的 required checks，才能形成最终合并硬门禁。
