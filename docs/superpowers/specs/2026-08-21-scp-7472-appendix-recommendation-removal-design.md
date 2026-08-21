# SCP-7472 附属文档推荐模块移除设计

## 背景

精选集将 `scp-7472/offset/1` 与 `scp-7472/offset/2` 作为 SCP-7472 的两篇原文附属文档收录。两页原始 HTML 的正文末尾均包含标题为“您可能也会喜欢...”的 Wikidot 折叠推荐模块。电子书会把折叠内容静态展开，因而显示三条站内推荐、作者头像及相关链接。

项目已经提供 `remove_recommendation_panel` 页面覆盖项及对应的精确清洗逻辑，但当前精选集配置只为主文档 `scp-7472` 启用了该选项。页面覆盖按完整 slug 匹配，不会由主文档自动继承到两篇附件，因此附件中的推荐模块仍被保留。

## 方案

在 `config/featured-scp.yaml` 的 `page_overrides` 中，为以下两个完整 slug 分别启用现有选项：

- `scp-7472/offset/1`
- `scp-7472/offset/2`

每项均设置 `remove_recommendation_panel: true`。主文档 `scp-7472` 的现有配置保持不变。不修改全局清洗规则，也不让所有附属文档自动继承主文档覆盖项。

这一方案把影响范围限制为 SCP-7472 的两篇已配置附件；其他包含类似折叠模块的文档不受影响。

## 数据流

构建读取精选集配置后，两个附件的完整 slug 会各自解析为 `PageOverride`。流水线处理对应 `PageRef` 时，将该覆盖项转换为启用 `remove_recommendation_panel` 的 `PageTransformOptions`。现有转换器定位标题文字为“您可能也会喜欢...”的 `.collapsible-block-folded`，并移除其所属的整个 `.collapsible-block`，正文其余部分保持不变。

## 测试

- 配置测试确认精选集配置中主文档及两个附件均启用该选项。
- 构建集成测试使用包含推荐模块的两篇附件样例，确认处理后的 XHTML 不再包含推荐标题、推荐链接或推荐模块内容，同时保留各自正文。
- 运行完整 `pytest -q`，确保其他页面覆盖及 EPUB 构建行为不变。

## 构建与验收

同步重建：

- `SCP基金会档案精选.epub`
- `SCP基金会档案精选-Kindle-Scribe.epub`
- `SCP基金会档案精选-Kindle-Scribe.azw3`

验收时从两个 EPUB 中分别定位 `scp-7472/offset/1` 与 `scp-7472/offset/2` 章节，确认：

- “您可能也会喜欢”及“可以随便在这里添加你自己的文章”不再出现；
- `SCP-3790-J`、`SCP-6222`、`SCP-6247` 三条推荐内容不再出现；
- 两篇附件的正常正文仍存在；
- EPUB 压缩结构完整，AZW3 具有有效的 `BOOKMOBI` 文件头。

## 非目标

- 不从 SCP Wiki 原始网页删除或修改内容。
- 不对其他 SCP 页面或其他附件全局移除推荐模块。
- 不把两篇附件新增到 Series 8；它们当前只作为精选集的显式附属文档收录。
