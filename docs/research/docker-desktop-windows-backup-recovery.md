# Docker Desktop for Windows 备份与两级恢复方案

> 调研日期：2026-08-17
>
> 研究问题：共享 Docker Desktop（WSL 2 后端）失效时，如何在不猜测数据归属的前提下完成最小备份，并按 `Clean / Purge data`、`Reset to factory defaults` 两级恢复。
>
> 证据范围：恢复语义仅采用 Docker 官方文档与 Microsoft Learn；本机状态来自 2026-08-17 的只读文件、设置日志、WSL 与 Docker Engine API 盘点。
> 结论边界：本文同时记录恢复前依据、本机盘点与实际执行结果。凡官方文档没有逐项说明的删除/保留行为均标为 `unknown`，不得据此推断其他项目数据可删除。

## 结论摘要

1. 在 Docker Engine API 不可用时，Docker 官方支持的整机级备份是：**完全停止 Docker Desktop 后**，复制 `%LOCALAPPDATA%\Docker\wsl\data\docker_data.vhdx` 到安全位置；重装或重置后把它恢复到原路径。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
2. Docker Desktop 的 Windows 用户设置文件位于 `%APPDATA%\Docker\settings-store.json`。应复制一份用于审计和手工复原，但 Docker 官方备份页只明确承诺恢复数据 VHDX，没有把直接覆盖 `settings-store.json` 描述为受支持的自动恢复流程。[Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/)
3. 官方对 `Clean / Purge data` 的原文语义是“重置全部 Docker 数据、不执行 factory reset”，并明确提示会丢失现有设置；对 `Reset to factory defaults` 的语义是把 Docker Desktop 的全部选项恢复到初装状态。[Docker Desktop troubleshoot](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/)
4. 上述 Troubleshoot 页面**没有逐项枚举**两种操作分别如何处理容器、镜像、named/anonymous volumes、BuildKit cache、Compose 元数据、登录态、凭据存储、Kubernetes 数据或 Extensions。因此恢复前必须把这些对象的保留情况按 `unknown / 可能删除` 处理，不能把 `Clean / Purge data` 误称为“只清缓存”。
5. 推荐恢复顺序：先完成数据盘与配置/归属清单的可验证备份；先尝试 `Clean / Purge data`；只有前者失败且获得新的明确授权，才执行 `Reset to factory defaults`。每一级恢复后均先验证共享 Engine/API、临时容器与自建网络，再运行仓库 canonical check。

## 0. 本机只读盘点（2026-08-17）

### 0.1 数据盘、设置与目标空间

| 项目 | 本机证据 | 结论 |
|---|---|---|
| 实际 Docker 数据 VHDX | `C:\Users\lizhuo\AppData\Local\Docker\wsl\disk\docker_data.vhdx` | 这是本机实际路径；不得套用文档中的默认目录猜测 |
| 数据 VHDX 当前文件大小 | `40,824,209,408` bytes，即 `38.021 GiB`；NTFS 报告为非 sparse 文件 | 当前宿主物理占用约 38.021 GiB，另计少量文件系统开销 |
| 数据 VHDX 虚拟上限 | Desktop 设置快照 `diskSizeMiB=512000`，即 `500 GiB` | 虚拟容量不是备份文件当前大小 |
| Docker Desktop 系统 VHDX | `C:\Users\lizhuo\AppData\Local\Docker\wsl\main\ext4.vhdx`，约 `174 MiB` | 不是 Docker 官方离线数据备份页指定的数据盘，但可纳入取证清单 |
| Desktop 设置文件 | `C:\Users\lizhuo\AppData\Roaming\Docker\settings-store.json`，168 bytes | 只保存少量显式覆盖；不能单靠它还原全部运行设置 |
| Docker CLI 设置 | `C:\Users\lizhuo\.docker\config.json`，使用 `credsStore=desktop` | 原文件进入受控备份；不得把认证值写进报告或仓库 |
| 备份目标空间 | `C:` 可用 `76.27 GiB`；`D:` 可用 `110.30 GiB` | 两盘都容得下当前 38.021 GiB VHDX；推荐 `D:`，余量约 72 GiB，仍须复制前复核 |

Docker Desktop 设置快照还保留了旧的 `dataFolder=C:\ProgramData\DockerDesktop\vm-data`，但该目录当前不存在。备份必须以实际找到的 VHDX 为准。复制前完全停止 Desktop；复制后校验长度与 SHA-256，备份目标不得位于将被清理的数据盘内部。

### 0.2 代理、WSL integration 与资源

- Docker Desktop 版本：`4.43.2`；Engine：`28.3.2`，API `1.51`，storage driver `overlay2`，Docker root `/var/lib/docker`。
- Engine 的 HTTP/HTTPS proxy 均指向 `127.0.0.1:7897`，无 URL userinfo；`NO_PROXY` 已配置。报告不保存 bypass 原文或任何认证值。
- Desktop 未配置 manual HTTP/HTTPS/PAC override；proxy mode 有值，但为避免从脱敏日志反推，具体模式标为 `unknown`。
- `%USERPROFILE%\.wslconfig` 仅显式设置 `networkingMode=mirrored`、`autoProxy=true`；未显式设置 processors/memory/swap。
- 当前 `docker-desktop` 实际可见：16 CPU、`14,211,256 KiB` memory、`4,194,304 KiB` swap。Desktop 日志快照中的 `memoryMiB=2048`、`swapMiB=1024` 与 WSL 实际值不一致，因此只能作为历史/兼容设置记录，不能声称是当前生效上限。
- `wslEngineEnabled=true`；默认 WSL distribution integration 已启用；显式 `integratedWslDistros` 列表为空。当前默认发行版为 Ubuntu。
- 网络设置快照：IPv4-only、DNS inhibition `auto`、Vpnkit enabled。Kubernetes disabled，containerd snapshotter disabled，disk TRIM enabled，resource saver enabled（300 秒）。

