# PROTOTYPE — 流式事件与断线恢复契约

> Throwaway prototype：只用于回答“Spring 白名单产品事件 + 权威快照 + SSE
> 重放”的状态模型能否覆盖重复、乱序、断线、代次替换和权限撤销。

本原型不连接 React、Spring Boot 或 LangGraph，也不是生产实现。它把上游原始事件投影为受控产品事件，并用纯 reducer 模拟浏览器如何消费快照和增量事件。

## 一条命令运行

```powershell
python prototypes/stream-recovery-contract/run_prototype.py --all
```

交互查看状态：

```powershell
python prototypes/stream-recovery-contract/run_prototype.py
```

交互模式每次动作后都会重绘完整状态。输入 `h` 查看动作列表，输入 `q` 退出。

## 要验证的问题

1. 原始 prompt、模型输出、工具 payload、checkpoint 和内部资源 ID 能否在投影边界被结构性排除。
2. 重复事件不产生第二次变化，序号缺口或 epoch 变化不会被静默越过。
3. 新 generation 生效后，旧 generation 的迟到事件不会改变当前页面。
4. 断线后能从最后游标重放；游标不可用时回到权威快照，而不是猜测状态。
5. 权限撤销后停止投递；重新查询快照返回拒绝，旧连接不能继续泄露数据。
6. 客户、客服和审批视图各自编号，过滤不可见事件不会制造伪序号缺口。

详细决策草案见 [CONCLUSION.md](CONCLUSION.md)。
