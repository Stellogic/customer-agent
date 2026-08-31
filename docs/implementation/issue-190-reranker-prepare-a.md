# #190 固定 reranker 准备 a：下载前置失败

2026-08-31；[Issue #190](https://github.com/Stellogic/customer-agent/issues/190) / [PR203](https://github.com/Stellogic/customer-agent/pull/203)。RunId `issue190-reranker-prepare-20260831a`，受测HEAD `cf87a6b6d25a65974c9ea1986214d1bd8ec50298`，源码 `04d7ee9c7129e00741db22f04ccc72492253738e`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`；二者之间只有[离线证据归档](issue-190-reranker-offline.md)，模型方法与代码未改。

**PREPARATION_ERROR，不是模型或语义质量FAIL。** 通过正式PowerShell入口取得共享锁并通过Python继承锁校验后，按固定revision下载模型。`config.json`已保存799字节；`model.safetensors`下载到204,766,396字节时，对端关闭连接，预期完整长度1,112,206,140字节。httpx抛出 `RemoteProtocolError: peer closed connection without sending complete message body`。这只证明本次下载连接中断，不证明模型无效或供应商整体不可用。

运行前检查本工作树、共享本地模型目录及标准HF缓存路径，未发现可直接复用的该revision模型目录；没有改用其他来源/版本。下载入口使用既有certifi证书包正常校验TLS，不禁用证书校验、不包含真实业务数据。未自动重试、换RunId或补下载。

模型准备尚未完成五文件校验，未加载模型，后续 `issue190-reranker-development-20260831a` **未开始**，阈值选择次数0，`completed_queries=0`、`metrics=null`。原RRF、72题与选择规则、默认产品、旧失败与共享预算不变；未读留出或189。真实付费API调用0、新增API费用0，未读取或修改共享活账本。墙钟436.16秒，Python阶段431.61秒；内存/CPU峰值未采集。

原始失败及阶段报告保存在[证据目录](evidence/issue190-reranker-prepare-20260831a/index.json)。日志仅替换工作树/用户目录前缀；源文件及归档文件hash均记录，原始日志仍在本地RunId目录。部分权重留在工作树 `.local/models/bge-reranker-base/`，未校验、不可加载、不提交Git、不清理；其SHA未采集。后续如果协调另行安排准备复验，应先保留这个失败和部分文件，再准备同一固定模型，不能通过换模型或改变评分方法掩盖此失败。

进程退出后释放自身锁，只读一次确认当时FREE，已通知 `LOCK_RELEASED` 并归还窗口。本阶段到此停止；不运行development、独立验证、冻结门或完整门禁，不合入关票或解阻。记录由Codex整理，用于可复核工程过程与面试材料，不代表生产成果或用户逐行手写。
