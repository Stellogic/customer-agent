# 版本化知识目录

Issue #166 的第一阶段知识源位于 `backend/src/main/resources/knowledge/`。每个 `.md` 文件都使用严格的 YAML 风格 front matter：

```text
---
id: stable-article-id
title: 中文标题
version: v1
updated_at: 2026-08-28T00:00:00Z
applicability: [INTERNAL, SUPPORT]
status: PUBLISHED
current: true
---
正文
```

Spring 启动时先解析并校验全部条目，再在一个事务中重建数据库索引。解析失败或写入失败会保留上一份完整索引并把索引状态标为 `FAILED`；`READY` 或成功重建后的 `EMPTY` 索引才可返回检索结果。删除全部源文件会清空条目并进入 `EMPTY`，不会把一次正常删除误报成失败。相同内容重复重建不会产生重复分段。

`current: true` 必须恰好对应每个稳定 `id` 的一个已发布版本。旧版本保留在索引中供审计，但普通检索只使用当前已发布版本。编辑、审核、发布和回滚目前只在内部页面显示“开发中”，不会写入内容。

已进入索引的 `(id, version)` 视为不可变版本；需要更新正文、元数据或源文件时应提交新的版本号。这样可避免原地改写后旧引用失去可审计内容。
