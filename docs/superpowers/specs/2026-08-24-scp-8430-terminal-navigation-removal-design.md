# SCP-8430 末尾快捷导航移除设计

## 背景

SCP-8430 正文末尾包含一个 `earthworm` 导航组件，链接到 “人类恐惧症：屠宰场地”、“SCP文选2024” 和 “享乐恐惧症：肉欲糜烂”。网页依靠组件 CSS 将其显示为快捷导航，电子书会保留并展开这一模块，形成多余的末尾导航。

现有清洗已经移除该页通用的 `footer-wikiwalk-nav`，但 `remove_terminal_navigation` 只识别紧凑书名号导航、特定迭代链接和 SCP-6781 导航，不识别 SCP-8430 的 `earthworm` 结构。

SCP-8430 当前只进入 Featured 精选集清单；仓库没有 Series 9 构建配置。因此受影响的现有目标产物是精选集普通 EPUB 和 Kindle Scribe EPUB/AZW3。

## 方案

在 Featured 配置中为 `scp-8430` 启用已有的 `remove_terminal_navigation` 页面覆盖。转换器在该选项开启且页面 slug 为 `scp-8430` 时，删除作为文章末尾快捷导航的 `.earthworm` 容器。

识别条件保持页面专用：

- 页面 slug 必须为 `scp-8430`；
- 元素具有 `earthworm` 类；
- 元素包含 previous、hub、next 三类 Earthworm 子项；
- 导航位于正文末尾，允许其后存在脚注区。

不对其他页面或其他 Earthworm 组件应用全局删除。

## 数据流

Featured 配置解析 `PageOverride`，流水线将其转换为 `PageTransformOptions(remove_terminal_navigation=True)`。转换器在资源归一化前检查终端导航，删除匹配的 SCP-8430 Earthworm 容器，然后继续处理正文、资源和脚注。

## 测试

- 转换测试构造与原页一致的 previous/hub/next Earthworm 导航和后续脚注，确认导航删除、正文与脚注保留。
- 负向测试确认关闭选项或使用其他 slug 时保留相同组件。
- 配置测试确认 Featured 中 `scp-8430` 启用终端导航清洗。
- 运行完整 `pytest -q`。

## 构建与验收

重建：

- `SCP基金会档案精选.epub`
- `SCP基金会档案精选-Kindle-Scribe.epub`
- `SCP基金会档案精选-Kindle-Scribe.azw3`

两个 EPUB 的 SCP-8430 章节中应不再出现 `.earthworm`、三条快捷导航标题或 `/scp-anthology-2024` 链接；正常正文和 Footnotes 区必须保留。EPUB ZIP 应完整，AZW3 应具有 `BOOKMOBI` 文件头。

## 非目标

- 不删除正文中的普通交叉引用。
- 不全局删除其他页面的 Earthworm 组件。
- 不修改原始网页或缓存 HTML。
