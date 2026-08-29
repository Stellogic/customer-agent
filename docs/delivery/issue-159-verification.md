# Issue #159 交付验证

## 交付范围

- Spring 以当前工单代次、机器身份、操作权限和稳定请求身份授权公开回复流，持久化 `LOADING`、受控进度、`STREAMING`、内容片段及终态。
- DeepSeek Responses API 使用供应商原生 SSE；Agent 只从 `response.output_text.delta` 中提取并发布仍匹配授权回复集合的正文前缀，不再切割已经生成完毕的文本冒充流式。
- 每个内容片段必须持续匹配 Spring 允许的安全回复前缀；完整回复必须精确匹配受控叙事，调查结论获 Spring 接受的同一事务内才落为完成态。
- `public-conversation-v2` 快照与 SSE 共同恢复当前代次的回复正文、阶段和状态；旧代次、重复请求、乱序片段、非法状态转换及越界正文均被拒绝。
- 客户界面使用 Ant Design X 的 `Conversations`、`Bubble`、`Sender` 与 `Sources`；仅引入 UI 组件包，不引入完整 X SDK。
- 公开来源为受控业务类别，不包含 prompt、reasoning、原始工具响应、checkpoint、provider 或内部运行标识。

## 关键顺序

1. Agent 先发布加载状态，再按“理解问题、核对事实、查询规则、整理回复”推进公开阶段。
2. DeepSeek 的真实输出增量进入 Agent 后，只有可证明属于授权正文前缀的新字符才作为内容片段提交；Spring 对累积正文逐段重新授权后才写入公开事件。
3. Spring 接受完整调查结论时，在同一事务内核对流正文、写入 `COMPLETED` 产品事件并持久化正式公开消息；转人工事务同样先把未完成流收敛到 `FAILED` 或 `ABORTED`，不存在依赖第二次网络请求补终态的窗口。
4. 浏览器只消费 Spring 快照和 SSE；断线、游标缺口、旧事件或 schema 不兼容沿用 v2 的整体快照恢复，不直接连接模型或 Agent Server。

## 验证矩阵

- Backend：事件字段白名单、机器作用域、幂等冲突、代次围栏、片段顺序、终态状态机、安全叙事前缀与快照恢复。
- Agent：DeepSeek 原生 SSE 事件、真实增量发布、授权前缀、单调事件序号、完整结构回读、四阶段进度、异常失败及稳定事件身份。
- Frontend：慢首字加载、增量正文、完成/失败/中止状态、当前代次恢复、旧代次忽略、缺口重同步、敏感字段拒绝和 Ant Design X 组件兼容。
- Chromium：桌面与窄屏下覆盖慢首字、断线刷新后的权威续流、完成、失败、中止及无横向溢出。

## 最终门禁

- `pwsh ./scripts/check.ps1`：待正式交付阶段仅运行一次并回填结果。

## 聚焦预检

- Agent 测试镜像：ruff format、ruff lint、pyright 与 216 项 pytest 全部通过。
- Backend 测试镜像：checkstyle、Spotless 与 Gradle 全量测试全部通过。
- Frontend 测试镜像：Prettier、ESLint、TypeScript、107 项测试与生产构建全部通过；其中包括完成事件真实顺序与刷新快照恢复回归覆盖。
