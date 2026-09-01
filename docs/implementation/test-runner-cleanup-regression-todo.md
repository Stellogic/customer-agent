# 测试执行器清理回归 TODO

状态：开发阶段暂缓，不阻塞当前业务实现。

背景：#169 的一次专属测试执行器在独立 Compose 项目名初始化前失败，`finally` 中未指定项目名的 `docker compose down --volumes` 回退到默认 `customer-agent-baseline`，误删了本地演示环境的数据卷。

当前最低安全边界继续保留：测试必须使用显式独立项目名；空项目名和 `customer-agent-baseline` 必须被拒绝；本票 Compose 未启动时不得执行清理。

后续补充最小 RED/GREEN 回归：模拟预检提前失败，证明不会调用默认项目清理；模拟独立项目正常结束，证明只删除本票容器、网络和卷。完成前 baseline 只保存可重建的演示数据。
