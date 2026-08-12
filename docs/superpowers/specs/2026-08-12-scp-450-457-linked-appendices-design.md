# SCP-450 与 SCP-457 原文附属文档收录设计

## 背景与目标

为 Featured 精选集与 Series 1 增加三项显式原文附属文档：

- `SCP-457` 下收录 `SCP-1689`（`https://scp-wiki-cn.wikidot.com/scp-1689`）。
- `SCP-457` 下收录 `SCP-124`（`https://scp-wiki-cn.wikidot.com/scp-124`）。
- `SCP-450` 下收录 `在恐惧中永世逃亡`（`https://scp-wiki-cn.wikidot.com/but-when-they-opened-it-they-turned-and-swift`）。

三个目标页面均已有中文站缓存，页面标题和 slug 已从实际 HTML 核实。它们是本次指定的关联材料，不通过放宽全局自动扫描规则来识别。

## 方案选择

在 `config/featured-scp.yaml` 与 `config/series-1.yaml` 中使用现有 `explicit_linked_appendices`：

```yaml
explicit_linked_appendices:
  scp-450:
    - title: 在恐惧中永世逃亡
      url: https://scp-wiki-cn.wikidot.com/but-when-they-opened-it-they-turned-and-swift
  scp-457:
    - title: SCP-1689
      url: https://scp-wiki-cn.wikidot.com/scp-1689
    - title: SCP-124
      url: https://scp-wiki-cn.wikidot.com/scp-124
```

该方案复用现有配置模型、分组、抓取和去重逻辑，不修改 `linked_appendices.py` 或流水线实现。

未采用的方案：

- 放宽自动扫描规则：会把普通 SCP 交叉引用纳入候选，违反当前保守扫描约束。
- 在流水线中硬编码页面关系：绕过配置模型，后续维护困难。

## 构建行为

1. SCP-450 主文档后插入 `scp-450--linked-appendices` 分组，其下加入 `but-when-they-opened-it-they-turned-and-swift`。
2. SCP-457 主文档后插入 `scp-457--linked-appendices` 分组，其下依配置顺序加入 `scp-1689`、`scp-124`。
3. 配置附件与自动扫描结果沿用现有 slug 去重逻辑，同一页面只抓取、只收录一次。
4. 附件只展开一层，不追踪附件页面中的链接。
5. 两份配置采用相同声明，因此 Featured 与 Series 1 的普通及 Kindle 构建共享该行为。

## 错误处理

附件抓取失败时沿用现有处理：保留 SCP 主文档，将失败写入构建报告，不生成空白附件正文。本次不增加 fallback 或浏览器抓取行为。

## 测试与验收

- 配置测试精确检查两份 YAML 中三个附件的标题、URL、slug 与 SCP-457 附件顺序。
- 流水线测试检查两个主文档各自形成独立的“原文附属文档”分组。
- 检查 SCP-457 的附件顺序为 `scp-1689`、`scp-124`，三个附件均只出现一次。
- 检查显式声明与扫描候选重复时仍只抓取、收录一次，且不递归展开。
- 运行目标测试、完整 `pytest -q`，并构建 Featured 与 Series 1 `400-499` 实际 EPUB。
- 检查报告顺序、`missing_pages` 与 EPUB 正文，确认三个附件位于正确父级且内容存在。

## 非目标

- 不改变全局高置信附属文档扫描规则。
- 不修改四篇 SCP 主文档或故事正文。
- 不为 Series 2–8 添加声明。
- 不递归收录附件页面里的链接。
