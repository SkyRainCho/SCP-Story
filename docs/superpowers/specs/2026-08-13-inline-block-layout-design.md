# EPUB 安全 inline-block 布局保留设计

## 问题与根因

SCP-3934 的“外务部制备”标题卡在原网页中使用内联样式
`display: inline-block`，父级折叠面板使用 `text-align: center`。这两个声明共同使
标题卡按内容宽度收缩并水平居中。

当前 EPUB 清洗器不允许 `display` 属性，因此标题卡在清洗后退化为普通块级元素，
占满整行。父级居中规则仍然存在，但无法移动一个等宽块，最终表现为图标和标题偏左。

## 选定方案

扩充内联样式白名单，仅允许安全值 `display: inline-block`。其他 `display` 值仍然删除，
特别是 `display: none` 不得被保留，以免隐藏模板或交互内容重新进入 EPUB。

实现应在样式值清洗阶段做值级判断，而不是把整个 `display` 属性无条件加入通用白名单。
这恢复原网页的收缩宽度布局语义，也避免为 SCP-3934 添加页面专用规则。

未选择的方案是只对 SCP-3934 标题卡添加专用样式。该方案影响范围较小，但会把通用的
安全样式丢失问题固化为页面特判，其他使用相同布局的文档仍会错误渲染。

## 影响范围

扫描口径是：当前 `data/manifests/` 已收录、在 `data/raw/pages/` 有缓存，并且
`#page-content` 内某个元素的内联 `style` 含有值为 `inline-block` 的 `display`
声明。页面 `<style>` 中的公共 CSS 不计入。

扫描结果：所有当前 manifest 共 252 篇文档、1115 个节点。完整机器可读清单位于
`output/reports/inline-block-affected-pages.json`。

Featured 精选集受影响的 13 篇文档如下：

1. `scp-3934` — SCP-3934 - 尼斯湖水怪有售（1 个节点）
2. `scp-4612` — SCP-4612 - 并非所有的神都会腐朽（1 个节点）
3. `scp-4793` — SCP-4793 - 石碑（14 个节点）
4. `scp-5952` — SCP-5952 - 校内外的Warbalang（1 个节点）
5. `scp-5550` — SCP-5550 - 我，辛格，我被收集的躯体（4 个节点）
6. `scp-6183` — SCP-6183 - 黑 色 匣 子（32 个节点）
7. `scp-6468` — SCP-6468 - dado 的 pvp 药水（3 个节点）
8. `scp-6747` — SCP-6747 - 混沌学说（1 个节点）
9. `site-14-secure-facility-dossier` — 安保设施档案：Site-14（1 个节点）
10. `experiment-log-914-hub` — 安保设施档案：Site-19 Facility 23（3 个节点）
11. `black-queen-hub` — 黑皇后（1 个节点）
12. `factory-hub` — 工厂（1 个节点）
13. `gru-p-hub` — 格鲁乌“P”部门（1 个节点）

Series 4 的 `3000-3999` 第10册中，除 SCP-3934 外还会影响 SCP-3937、SCP-3995
和 SCP-3999。其他 Series 卷册中的完整范围以机器可读清单为准。

## 测试与验证

1. 新增清洗测试，证明 `display: inline-block` 被保留。
2. 同一测试证明 `display: none`、`display: block` 和其他未许可值仍被删除。
3. 新增 SCP-3934 最小结构回归，证明标题卡保留 `display: inline-block`，父级页面样式
   保留 `text-align: center`。
4. 运行完整测试套件。
5. 重建 Featured 普通 EPUB 与 Kindle Scribe 稳定版。
6. 检查两种 EPUB 中 SCP-3934 的 XHTML，并对渲染结果进行视觉核验；同时抽查
   Featured 中节点数较多的 SCP-4793 与 SCP-6183，避免产生明显布局回归。

## 非目标

- 不恢复任意 `display` 值。
- 不改动全局正文对齐、折叠面板展开逻辑或图片尺寸规则。
- 不加入 SCP-3934 专用 layout profile。
