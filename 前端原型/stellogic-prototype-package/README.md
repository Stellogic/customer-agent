# Stellogic Customer Support Agent · 高保真 HTML 原型

## 使用方式

直接双击 `index.html` 即可打开。页面右下角有“原型导航”，可在全部页面和关键状态之间切换；所有页面都在同一个静态文件中，不需要安装依赖或启动服务。

这是纯 HTML / CSS / JavaScript 原型，使用模拟数据，不调用后端接口。

## 已覆盖页面

### 客户侧

- `#/help/login`：客户登录
- `#/help`：帮助中心首页 / 创建工单
- `#/help/ticket/investigating`：AI 正在调查
- `#/help/ticket/clarification`：等待客户补充信息
- `#/help/ticket/human`：人工客服处理中

### 内部工作台

- `#/internal/login`：内部人员登录
- `#/internal`：双角色工作区选择
- `#/internal/support`：客服共享队列
- `#/internal/support/ticket`：客服工单详情
- `#/internal/approvals`：补偿审批队列
- `#/internal/approvals/detail`：补偿审批详情

### 状态页面

- `#/states`：Loading、Empty、Error、断线、重新同步、租约过期、成功、结果未知等状态组件
- `#/403`
- `#/404`

## 可交互部分

- 登录表单与演示账号填充
- 创建工单并进入调查状态
- 提交客户澄清信息
- 申请转人工
- 客服队列搜索、选择和领取工单
- 审批队列搜索和进入详情
- 批准、驳回、释放审批责任的确认弹窗
- 模拟实时重新同步与 Toast 反馈

## 视觉与组件实现建议

### 设计基调

- 品牌色：森林绿、深海军绿、米白、浅鼠尾草绿
- 客户侧：温暖、轻量、解释性更强
- 内部工作台：结构化、高信息密度、强调状态和下一步动作
- 标题使用宋体/衬线字体，正文使用系统无衬线字体
- 避免紫色渐变、夸张 AI 光球和纯卡片堆叠

### React / Ant Design 映射

- 壳层：`ProLayout` / `PageContainer`
- 队列表格：`ProTable`
- 工单预览：`Drawer` 或固定侧栏
- 过滤：`ProForm`、`Select`、`Input.Search`、`DatePicker.RangePicker`
- 状态：`Tag`、`Badge`、`Alert`、`Result`、`Skeleton`、`Empty`
- 进度：`Steps`、`Timeline`
- 描述信息：`Descriptions`
- 高风险操作：`Modal.confirm`
- 提交反馈：`message` / `notification`

## 业务边界提醒

- 客户页面不得展示内部调查、审批证据、内部备注或技术字段。
- 客服领取工单前只展示裁剪后的队列摘要。
- 审批证据只能在领取当前提案且租约有效时展示。
- 租约失效后应立即移除证据和审批按钮。
- UUID、cursor、generation、lease token 等技术字段不得直接展示。
- 前端菜单隐藏不等于授权，最终权限必须由 Spring 后端校验。
- 操作结果未知时不要鼓励重复提交，应使用幂等查询确认最终状态。