### 0.3 容器、Compose、volume、image 与 network 归属

Windows named-pipe API 仍因内部路由异常返回 HTTP 500，但 dockerd 自身 netns 内的只读 API 可用。本次只调用 `GET /version`、`/info`、`/containers/json`、`/volumes`、`/images/json`、`/networks`、`/system/df`，没有启动、删除或修改资源，也没有读取 container environment、secret、registry token 或原始 proxy 配置。

| 对象 | 数量/大小 | 归属与可重建性 |
|---|---|---|
| Containers | 66，全部 stopped | 65 个属于 customer-agent 历史检查；1 个 `db-lab` OpenGauss 容器。没有其他运行中容器 |
| Compose projects（有 container） | customer-agent 9 组、`db-lab` 1 组 | customer-agent 数据经用户确认可丢弃；该结论不得外推到 `db-lab` |
| Named volumes | 12 | customer-agent PostgreSQL 10 个，共约 736 MiB，可按用户声明丢弃；`db-lab_opengauss-data` 约 708.91 MiB；`gemini-balance_mysql_data` 约 381.81 MiB，后两者必须备份或由所有者明确放弃 |
| Anonymous volumes | 64，共约 6.26 MiB | 5 个仍被 customer-agent Gradle cache mount 引用；59 个无引用但归属无法可靠确认，标为 `unknown`，不得擅自删除 |
| Top-level images | 375；其中 dangling 178 | layers 约 26.12 GiB；BuildKit cache 约 19.87 GiB。customer-agent 有大量本地历史 tag；其他镜像包括 OpenGauss、MySQL、Gemini Balance、Lobe Chat、ChatGPT Next Web、GitHub MCP 等 |
| Networks | 35 | 30 个 customer-agent 网络、`db-lab` 1 个、`gemini-balance` 1 个、系统 `bridge/host/none` 3 个 |

`db-lab` 的 Compose 文件 `D:\数据库实验报告\docker-compose.yml` 当前存在。customer-agent baseline 与 issue67 的 Compose 文件存在；issue26/issue27 历史 worktree 已不存在，因此这些历史 tag 无法按原路径精确重建，但当前仓库可重建项目功能镜像。`gemini-balance` 当前没有 container label 可提供 Compose 文件路径，其配置材料标为 `unknown`。

公开或 GHCR tag 只能说“可能重新 pull”；`latest` 可变、私有仓库权限和外部 registry 可用性均未验证，不能声称可字节级重建。完整 VHDX 备份会保留当前 image/cache 状态；如果决定不做整盘恢复，关键本地镜像还需另行 `docker image save`，但本次未执行。

### 0.4 本机最小备份清单与准入条件

在授权任何破坏性动作前，至少完成并回读：

1. 完全停止 Docker Desktop 后，将实际 `docker_data.vhdx` 复制到 `D:` 上独立、受访问控制的备份目录；记录源/目标长度、SHA-256、时间和 Desktop stopped 证据。
2. 受控保存 `settings-store.json`、`.wslconfig` 和 `.docker/config.json` 原件；报告只保存本节的脱敏摘要。OS credential store 不导出明文秘密。
3. 单独备份 `db-lab_opengauss-data` 与 `gemini-balance_mysql_data` 的数据库原生 dump 和 volume 内容。执行证据与恢复验证见第 0.5 节。
4. 保存 `db-lab` Compose 文件及其 Dockerfile/`.env`/secret 来源；对 `gemini-balance` 查明配置目录和所有者。敏感文件只进入受控备份，不提交仓库。
5. 59 个无引用匿名 volume 的归属仍为 `unknown`。在没有所有者确认时，只能由完整 VHDX 覆盖其灾备，不能逐个删弃。
6. 记录关键镜像 tag/digest；对不可重新 pull、未推送且无 Dockerfile 的镜像另做 `docker image save`。当前尚未验证 registry 可用性，因此不能用“可 pull”代替备份。

只有上述备份实际存在、校验通过、恢复演练边界明确并重新获得破坏性操作授权，才可进入第一级 Clean/Purge。2026-08-17 用户已授权本次完整流程；第 0.5 节记录的 VHDX、配置和两个非 customer-agent 数据库备份已通过准入。

### 0.5 已执行备份、校验与恢复验证

受控备份根目录：`D:\docker-desktop-backups\20260817-pre-clean-purge`。ACL 已移除继承，仅当前用户、SYSTEM、Administrators 具有 FullControl。不得在后续清理或回滚时删除该目录。

