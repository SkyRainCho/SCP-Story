# SCP-9100 隐藏缩略图与静态时间分隔器设计

## 目标

修复 SCP-9100 在 EPUB 中出现的两类原网页不可见或不适配内容：删除顶部预览用眼睛缩略图，并将研究进展时间线中的相对时间分隔器转换成与原网页视觉一致的静态结构。

## 根因

- `Daydream.png` 使用 `.crom-thumbnail` 和行内 `display: none`，仅供网页预览。EPUB 样式清洗不保留 `display`，导致该隐藏图片变成正文图片并被登记为资源。
- `.relativetime` 依赖网页端 Flexbox 与 `::before` / `::after` 伪元素绘制横线。EPUB 中该布局不能稳定复现，形成带大量空白的异常分隔块；时间信息本身必须保留。

## 方案

在 `transform_page` 中增加仅对 `entry.slug == "scp-9100"` 调用的结构规范化：

- 删除所有 `.crom-thumbnail` 元素，使 `Daydream.png` 不进入正文和资源清单。
- 将每个 `.relativetime` 转换为三列表格：左右单元格包含真实横线，中间单元格保留 `[+2天]`、`[+5天]` 等原始文字。
- 使用真实 XHTML 节点和行内样式，不依赖 Flexbox、CSS 伪元素或生成内容，以兼容普通 EPUB 与 Kindle Scribe。
- 不修改正文事件卡、研究记录、分类条、阿克伦图片或其他内容。
- 不对其他页面应用该规则。

## 验证

- 用最小 fixture 证明 SCP-9100 不再输出 `.crom-thumbnail`、`Daydream.png` 和原始 `.relativetime`，但会输出带左右横线的静态分隔器并保留时间文字。
- 证明同一输入在其他 slug 中保持不变。
- 用真实缓存页面确认 1 个隐藏缩略图被删除，92 个时间分隔器全部转换且文字保持不变，同时正文事件仍存在。
- 运行完整测试，重建 Featured 普通版与 Kindle Scribe 稳定版，并检查两个 EPUB 内的 SCP-9100 章节。
