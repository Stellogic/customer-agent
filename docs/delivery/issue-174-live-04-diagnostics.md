# #174 第4轮后的诊断与知识检索修复依据

第4轮仍为 INCOMPLETE。本记录补充合成场景观察，不回写旧失败，不将诊断算作五场景发布通过。

- 诊断05：单次真实客户回复适配器返回合法 envelope，未复现第4轮失败。
- 诊断06：L174-01浏览器建单通过；后台两代次为1 COMPLETED/1 HANDED_OFF，记录PROVIDER_REQUEST_REJECTED，不能推断精确HTTP状态。
- 诊断07：L174-02未出现自动解决取消按钮，代次因TOOL_RETRY_EXHAUSTED转人工，后三场景未执行。

临时stdout标记受既有logging.driver=none影响未被收集，空parseFailures不能证明没有解析失败。后续无付费的真实检索路径复现确定了任务槽自等待，显式并发参数修复的复现依据见[知识检索并发说明](agent-nested-knowledge-concurrency.md)，由[#224](https://github.com/Stellogic/customer-agent/issues/224)和[PR #225](https://github.com/Stellogic/customer-agent/pull/225)交付。

正式验收增加已持久化knowledge_failure的聚合，单列知识失败。每场景后若已记录模型或检索失败，立即停止后续场景。模型、提示、五场景和业务断言不变；完整诊断及费用原记录保留在本地。
