# #226 证据适用性提示补充

## 已知问题与边界

#174 run09 的 Spring 拒绝码为 INVALID_EVIDENCE_APPLICABILITY，被拒绝风险场景为 DUPLICATE_CHARGE。模型请求均 HTTP 200；未保存完整证据声明，因此具体缺项或错误绑定未知，不能认定提示遗漏是该次失败的唯一根因。

现有 action v4 提示仅明确列举物流延迟场景的必需适用性。Spring 的 `EvidenceSufficiencyPolicy` 对支付、包裹未收到和订单规则场景另有要求。解析器保留模型提供的 applicability，结论合并也只去重，不补充或删除有效声明；静态检查未发现这里丢项的实现缺陷，但无法据此重建 run09 输出。

## 最小候选改动

action prompt 升级为 investigation-action-v5，补充 Spring 已有场景要求：支付需分别声明 PAYMENT_STATUS、ORDER_ELIGIBILITY、REFUND_STATUS；未收到包裹需 LOGISTICS_STATUS；订单规则需 ORDER_RULE。各场景的订单、政策和待执行等要求按现有 Spring 策略列出。模型仍自主选择目录证据并声明适用性，Spring 校验保持不变。未新增模型调用或重试，schema 和业务权限不变。

当前 run09 冻结及其 action v4 版本保持不变，目录已禁用重跑。候选提示不能沿用 run09 的旧授权或被记作真实验收通过；下一次运行须单独获得授权，并冻结 v5 及其受测 HEAD。预算累计 12 元，28 笔旧 PENDING 保留。

## 验证

本次为基于权威策略的提示契约补充，真实问题仅在付费运行中出现；未保存完整声明，无法精确离线回放，也不伪造红绿模型复验。沿用现有真实适配器、graph 证据传播和 Spring 场景校验测试验证回归；Agent 聚焦镜像检查通过：ruff format/check、pyright、470 passed / 3 skipped（日志 `.local/issue174-action-v5-focused.log`）；Spring 策略未修改，本轮未重复 Backend 全组件检查。真实效果和最终完整门禁均 NOT_RUN。

Standards PASS、Spec PASS（当前增量静态审查）。
