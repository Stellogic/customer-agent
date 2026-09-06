# #174 第11轮结果

INCOMPLETE，受测33fb8f9658857f87cf21786c29ed86bf9bb1fbc6，基线474e6068ca1f562a60d67518bba1619a1a3582ef。第一场景浏览器通过，但两项调查均转人工，后四场景NOT_RUN。

行动失败元数据定位actionFailureLine=604，对应 `action not in allowed_actions`：一次HTTP200、completed响应选择了本轮集合外动作，输出14 token。不能据此回填run10的未知分支。另一次重复扣款结论被Spring以INVALID_EVIDENCE_APPLICABILITY拒绝；完整声明未保存，具体缺项或绑定未知。单次诊断通过没有证明五场景通过。

模型15次HTTP200，行动13/判断1/回复1；含受理代理计数为18逻辑调用/18尝试，14866已知token，usageTrusted=true。程序费用上界0.110015元不是实扣。整轮1元保留PENDING，现31笔预留；历史核对上界2元加后续预留12元为14元，累计上限16.12元内剩余2.12元。旧冻结和失败保留，禁止重跑run11。

见[报告](issue-174-live-report-11.json)、[指标](issue-174-live-11-formal-metrics.json)。后续候选将本轮允许动作与当前场景既有证据要求放入显式请求上下文，仍由模型选证据、Spring校验，不自动补证据或放宽校验。请求契约离线回归不同于真实效果验证。