| 备份 | 长度 | SHA-256 | 验证 |
|---|---:|---|---|
| `docker_data.vhdx` | 40,824,209,408 bytes | `06426BAE297C76468416E8A335759DA6B2F1FAD7D896978181EA7AFD6A6F60B0` | Desktop/WSL 完全停止后复制；源/目标长度、时间戳和 SHA-256 一致；源未修改 |
| `config-raw/docker-desktop-settings-store.json` | 168 bytes | `AB4CD805C4863445F4A8ABD9142872F1C9219E3C906E2C52B92DCCBD624897CE` | 源/目标一致；原文仅存受控目录 |
| `config-raw/wslconfig` | 47 bytes | `674679A28EC9824A3C41A086AEC864C01B876BACF100577F99F70DF525ACBC9E` | 源/目标一致 |
| `config-raw/docker-cli-config.json` | 78 bytes | `7B2EC346B548B5BDF0BCD95923E800FE50AC50F0B2678E874FC18124AC5B22B6` | 源/目标一致；凭据由 `credsStore=desktop` 管理，报告未记录认证值 |
| `databases/db-lab-opengauss-all.sql.gz` | 5,029 bytes | `405D64032075F8C78C572E469D66E218687F2440FAFC6203072F2898AC873EDC` | `gs_dumpall` 成功；容器/宿主 hash 一致；`gzip -t` 成功 |
| `databases/db-lab-labdb.custom` | 28,125 bytes | `B452F52B3C9719E5055E3D96F0245A628660F3531F7D0A7C46D63E41EA7877E3` | `gs_restore` 到唯一临时数据库成功；源/目标业务表均 18；trap 删除临时数据库 |
| `databases/db-lab-opengauss-volume.tar` | 744,907,264 bytes | `24CC66D337C3906DEEEA4CFAB3068D7F504BD3F9A0A9961886F6C261609459C1` | 原容器正常停止后冷态导出；tar 2,731 entries，可列目录且包含 `PG_VERSION` |
| `databases/gemini-balance-mysql-volume.tar` | 400,491,520 bytes | `6895E408DACC46179BFC8D0E7A3AF0DFD03E37626F195EBA89E437077CEEAE80` | 原卷只读冷态导出；tar 184 entries，包含 `auto.cnf`、`mysql/`、`ibdata1`；实际恢复到临时卷后 `mysql:8` 启动成功，`mysqladmin ping` 成功，可读取 5 个 database 和 38 个 `mysql` 系统表 |

OpenGauss 恢复命令（在版本兼容的 OpenGauss 容器中，以 `omm` 用户执行）：

```sh
gzip -dc /backup/db-lab-opengauss-all.sql.gz \
  | /usr/local/opengauss/bin/gsql -d postgres -v ON_ERROR_STOP=1

# 或先创建空数据库，再恢复已验证的 custom dump：
/usr/local/opengauss/bin/gs_restore -e -d <empty_database> \
  /backup/db-lab-labdb.custom
```

volume 冷态恢复命令（目标 volume 必须为空，数据库容器必须停止；`<backup-root>` 替换为受控目录）：

```powershell
docker run --rm --network none `
  --mount type=bind,src=<backup-root>\databases,dst=/backup,readonly `
  --mount type=volume,src=db-lab_opengauss-data,dst=/restore `
  nginx:1.29.4-alpine sh -lc `
  'tar -xf /backup/db-lab-opengauss-volume.tar -C /restore --strip-components=1'

docker run --rm --network none `
  --mount type=bind,src=<backup-root>\databases,dst=/backup,readonly `
  --mount type=volume,src=gemini-balance_mysql_data,dst=/restore `
  nginx:1.29.4-alpine sh -lc `
  'tar -xf /backup/gemini-balance-mysql-volume.tar -C /restore --strip-components=1'
```

恢复后必须使用原 Compose/image 版本启动数据库并做业务级校验。MySQL 备份已用 `mysql:8` 克隆验证；OpenGauss 已用当前 `opengauss/opengauss-server:latest` 的本机镜像验证，但 `latest` 可漂移，恢复时优先使用 VHDX 中保留的原 image ID。

备份过程中创建的唯一自有验证资源：

- containers：`3457164c1c2e...`、`605a793b64f2...`、`abd65c71b968...`；
- volume：`codex-mysql-restore-verify-20260817`；
- label：`codex.backup.probe=*`。

当前损坏 daemon 对这些对象的精确 DELETE 均返回 HTTP 500，因此 Clean/Purge 前仍有 3 个 stopped probe containers 与 1 个 probe volume。它们不包含原始业务卷，且必须在 Clean/Purge 后按名称/label 回读为不存在；不得使用 `prune` 代替精确证据。

### 0.6 Clean/Purge 实际执行结果（阻塞）

2026-08-17 用户在最终删除确认点再次明确同意后，Docker Desktop 4.43.2 的 Troubleshoot → `Clean / Purge data` 对话框中**仅勾选 `WSL 2`**；`Hyper-V`、`Windows Containers` 均未勾选，`Reset to factory defaults` 未触碰。点击最终 `Delete` 后，Docker Desktop 渲染进程进入“未响应”，但后台会话仍保持 running；数据盘在数分钟观察期内没有继续写入，也没有出现资源重置证据。

随后按授权执行 `docker desktop restart`，Desktop 从 session `a089eaf7-77e2-4bbf-b2a1-7e8fe5d74c2a` 重启到 `08a03227-040e-4eaf-b24d-bef97ab6c28a`。重启后的验证结果如下：

- `docker version` 与 `docker info` 均在 6 秒 red-capable 探针中超时；共享 named-pipe Engine/API 仍不可用。
- 后端日志继续返回 `connect tcp 192.168.65.7:2375: no route to host`，并记录 WSL `CheckConnection: getaddrinfo() failed: -5`。
- 通过 dockerd 自身 network namespace 只读回读到 `69` containers、`405` images、`77` volumes、`35` networks；其中原 db-lab 容器仍在，本次 `3` 个 stopped backup probe containers 与 `codex-mysql-restore-verify-20260817` probe volume 也都仍在。这证明 WSL 2 Docker data **没有被 Clean/Purge 删除**。
- 数据盘仍位于 `C:\Users\lizhuo\AppData\Local\Docker\wsl\disk\docker_data.vhdx`，重启后物理长度为 `41,095,790,592` bytes；D: 的灾备副本和数据库备份未被修改或删除。

因此，本次只能判定为“Clean/Purge UI 提交后挂起且未落地”，不能判定修复成功。继续重试 UI 删除、手工删除/替换 VHDX、调用未文档化 reset 接口或执行 Factory Reset 都需要新的明确授权；在当前边界内必须停止，不能运行临时容器/自建网络验收或仓库 canonical check。

### 0.7 Factory Reset、设置恢复与最终阻塞

