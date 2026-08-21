# Issue #82：Docker BuildKit 标准代理适配验证

## 交付范围

- backend Docker 构建通过 Gradle init script 把 BuildKit 注入的标准 `HTTP_PROXY`、`HTTPS_PROXY` 与可等价表达的 `NO_PROXY` 映射到 Java 网络 system properties。
- 仓库不保存代理 endpoint 或凭据；带 userinfo 的 proxy URI 只在临时 Gradle JVM 中映射为 proxy user/password，回归用运行时随机合成值证明构建输出不泄露它们。
- frontend 的纯本地 BusyBox `wget` healthcheck 显式禁用代理，避免请求离开容器。
- 不启用 Clash TUN，不修改产品业务逻辑，不涉及 #73。

## TDD 证据

公开回归入口：

```powershell
pwsh ./scripts/test-gradle-proxy.ps1
```

首个 red 先由唯一临时本地 proxy container 证明普通 `curl` 能采用同类标准代理环境，再证明 BuildKit 已注入 `HTTP_PROXY`、但 Gradle 未配置 `http.proxyHost`。实现后，同一入口覆盖并通过：

- 无代理时不设置 JVM proxy property；
- 无凭据 HTTP/HTTPS proxy 的 host、显式 port；
- 前导点域名 `NO_PROXY` 到 Java `http.nonProxyHosts` 的明确转换；
- 运行时随机合成带凭据 URI 被安全采用，覆盖 percent-encoded 分隔符，且捕获的成功构建输出不含解码值、编码值或完整 proxy URI；
- CIDR `NO_PROXY` 因 Java pattern 无法等价表达而被脱敏拒绝；
- 普通 HTTP 对照在有界就绪检查后执行；container、network 与三个并发唯一测试镜像标签在成功或失败后均精确删除，并在 Docker 查询成功的前提下回读不存在。

官方契约：[Docker CLI proxy configuration](https://docs.docker.com/engine/cli/proxy/)、[Gradle init scripts](https://docs.gradle.org/current/userguide/init_scripts.html)、[Gradle networking](https://docs.gradle.org/current/userguide/networking.html)、[Java networking properties](https://docs.oracle.com/en/java/javase/26/docs/api/java.base/java/net/doc-files/net-properties.html)。

## 验收结果

- 聚焦 backend Docker `test` target：退出码 `0`；`:checkstyleMain` 与完整 backend `check` 成功。
- 共享 Docker Engine、无额外环境覆盖、仓库根目录原样 `pwsh ./scripts/check.ps1`：退出码 `0`。
- `FULL_RESET_GATE`：Spring、database、agent 均为 `UP`；Issue #29 normal/reconciliation、广域 integration smoke、审批队列时间、React live 与日志隐私扫描通过。
- 验收后精确拆除本项目 Compose containers/networks/volumes；回读均为 `0`。代理契约与聚焦测试镜像标签不存在；没有执行 `prune`。

完整 Docker Desktop 恢复、备份和根因证据见 `docs/research/docker-desktop-windows-backup-recovery.md`。
