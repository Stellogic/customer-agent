# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: issue190.hybrid-retrieval.spec.ts >> Issue #190 显式未授权范围返回权限错误而非空结果
- Location: e2e/issue190.hybrid-retrieval.spec.ts:124:1

# Error details

```
Test timeout of 30000ms exceeded.
```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - generic [ref=f1e5]:
      - link "Stellogic 内部工作台" [ref=f1e6] [cursor=pointer]:
        - /url: /internal
        - generic [ref=f1e11]:
          - strong [ref=f1e12]: Stellogic
          - generic [ref=f1e13]: 内部工作台
      - navigation "内部工作区" [ref=f1e14]:
        - menu [ref=f1e15]:
          - menuitem [ref=f1e16] [cursor=pointer]:
            - link "客服工作区" [ref=f1e18]:
              - /url: /internal/support
              - generic [ref=f1e19]: 服
              - text: 客服工作区
          - menuitem [ref=f1e20] [cursor=pointer]:
            - link "知识目录" [ref=f1e22]:
              - /url: /internal/knowledge
              - generic [ref=f1e23]: 知
              - text: 知识目录
      - paragraph [ref=f1e24]: 按当前职责显示工作区入口
    - img "left" [ref=f1e26] [cursor=pointer]
  - generic [ref=f1e29]:
    - banner "内部工作台" [ref=f1e30]:
      - generic [ref=f1e31]:
        - strong [ref=f1e32]: 统一内部工作台
        - generic [ref=f1e33]: 当前工作人员：演示客服
      - generic [ref=f1e34]:
        - generic [ref=f1e35]: 安全会话
        - button "退出登录" [ref=f1e36] [cursor=pointer]
    - main [ref=f1e37]:
      - main "知识目录工作区" [ref=f1e38]:
        - generic [ref=f1e39]:
          - generic [ref=f1e40]:
            - paragraph [ref=f1e41]: KNOWLEDGE CATALOG
            - heading "版本化知识目录" [level=1] [ref=f1e42]
            - paragraph [ref=f1e43]: 从真实中文 Markdown 条目检索规则说明，查看版本、适用范围和可回到源文件的引用片段。
          - generic [ref=f1e44]: 索引就绪 · 4 条目
        - region "中文混合检索" [ref=f1e45]:
          - heading "中文混合检索" [level=2] [ref=f1e46]
          - paragraph [ref=f1e47]: 在当前身份可读、当前已发布的知识片段中检索；全文与离线 BGE 候选经 RRF 融合。
          - generic [ref=f1e48]:
            - generic [ref=f1e49]: 检索问题
            - generic [ref=f1e50]:
              - textbox "检索问题" [ref=f1e51]:
                - /placeholder: 例如：客户问退款是不是已经到账，怎么说明？
                - text: 物流延迟
              - button "混合检索" [ref=f1e52] [cursor=pointer]
            - generic [ref=f1e53]: 检索适用范围
            - combobox "检索适用范围" [ref=f1e54]:
              - option "内部规则"
              - option "客服规则（需当前身份授权）"
              - option "审批规则（需当前身份授权）" [selected]
          - alert [ref=f1e55]: 当前身份无权检索所选适用范围。
        - region "知识检索" [ref=f1e56]:
          - search [ref=f1e57]:
            - generic [ref=f1e58]: 关键词
            - generic [ref=f1e59]:
              - textbox "关键词" [ref=f1e60]:
                - /placeholder: 例如：物流延迟、部分退款
              - button "检索知识" [ref=f1e61] [cursor=pointer]
          - paragraph [ref=f1e62]: 普通检索只使用当前已发布版本；历史版本需要从条目详情进入审计查看。
        - generic [ref=f1e63]:
          - region [ref=f1e64]:
            - generic [ref=f1e65]:
              - generic [ref=f1e66]:
                - paragraph [ref=f1e67]: SEARCH RESULTS
                - heading "当前知识条目" [level=2] [ref=f1e68]
              - generic [ref=f1e69]: 3 条引用
            - list [ref=f1e70]:
              - listitem [ref=f1e71]:
                - 'button "物流延迟处理说明 v2 logistics-delay · INTERNAL、SUPPORT · 更新于 2026年8月28日 # 物流延迟 knowledge/logistics-delay-v2.md · 第 10–10 行 · 全文命中" [ref=f1e72] [cursor=pointer]':
                  - generic [ref=f1e73]:
                    - strong [ref=f1e74]: 物流延迟处理说明
                    - generic [ref=f1e75]: v2
                  - generic [ref=f1e76]: logistics-delay · INTERNAL、SUPPORT · 更新于 2026年8月28日
                  - generic [ref=f1e77]: "# 物流延迟"
                  - generic [ref=f1e78]: knowledge/logistics-delay-v2.md · 第 10–10 行 · 全文命中
              - listitem [ref=f1e79]:
                - 'button "补偿审批审查要点 v1 approval-review · INTERNAL、APPROVER · 更新于 2026年8月28日 # 补偿审批 knowledge/approval-review-v1.md · 第 10–10 行 · 全文命中" [ref=f1e80] [cursor=pointer]':
                  - generic [ref=f1e81]:
                    - strong [ref=f1e82]: 补偿审批审查要点
                    - generic [ref=f1e83]: v1
                  - generic [ref=f1e84]: approval-review · INTERNAL、APPROVER · 更新于 2026年8月28日
                  - generic [ref=f1e85]: "# 补偿审批"
                  - generic [ref=f1e86]: knowledge/approval-review-v1.md · 第 10–10 行 · 全文命中
              - listitem [ref=f1e87]:
                - 'button "部分退款沟通规范 v1 refund-policy · INTERNAL、SUPPORT、APPROVER · 更新于 2026年8月27日 # 部分退款 knowledge/refund-policy-v1.md · 第 10–10 行 · 全文命中" [ref=f1e88] [cursor=pointer]':
                  - generic [ref=f1e89]:
                    - strong [ref=f1e90]: 部分退款沟通规范
                    - generic [ref=f1e91]: v1
                  - generic [ref=f1e92]: refund-policy · INTERNAL、SUPPORT、APPROVER · 更新于 2026年8月27日
                  - generic [ref=f1e93]: "# 部分退款"
                  - generic [ref=f1e94]: knowledge/refund-policy-v1.md · 第 10–10 行 · 全文命中
          - complementary "知识条目详情" [ref=f1e95]:
            - generic [ref=f1e96]:
              - generic [ref=f1e97]: ↳
              - paragraph [ref=f1e98]: ARTICLE DETAIL
              - heading "选择一条知识引用" [level=2] [ref=f1e99]
              - paragraph [ref=f1e100]: 这里会展示真实正文、可审计版本以及每个分段的源文件位置。
        - region [ref=f1e101]:
          - generic [ref=f1e102]:
            - paragraph [ref=f1e103]: OPERATIONS ROADMAP
            - heading "内容运营入口" [level=2] [ref=f1e104]
            - paragraph [ref=f1e105]: 第一阶段只提供真实查看、检索、版本和引用；内容变更仍通过仓库审阅。
          - generic [ref=f1e106]:
            - button "编辑（开发中）" [ref=f1e107] [cursor=pointer]
            - button "审核（开发中）" [ref=f1e108] [cursor=pointer]
            - button "发布（开发中）" [ref=f1e109] [cursor=pointer]
            - button "回滚（开发中）" [ref=f1e110] [cursor=pointer]
            - button "重建索引（开发中）" [ref=f1e111] [cursor=pointer]
```