用户随后针对 Docker Desktop Troubleshoot 中的官方 `Reset to factory defaults` 最终确认框明确授权。执行前再次核对目标为 Factory Reset；确认框明确警告会销毁 Docker containers、images 和 volumes。点击 `Yes, reset anyway` 后 Desktop 成功重建 WSL 2 后端，没有使用未文档化 reset 接口，也没有手工删除或替换 VHDX。

重建后的确定性证据：

- 新 Desktop session 为 `3033e49a-8b76-41b1-a036-33ba3af6da72`；恢复必要设置并重启后的 session 为 `c9e06e9c-cb8e-42f9-b9a4-8a282fb52390`。
- `docker version` 与 `docker info` 均在 6 秒探针内成功；Server `28.3.2`、API `1.51`、Docker Desktop `4.43.2`。Factory Reset 后 containers/images 均为 `0`，系统网络仅 `bridge`、`host`、`none`。
- 当前数据盘位于 `C:\Users\lizhuo\AppData\Local\Docker\wsl\disk\docker_data.vhdx`，回读长度 `1,410,334,720` bytes。受控备份仍位于 D:，完整备份长度仍为 `40,824,209,408` bytes；没有删除或修改该备份目录。
- 通过官方 Settings UI 关闭 Factory Reset 默认启用的 containerd image store，回读 `UseContainerdSnapshotter=false`，Engine storage driver 为 `overlay2`。`.wslconfig` SHA-256 仍为 `674679A28EC9824A3C41A086AEC864C01B876BACF100577F99F70DF525ACBC9E`；Ubuntu integration 内执行 Docker server version 返回 `28.3.2`。磁盘位置保持默认 WSL 路径；资源限制继续由 `.wslconfig` 管理。
- Factory Reset 清除了旧的 69 containers、77 volumes、405 images 和非系统 networks，也清除了本任务遗留的 3 个 stopped probe containers 与 `codex-mysql-restore-verify-20260817` volume。当前精确回读为 containers `0`、volumes `0`、images `0`、networks `3`。

Engine/API 路由故障已经由 Factory Reset 修复，但验收在 registry 代理处出现独立阻塞：Windows 系统代理与用户级 `HTTP_PROXY`/`HTTPS_PROXY` 均为 `http://127.0.0.1:7897`，宿主上该端口确有监听；Docker Engine 却从 WSL 2 Docker VM 内连接同一回环地址，因此 `docker pull alpine:3.22` 确定性失败：

```text
proxyconnect tcp: dial tcp 127.0.0.1:7897: connect: connection refused
```

已在官方 Settings → Resources → Proxies 中启用 manual proxy，并把 HTTP/HTTPS 设置为同一脱敏地址；Engine 回读仍为 `127.0.0.1:7897`，重试 pull 得到相同错误。这证明配置已经传递给 Engine，但该地址在 Docker VM 的网络命名空间中不可达，而不是 Docker CLI、Engine API 或 registry 凭据错误。

第一次验收尝试中，唯一自建网络 `codex-shared-engine-net-20260817` 创建成功；由于镜像 pull 失败，唯一临时容器未创建。`finally` 已精确删除该网络，并回读 probe container/network/image 均为 `0`；没有使用 `prune`。因为当前 image store 为全新空状态，无法运行“可离线命中本地镜像”的容器探针，仓库 canonical check 也必然先在镜像获取处失败，所以未把它伪装为产品门禁结果。依照“UI/执行再次异常即停止、不自行扩大”的授权边界，本次没有创建宿主端口转发、修改系统代理监听地址、安装代理运行时、再次 reset 或恢复旧 VHDX。

### 0.8 Engine 拉取恢复、构建代理诊断与当前授权边界

2026-08-21 至 2026-08-22 继续处理代理接入。Clash Verge 保持 `allow-lan: false`，没有把代理监听扩大到 `0.0.0.0`，也没有关闭防火墙。用户在 Clash Verge 中持久保存 Docker Hub bypass；Windows `ProxyOverride` 回读包含 `docker.io`、`*.docker.io`、`docker.com`、`*.docker.com` 与 `production.cloudflare.docker.com`。一次试验性 PowerShell relay 曾触发 Windows 自动创建两条 Public 入站规则；经用户确认管理员 UAC 后，仅按唯一 GUID Name 删除 TCP `9CF47BFD-F2DE-40A6-9D04-1F0BA546FF04` 与 UDP `D4EEC6E4-E8EB-4508-BA69-5415602CE826`，回读两者均不存在，临时端口 `17897` 无 listener，相关临时文件也已删除。

重新启动 Docker Desktop 后，共享 Engine 恢复为 running；`docker version` 返回 Client/Server `28.3.2`、API `1.51`，`docker info` 返回 `overlay2`。Engine 使用 Docker Desktop 内部代理 `http.docker.internal:3128`，`docker pull alpine:3.22` 成功。唯一命名 container/network 探针能够创建、获得 bridge 路由与 Docker DNS，结束后精确回读 probe container、network、image 均不存在；全局状态回到 containers `0`、volumes `0`、networks `3`，没有执行 `prune`。

