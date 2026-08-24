# SCP-9100 隐藏缩略图与时间分隔器清理设计

## 目标

修复 SCP-9100 在 EPUB 中出现的两类原网页不可见或不适配内容：删除顶部预览用眼睛缩略图，并删除研究进展时间线中的相对时间分隔器。

## 根因

- `Daydream.png` 使用 `.crom-thumbnail` 和行内 `display: none`，仅供网页预览。EPUB 样式清洗不保留 `display`，导致该隐藏图片变成正文图片并被登记为资源。
- `.relativetime` 依赖网页端 Flexbox 与 `::before` / `::after` 伪元素绘制横线。EPUB 中该交互主题布局不能稳定复现，形成带大量空白的异常分隔块。

## 方案

在 `transform_page` 中增加仅对 `entry.slug == "scp-9100"` 调用的结构清理：

- 删除所有 `.crom-thumbnail` 元素，使 `Daydream.png` 不进入正文和资源清单。
- 删除所有 `.relativetime` 元素，包括 `[+2天]`、`[+5天]` 以及全文其他同类时间间隔提示。
- 不修改正文事件卡、研究记录、分类条、阿克伦图片或其他内容。
- 不对其他页面应用该规则。

## 验证

- 用最小 fixture 证明 SCP-9100 不再输出 `.crom-thumbnail`、`Daydream.png` 和 `.relativetime`。
- 证明同一输入在其他 slug 中保持不变。
- 用真实缓存页面确认 1 个隐藏缩略图和 92 个时间分隔器均被删除，同时正文事件仍存在。
- 运行完整测试，重建 Featured 普通版与 Kindle Scribe 稳定版，并检查两个 EPUB 内的 SCP-9100 章节。
