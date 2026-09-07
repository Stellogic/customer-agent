# 四角色统一使用 DeepSeek Pro

按用户决定，正式受理、行动选择、调查判断和客户回复统一使用 `deepseek-v4-pro`。

- 本地正式配置设置 `DEEPSEEK_MODEL=deepseek-v4-pro`。回复角色未单独指定模型时跟随此值。
- `scripts/issue230-real-core.ps1` 默认选择 Pro；显式 `-Model deepseek-v4-flash` 仍可读取对应历史配置。每次执行必须与冻结账本模型一致。
- 人民币预算按请求模型预留与结算：Pro 非缓存峰价输入 9、输出 27 微元/token。旧 Flash 账本继续使用原来的价格，不能重置或挪用。
- 模型名称、请求记录和模式标签反映真实选择；旧美元汇总中无法完整估计的费用保持未知，不把 Pro 套用 Flash 价格。

价格来源：[DeepSeek 官方定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，核对日期 2026-09-07。这里是程序估算，不是供应商账单。

默认固定模型测试仍不调用供应商。模型切换本身不代表真实产品验收通过；#230 仍需完整矩阵证据，#174 继续暂停。