后续 red-capable 检查区分出了第二层问题：容器直连 `repo.maven.apache.org` 会失败，而显式使用 `http://host.docker.internal:7897` 时 `curl` 返回 HTTP `200`。依据 Docker 官方客户端代理机制，在 `%USERPROFILE%\.docker\config.json` 中只新增无凭据的 `proxies.default`，并在同目录保留修改前回滚副本 `config.json.codex-backup-20260821-pre-proxy`（SHA-256 `0EF3635FFDEC36C591EA98A35F6F374CC90EF735B91087BA788C06AE81B0CD8F`）；`auths` 与 `credsStore` 字段保留。新容器自动获得大小写 HTTP/HTTPS proxy 变量，访问目标 Maven POM 返回 `200`。[Docker CLI proxy configuration](https://docs.docker.com/engine/cli/proxy/)

但是，仓库根目录原样执行 `pwsh ./scripts/check.ps1` 仍在 backend Dockerfile 的 `gradle check --no-daemon` / `:checkstyleMain` 失败：Gradle/JVM 不采用容器的通用 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量，转而直连 Maven，最终报 `Remote host terminated the handshake`。对照证据如下：

- Docker DNS 与指定 `1.1.1.1` 的查询均被 Clash Fake-IP 接管，返回 `198.18.0.101`；经本机代理访问 DNS-over-HTTPS 得到真实地址 `104.18.19.12`、`104.18.18.12`。
- 临时容器清空全部 proxy 环境后，即使以 `curl --resolve` 指定上述真实地址，TLS 直连仍失败；因此仅添加 Fake-IP filter 不足以修复，当前网络必须经过代理。
- 普通容器的 `curl` 会读取 Docker CLI 自动注入的 proxy 环境并成功；Gradle/JVM 不会自动把这些变量转换为 Java `https.proxyHost`/`https.proxyPort` 系统属性。

因此当前完成状态是：共享 Engine/API、registry pull、临时 container、自建 network 与精确清理均已通过；canonical check 仍确定性失败，不能宣称完成。主机侧下一候选是 Clash TUN/透明代理，使 JVM 的直连流量也进入代理，但这会影响整机网络，超出“只绑定 Docker/WSL 专用接口、不扩大系统影响”的既有授权；在协调任务取得新的明确授权前未执行。没有修改产品代码、没有恢复旧 VHDX、没有删除或修改 D: 备份，也没有启动任何产品 ticket。

### 0.9 Issue #82 可移植构建修复与最终验收

协调决定不启用 Clash TUN，改为在基础设施任务内修复仓库构建 seam，并创建 [Issue #82](https://github.com/Stellogic/customer-agent/issues/82) 记录范围与验收标准。修复没有硬编码本机代理地址：Docker/BuildKit 继续按官方契约向 build 注入标准 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`；backend Dockerfile 只加载仓库内的 Gradle init script。该脚本在 Gradle 初始化阶段读取环境，用 `java.net.URI` 解析无凭据 HTTP/HTTPS proxy，并在未有显式 JVM proxy property 时设置 Java `http.proxyHost`、`http.proxyPort`、`https.proxyHost`、`https.proxyPort` 与可准确转换的 `http.nonProxyHosts`。[Docker CLI proxy configuration](https://docs.docker.com/engine/cli/proxy/)、[Gradle init scripts](https://docs.gradle.org/current/userguide/init_scripts.html)、[Gradle networking](https://docs.gradle.org/current/userguide/networking.html)、[Java networking properties](https://docs.oracle.com/en/java/javase/26/docs/api/java.base/java/net/doc-files/net-properties.html)

安全边界如下：

- 无代理环境不设置或清除任何 JVM proxy property；显式 Gradle/JVM 配置保持优先。
- proxy URI 只接受 HTTP/HTTPS、有效 host、无 path/query/fragment 的形式；带 userinfo 的 URI 在任何网络访问前用不含原值的错误拒绝，不把凭据写入脚本、镜像层、构建日志或 Git。
- `NO_PROXY` 只把逗号分隔的主机、Java 支持的首尾通配符、前导点域名与 IPv6 loopback 转成 Java `|` 模式；CIDR、端口限定、其他 IPv6 或不可等价通配符会用脱敏错误拒绝，不悄悄扩大或缩小绕过范围。
- frontend 本地 healthcheck 使用 BusyBox `wget -Y off` 直连 `127.0.0.1`，避免纯本地健康请求被运行容器的 proxy 环境带出容器；应用自身的代理环境没有被清空。

TDD 与运行证据：

1. 首个快速回归先证明 BuildKit 中标准 proxy 变量已存在，但 Gradle 的 `http.proxyHost` 为空，确定性红灯信息为 `HTTP_PROXY was injected, but Gradle did not configure http.proxyHost`。
2. 加入 init seam 后，同一回归转绿；随后覆盖无代理、HTTP/HTTPS 显式端口、前导点 `NO_PROXY`、合成带凭据 URI 不泄露、CIDR 不可等价转换的安全拒绝。测试脚本用唯一镜像标签并在 `finally` 精确删除。
3. 真实 `backend` Docker `test` target 通过，原失败点 `:checkstyleMain`、完整 backend 测试与格式检查均成功；聚焦镜像标签已删除。
4. 第一次完整门禁在 frontend healthcheck 暴露 BusyBox `wget` 代理行为，第二次在 Issue #29 异步流暴露运行容器 `NO_PROXY` 缺少 Compose 服务名；两者均通过同请求的 red/green 对照收敛，没有把失败重跑当作偶发抖动。Docker 客户端可回滚 `noProxy` 最终补充本仓库 Compose 服务 DNS 名称，使新 agent-server 对 `backend` 的 HTTPX 请求由失败转为 HTTP `200`。
5. 最终从空 customer-agent 卷、共享 Engine、无额外命令行环境覆盖，仓库根目录原样 `pwsh ./scripts/check.ps1` 退出码 `0`。backend、Agent 22 项、frontend 38 项、Issue #29 normal/reconciliation、广域 integration smoke、审批队列时间、React live 与日志隐私扫描全部通过；最终状态输出 `FULL_RESET_GATE`、Spring/database/agent 均为 `UP`。测试脚本改用运行时随机合成凭据后，额外的最终复跑曾在 registry 对 `nginx:1.29.4-alpine` 的 metadata HEAD 遇到一次 `EOF`；同一共享 Engine 上精确 `docker pull nginx:1.29.4-alpine` 随即成功，随后再次原样运行完整门禁仍退出 `0`，因此该瞬时 registry 失败没有被当成产品或代理修复证据。
6. 验收后执行精确 `docker compose down --volumes --remove-orphans`；回读本项目 containers `0`、networks `0`、volumes `0`，proxy contract images `0`、focused image 不存在，全局 containers `0`、volumes `0`、系统 networks `3`。没有执行 `prune`，构建镜像按验收产物保留。

最终共享 Engine 回读仍为 Client/Server `28.3.2`、API `1.51`、storage driver `overlay2`；Docker Desktop Engine proxy 为 `http.docker.internal:3128`。D: 受控备份和同目录 Docker client config 回滚副本均保持存在，未恢复旧 VHDX，未执行新的 Clean/Purge 或 Factory Reset，未启用 TUN，也未启动 #73。

## 1. 官方确认的存储与设置位置

| 对象 | 官方位置/语义 | 备份用途 | 结论性质 |
|---|---|---|---|
| Docker Desktop WSL 2 数据根目录 | 默认 `%LOCALAPPDATA%\Docker\wsl`；Dashboard 的 `Settings -> Resources -> Advanced` 可更改位置 | 定位实际 data disk，不能只假设默认路径 | 官方确认 |
| Docker 数据 VHDX | `%LOCALAPPDATA%\Docker\wsl\data\docker_data.vhdx`（默认位置） | Engine 无法启动时，整盘保留容器/镜像数据；恢复到同一路径 | 官方确认 |
| Docker Desktop 用户设置 | `%APPDATA%\Docker\settings-store.json` | 保存设置快照、差异审计、必要时手工重配 | 官方确认位置；直接覆盖恢复未获官方承诺 |
| WSL 全局配置 | `%USERPROFILE%\.wslconfig`，适用于所有 WSL 2 发行版 | 保存 CPU、内存、swap、网络、DNS、代理继承等主机级约束 | Microsoft 官方确认 |
| 其他 WSL 发行版 | 由 `wsl --export <Distro> <FileName>` 导出；WSL 2 可用 `--vhd` | 防止 Docker 恢复动作之外的 WSL 数据风险 | Microsoft 官方确认 |

来源：[Docker Desktop WSL 2 backend](https://docs.docker.com/desktop/features/wsl/)、[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)、[Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/)、[Microsoft WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config)、[Microsoft WSL basic commands](https://learn.microsoft.com/windows/wsl/basic-commands)。

### 1.1 大小与空间记录要求

恢复前应记录而不是猜测：

- `docker_data.vhdx` 的实际路径、文件逻辑长度、占用磁盘大小以及最后修改时间；
- 数据盘所在卷与备份目标卷的可用空间；
- 备份复制完成后的文件长度与校验摘要；
- Docker Desktop 是否完全停止后才复制。

Docker 官方明确要求复制 VM disk 前完全停止 Docker Desktop。Microsoft 说明 WSL 2 的 VHD 会动态扩展，其来宾视角最大逻辑容量并不表示宿主盘已有同等可用空间。因此应分别记录 VHDX 文件 Length/宿主实际占用、VHD virtual size/来宾已用量以及承载 Windows volume 的剩余空间；目标盘容量必须以实际文件和安全余量决定，不能以 `docker system df` 代替文件级容量检查。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)、[Microsoft WSL disk space](https://learn.microsoft.com/windows/wsl/disk-space)

## 2. 最小备份清单

### 2.1 必须备份

1. **完整 `docker_data.vhdx` 副本**：这是 Engine API 不可用时，Docker 官方明确给出的 Windows 容器/镜像数据备份路径。复制前必须完全停止 Docker Desktop；复制后保留路径、长度和校验值。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
2. **`settings-store.json` 脱敏副本与可读摘要**：记录 WSL 2 engine、data disk location、代理模式与 bypass、WSL integration、Docker Engine JSON、网络、Kubernetes、containerd image store 等当前值。原文件只应进入受控备份，不应提交仓库。
3. **Compose 与重建材料**：保存各项目的 `compose.yaml`/覆盖文件、Dockerfile、构建上下文版本、镜像来源/标签或 digest、启动参数、端口、网络、secret/config 来源。Docker 官方明确建议用 Docker Compose 或保存创建参数重建容器。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
4. **不可重建 named volume 的内容级备份**：Engine 可用时，Docker 官方提供临时容器挂载 volume 后打包、再解包恢复的方式；Engine 不可用时该项无法执行，应标为 `unknown`。完整 VHDX 只能作为整盘灾难恢复副本；Docker 的离线备份段没有逐项保证 named volume 可被单独恢复。[Docker volumes: back up, restore, or migrate](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes)、[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
5. **其他 WSL 发行版（如有不可重建内容）**：用 Microsoft 官方 `wsl --export` 流程独立备份；不要把 Docker 的 `docker_data.vhdx` 当作其他发行版备份。[Microsoft WSL basic commands](https://learn.microsoft.com/windows/wsl/basic-commands)

### 2.2 凭据与隐私边界

- Docker 官方提醒：container commit 会保留部分配置（包括 labels 与环境变量），环境变量可能包含密码或 proxy authentication；推送镜像时应使用 private repository，并仍需审查敏感内容。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
- named volume 的数据不包含在 committed image 中，必须单独备份。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
- Docker Desktop Basic proxy 凭据缓存在 OS credential store；因此不得把凭据明文复制进研究文档、盘点报告或仓库。设置摘要只保留 proxy mode、主机/端口的脱敏形式和 bypass 范围。[Docker Desktop settings: Proxy authentication](https://docs.docker.com/desktop/settings-and-maintenance/settings/#proxy-authentication)
- Docker CLI 的 `.docker` 配置目录可能包含 registry/proxy authentication 信息；Docker Desktop 默认使用平台原生凭据存储，但未配置 credential store 时，`config.json` 中的 `auth` 只是 Base64 编码而非加密。盘点只报告 `credsStore`/`credHelpers` 键名，不输出 `auth`、token、password、userinfo 或 PAC 内容。[Docker CLI configuration](https://docs.docker.com/reference/cli/docker/)、[docker login](https://docs.docker.com/reference/cli/docker/login/)
- `.env`、Compose `environment`、secret/config、registry 登录配置和私有镜像内容都应视为敏感；备份应加访问控制，文档只记录“存在/已备份/可重建/unknown”。

## 3. 资源归属与可重建性盘点

Engine API 正常时，应对 containers、images、volumes、networks、builders 逐项导出只读清单。Compose 创建的容器具有 `com.docker.compose.project` 与 `com.docker.compose.service` 标签；Compose 项目名用于把一组资源与其他部署隔离，是归属判断的一手证据。[Compose application model](https://docs.docker.com/compose/intro/compose-application-model/)、[Compose service labels](https://docs.docker.com/reference/compose-file/services/#labels)

每项至少记录：

| 对象 | 归属证据 | 可重建性判断 |
|---|---|---|
| Container | Compose project/service labels、image、mounts、ports、启动参数 | 有 Compose/Dockerfile 且持久数据在已备份 volume/bind mount：通常可重建；否则 unknown |
| Named volume | Compose project label、被哪些 container mount、业务负责人确认 | 数据库或上传文件等有独立备份才可恢复；仅有定义不等于有数据备份 |
| Image | repository/tag/digest、是否本地构建、Dockerfile/源码 commit、是否可重新 pull | 私有/未推送/无 Dockerfile 的本地镜像必须另备份；公开可 pull 镜像通常可重建 |
| Network | Compose project label、driver、IPAM/subnet、连接对象 | 多数可由 Compose 重建；自定义外部网络需保存参数 |
| Bind mount | host source path 与所有者 | 数据在 VHDX 之外；必须按宿主路径另行备份 |

若共享 Engine API 不通，就无法从 daemon 可靠列出现有 container、Compose project、named volume、image、network 与其 labels/mounts。此时只能从 Compose 文件、项目目录、Desktop 可读设置和完整 VHDX 的存在确认“可能有数据”，对象级清单必须标为 `unknown`，不能从文件名或已知 `customer-agent` 数据可丢弃推断其他项目也可丢弃。

## 4. 设置快照应记录什么

### 4.1 WSL 2 与资源限制

- 是否使用 WSL 2 based engine；默认 WSL 2 数据目录及实际 data disk location；启用了哪些 WSL 2 distribution integration。Docker Desktop 默认对 WSL default distribution 启用 integration。[Docker Desktop WSL 2 backend](https://docs.docker.com/desktop/features/wsl/)、[Docker Desktop settings: WSL integration](https://docs.docker.com/desktop/settings-and-maintenance/settings/#wsl-integration)
- WSL 2 模式下，CPU、内存和 swap 由 WSL utility VM 的 `.wslconfig` 管理；Docker Desktop 设置页把 Desktop 内的 CPU/memory/disk usage limit 标为 Mac、Linux、Windows Hyper-V 项，而非 WSL 2。[Docker Desktop settings: Resources](https://docs.docker.com/desktop/settings-and-maintenance/settings/#resources)、[Microsoft WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config)
- `.wslconfig` 中与故障相关的 `memory`、`processors`、`swap`、`swapFile`、`networkingMode`、`dnsTunneling`、`autoProxy`、`localhostForwarding` 应只读记录。该文件影响所有 WSL 2 发行版，不能为修 Docker 而未经授权改动。[Microsoft WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config)

### 4.2 代理、网络与 integration

- Docker Desktop proxy 负责登录、Desktop 应用、CLI、extensions 等 host-level traffic；当未配置 Containers proxy 时，它也是 image pull 的 fallback。
- Containers proxy 始终用于 `docker pull` 与 Compose pull；可选择 same as host、system、no proxy 或 manual。PAC 必须对 registry endpoints 返回合适代理，否则 pull 会失败。
- 记录时保留 proxy mode、脱敏 endpoint、bypass 列表；不得记录认证秘密。Basic 凭据位于 OS credential store。
- 记录 Docker subnet、默认 networking mode/DNS behavior（若 UI 提供）、WSL integration distribution 列表与 Docker Engine JSON。Docker 官方说明 Desktop 内部服务默认使用私有 IPv4 网段 `192.168.65.0/24`，企业/VPN 环境应留意冲突。[Docker Desktop settings: Proxies and Network](https://docs.docker.com/desktop/settings-and-maintenance/settings/#proxies)

## 5. 两级恢复方案

执行任一级前都必须重新确认：备份文件存在且校验通过；备份目标不在将被清理的数据盘中；归属为 `unknown` 的共享对象已由所有者接受风险；已获得对应破坏性操作的明确授权。

### 5.1 第一级：Clean / Purge data

**官方确认的影响**

- 重置全部 Docker data；
- 不执行 factory-default reset；
- 会丢失现有 settings。

来源：[Docker Desktop troubleshoot](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/)

**必须按 unknown 处理的影响**

官方同页没有逐项说明 containers、images、volumes、build cache、Compose labels/metadata、Kubernetes、extensions、登录态与 OS credential store 是否分别删除或保留。操作前应按“Docker 数据可能全部删除、Desktop 设置可能丢失”准备，而不是依赖未文档化实现细节。

**回滚**

如果需要恢复原 Docker 数据，Docker 官方路径是完全停止 Docker Desktop，将已备份的 `docker_data.vhdx` 恢复到同一位置，再启动 Desktop。设置应依据脱敏快照手工复原；直接覆盖 `settings-store.json` 不在官方 backup/restore 流程的明确承诺内。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)

不得用 Windows 工具挂载、编辑或改写 AppData 内的 WSL 文件。Microsoft 警告这可能损坏 WSL 发行版；本方案只采用 Docker 官方明确允许的“完全停止 Desktop 后原样复制/放回 VHDX”。[Microsoft WSL disk space](https://learn.microsoft.com/windows/wsl/disk-space)

### 5.2 第二级：Reset to factory defaults

仅当第一级无法恢复且另行取得明确授权时执行。

**官方确认的影响**

- 把 Docker Desktop 的全部 options 恢复到首次安装时的初始状态。[Docker Desktop troubleshoot](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/)

**必须按 unknown 处理的影响**

Troubleshoot 页面没有逐项列出 factory reset 对 Docker data、WSL integration、代理凭据、Kubernetes、extensions、登录态或其他对象的保留/删除矩阵。由于 Docker 官方 backup/restore 页面明确建议先备份，再可执行 factory reset，应在风险评估中把 data disk 和 Desktop settings 都视作可能丢失。[Docker Desktop backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)

**回滚**

与第一级相同：完全停止 Desktop，恢复原路径的 `docker_data.vhdx`，按记录重新配置 Desktop；其他 WSL 发行版使用各自的 Microsoft `wsl --import` / `--import-in-place` 备份恢复流程。恢复 VHDX 前应保留失败后的新盘副本，避免覆盖唯一的取证证据。

## 6. 修复后验证顺序

以下是修复成功后的验收顺序。第 1 至 7 项最终均已通过；详细的最终证据与中间 red-capable 失败见第 0.9 节。

1. **Client/Server API**：`docker version` 必须同时返回 Client 与 Server；`docker --version` 只证明 CLI 存在，不足以证明 Engine 可用。[docker version](https://docs.docker.com/reference/cli/docker/version/)
2. **Engine 全局信息**：`docker info` 返回 server 信息，包括 containers/images 计数、kernel、storage driver、Docker Root Dir 等。[docker system info](https://docs.docker.com/reference/cli/docker/system/info/)
3. **临时容器探针**：使用唯一名称运行一个最小、可离线命中本地镜像的临时容器，核对退出码和标准输出；若必须 pull，单独区分 registry/proxy 故障与 Engine 故障。
4. **自建网络探针**：创建唯一命名 bridge network，把临时容器接入并核对网络 inspect/容器执行；`docker network create` 的默认 driver 是 bridge。[docker network create](https://docs.docker.com/reference/cli/docker/network/create/)
5. **清理并回读**：只删除本次唯一命名的 probe container/network，随后用精确名称回读为不存在；禁止使用 `prune`。
6. **共享资源回读**：重新列出 containers、images、volumes、networks 及 Compose labels，与恢复前清单对比；归属 unknown 的差异必须人工处置，不得自动删除。
7. **仓库门禁**：从仓库根目录、直接使用共享 Engine 原样运行 `pwsh ./scripts/check.ps1`。只有完整成功才能证明本仓库 canonical check 已恢复；单个容器探针或组件检查不能替代。

若某一步失败，应保存命令、时间、退出码、stderr、Docker Desktop diagnostics/logs 与当前设置摘要。Docker 官方支持从 Troubleshoot 生成 diagnostic ID，也列出了 Windows 日志目录 `%LOCALAPPDATA%\Docker\log`。[Docker Desktop troubleshoot](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/)

## 7. 风险与未知项总表

| 项目 | 当前可据官方资料下结论 | 必须保持 unknown 的部分 |
|---|---|---|
| `Clean / Purge data` | 重置全部 Docker data；丢失现有 settings；不是 factory reset | 每类对象的精确删除/保留矩阵 |
| Factory reset | 全部 Desktop options 回到初装状态 | Docker data、OS credential store、extensions 等逐项影响 |
| 整盘备份 | 停止 Desktop 后复制 `docker_data.vhdx`，恢复到同一路径 | 跨 Desktop 版本恢复的完整兼容矩阵、损坏 VHDX 的可恢复性 |
| `settings-store.json` | 官方确认 Windows 路径 | 直接文件覆盖是否为受支持恢复机制 |
| API 不通时的对象清单 | 完整 VHDX 可作为灾难恢复备份 | 容器/卷/镜像/Compose 的可靠对象级归属与可重建性 |
| customer-agent 数据 | 需由项目所有者单独确认 | 不能外推到任何其他项目 |

## 8. 验证范围与限制

- 本文于 2026-08-17 核对官方网页；Docker Desktop 行为会随版本变化，破坏性操作前应再次核对当前版本文档与 UI 警告。
- 已完成第 0 节列出的本机盘点和备份准入；设置仅做白名单提取，凭据和敏感原文未写入本文。
- 已离线复制并校验完整 VHDX，保存配置快照，并为 OpenGauss/MySQL 完成独立备份与实际恢复验证；备份过程中只启动/停止了明确归属的数据库容器和唯一命名 probe 资源。
- 已在用户最终确认后提交一次“仅 WSL 2”的 Clean/Purge，并在 UI 挂起后按授权重启 Docker Desktop；第 0.6 节的资源回读证明 Clean/Purge 未落地。
- 用户另行最终授权后，已执行官方 Factory Reset；共享 Engine/API 已恢复，旧 Docker data 已清空，必要的 WSL、storage driver、data disk 与 integration 设置已回读。未手工删除/替换 VHDX，未安装运行时，未修改产品代码。
- registry pull、临时容器、自建网络、Gradle/JVM 构建代理与原样 canonical check 均已恢复；第 0.8、0.9 节保留了从 Engine、registry、BuildKit、JVM 到运行容器内部 DNS/healthcheck 的分层 red/green 证据，没有用单点成功替代完整门禁。
- Docker 官方没有提供 Clean/Purge 与 Factory Reset 的逐对象保留矩阵；本文没有用经验或推测填补该空白。
- 本文没有涉及或启动任何产品 ticket。
