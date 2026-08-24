# SCP-7646 分隔徽标尺寸修复设计

## 目标

将 `SCP-7646` 中四处“非现实部”SVG 章节分隔徽标恢复为原网页比例，并同步应用于 Series 8、Featured 普通版和 Kindle Scribe 稳定版。正文图片、异常分级图标及其他页面不受影响。

## 根因

原网页的 Eigenmachine 外部主题将 `.asterisk` 容器定义为 50×50 像素，并通过页面变量 `--astersize: 40` 将其中 SVG 定义为 40×40 像素。EPUB 清洗仅保留页面内 CSS，不递归下载 `@import` 的主题样式；因此 `.asterisk` 节点及 SVG 被保留，但尺寸规则丢失。通用 EPUB 图片规则只设置 `max-width: 100%`，导致无显式尺寸的 SVG 按阅读器可用宽度显示。

## 方案

在页面转换中按 slug `scp-7646` 调用专用规范化函数。函数只处理 `.asterisk` 的直接子图片：容器使用 50×50 像素、最大 80×80 像素、上下 10 像素且水平居中；图片使用 40×40 像素和 `max-width: 100%`。这些数值直接对应原主题在 `--astersize: 40` 时的计算结果。

选择页面级处理而非全局 `.asterisk` 规则，是为了不改变同样使用该 class 的 SCP-5541、SCP-7243 等文档。转换发生在所有构建配置共用的 `transform_page` 中，因此无需在 Featured 与 Series 8 中重复配置。

## 验证

- 最小 fixture 包含四个目标徽标和一个无关图片。
- 测试证明 `scp-7646` 会缩放并居中四个徽标，无关图片不变。
- 同一 fixture 以其他 slug 转换时保持未修改，证明页面隔离。
- 运行全量测试，并重建 Series 8 `7600-7699`、Featured 普通版和 Featured Kindle Scribe。
- 从每个 EPUB 包内检查唯一的 `scp-7646.xhtml`，确认四个徽标尺寸一致；用 Calibre metadata 验证 AZW3 可读。
