# 原型验证矩阵

运行命令：

```powershell
python prototypes/stream-recovery-contract/run_prototype.py --all
```

| 场景 | 必须成立的不变量 |
|---|---|
| `white_list_projection` | 私有 prompt、模型输出、工具 payload、checkpoint 和内部 run ID 不进入产品事件 |
| `duplicate_is_idempotent` | 相同或更小序号不会再次改变投影 |
| `gap_requires_snapshot` | 序号缺口使 reducer 停止应用增量并要求快照 |
| `replay_after_snapshot` | 权威快照替换本地状态后，可从其下一序号继续重放 |
| `stale_generation_ignored` | 旧 generation 迟到事件不改变当前页面 |
| `permission_revocation_stops_delivery` | 权限撤销关闭流，后续事件不再生效 |
| `epoch_change_requires_snapshot` | 不同 epoch 不能混合应用 |
| `unknown_raw_event_is_dropped` | 未列入映射的 LangGraph/Agent 原始事件默认丢弃 |
| `malformed_product_event_requires_snapshot` | 含额外或敏感字段的产品事件不被部分应用，客户端转而获取权威快照 |
| `role_scoped_stream_avoids_filtered_gaps` | 客户公开流过滤内部调查事件后仍使用自身连续序号，不因看不见的事件产生伪缺口 |

本矩阵是纯状态模型验证，不代表 Spring、浏览器或代理链路的运行结果。
