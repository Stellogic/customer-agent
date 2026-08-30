# Issue #190 A方案前置中止记录

关联 #190 / PR203。RunId `issue190-logistic-fit-20260831a`，受测干净HEAD `1c7b8a8a584ee919c52de52d2ddf73c2b7474768`，base `c19a7ebe8ec31f7ed21048ea75fbfcfd61df1472`。本轮结果为 **PRECONDITION_FAIL**，不是训练/校准质量FAIL，也不代表质量PASS。

## 实际执行与停止位置

- 训练144题/24篇、校准72题/12篇分别渲染为独立目录，manifest/seal哈希核对通过；未修改数据或方法。
- 本轮Python手算数值契约1项通过（0.04秒），Java特征2项/策略3项通过，JUnit XML已保存；Java测试阶段13秒。
- 本地固定BGE、真实PostgreSQL/FTS/pgvector/RRF路径已启动训练分区。9次安全探针HTTP请求中，匿名401、客户403；非当前版本/退役条目、条目范围/片段范围和请求越范围均按既定断言排除。
- 最后的“恢复后整个响应字典精确相等”断言失败。未执行之后的迁移history查询，未采集144/72题，未调用fit或选择门槛；没有新系数或唯一参数可交付。产品仍PENDING_CALIBRATION。
- 阶段251.339985秒，包括镜像依赖准备与清理，不是拟合时长。付费模型API费用0元；CPU/峰值内存/总流量未采集。本次没有下载模型权重，固定模型从既有目录只读加载。
- 自有Compose容器、卷、网络和3个镜像tag已清理；锁释放后单次FREE回读，已发LOCK_RELEASED并归还窗口。没有自动重试、读取留出、运行189/完整门禁或合入。

## 原始差异与有限结论

只读比较同一探针的 `legal_before` / `legal_restored` 原始响应：候选数量、顺序、ID、正文、版本/范围、四特征、向量分数和RRF分数一致；唯一差异为全文float4分数在JSON中的double表示，例如 `1.9` / `1.899999976158142`、`0.3` / `0.30000001192092896`。原始报告的三个分项PASS不能覆盖最后断言FAIL，整体报告保持FAIL。

PostgreSQL明确 `ts_rank_cd` 返回float4；pgJDBC默认在达到prepareThreshold后启用服务端预备语句并可使用二进制传输。它们支持“同一float4值经文本/二进制路径转double产生不同表示”的解释，但本轮未抓取协议或固定连接复现实验，传输切换仍是推断。[PostgreSQL排名函数](https://www.postgresql.org/docs/18/textsearch-controls.html#TEXTSEARCH-RANKING) / [pgJDBC预备语句](https://jdbc.postgresql.org/documentation/server-prepare/) / [驱动参数](https://jdbc.postgresql.org/documentation/use/)

已确认的缺陷是一次性安全探针对全文诊断分数使用了比数据库类型契约更严格的整份double精确比较。没有证据显示过滤失效、RRF改变、训练与运行四特征不一致或A方法质量不足；A尚未拟合，不能作这些结论。

最小修正只在探针比较时将全文 `score/lexicalScore` 恢复为其声明的float4后精确比较；其他字段、四特征、向量/RRF分数仍要求精确相等。原始响应不改写，不加经验epsilon，不修改产品代码、特征、训练数据或任何质量阈值。修正须静态双CR并提交，重新获取阶段窗口后方可执行；本轮失败不能追认PASS。新RunId继续保留此次未拟合的尝试，仍只允许一次实际拟合/唯一校准。

## 可核对证据

[原始安全探针、阶段记录、数值契约日志/XML及SHA索引](evidence/issue190-logistic-fit-20260831a/index.json)。实际运行计划快照见提交 `73d9aeb` 下 `evidence/issue190-logistic-run-plan/`。模型revision `7999e1d3359715c523056ef9478215996d62a620`，seal文件SHA256 `0fc933afdb217763d51bfe3989482cf2c512c0a0d9829852ba9508190768189a`；后者是元数据文件哈希，不是72题内容哈希。

环境：宿主Windows/CPython3.13.13，Docker Linux/CPython3.13.14、Gradle9.3.1/JDK25、PostgreSQL18/pgvector0.8.6镜像；细节和包版本见日志。真实运行只针对本地合成开发资料，不是生产规模、线上收益或用户逐行手写代码的证据。
