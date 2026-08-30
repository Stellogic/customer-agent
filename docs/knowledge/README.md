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

Spring 启动时先解析并校验全部条目，再在一个事务中重建数据库索引。解析失败或写入失败会保留上一份完整索引并继续按上一份 `READY` 或 `EMPTY` 目录提供检索，只记录失败原因；仅当从未形成可检索目录时才把状态标为 `FAILED`。删除全部源文件会清空条目并进入 `EMPTY`，不会把一次正常删除误报成失败。相同内容重复重建不会产生重复分段。知识分段与条目一样保留适用范围。

`current: true` 必须恰好对应每个稳定 `id` 的一个已发布版本。旧版本保留在索引中供审计，但普通检索只使用当前已发布版本。编辑、审核、发布、回滚和读者侧重建索引目前只在内部页面显示“开发中”，不会写入内容。索引只在服务启动时由仓库内 Markdown 重建。

已进入索引的 `(id, version)` 内容及稳定元数据视为不可变版本；`status` 与 `current` 是发布生命周期字段，可在发布新版本或下线旧版本时调整。需要更新正文、标题、更新时间、适用范围或源文件时应提交新的版本号。这样可避免原地改写后旧引用失去可审计内容。

中文检索质量基线 `rag-eval-v1` 见 [`docs/eval/rag-eval-v1.md`](../eval/rag-eval-v1.md)。该基线在实现 Embedding 或混合检索之前冻结；纠错必须保留原哈希。
