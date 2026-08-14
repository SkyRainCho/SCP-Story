# SCP-7900 Paperstack 装饰 Logo 移除设计

## 背景

SCP-7900 中文原页在正文开头包含 Paperstack 主题的装饰性 Logo：

```html
<div class="logo">
  <img src="https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png">
</div>
```

网页依赖 Paperstack 主题 CSS 对该元素进行定位和装饰。EPUB 不保留完整网页主题布局，因此该图片被当作普通正文图片本地化并放大，出现在项目编号和收容等级之前。

## 目标

- 从 SCP-7900 的 EPUB 正文中移除 Paperstack 装饰 Logo。
- 保留 SCP-7900 的鲸皮、教堂、洞穴等全部正文图片。
- 通过显式页面配置限定行为，不影响其他使用 Paperstack 主题的文档。
- 同步 Featured 普通 EPUB、Featured Kindle Scribe EPUB/AZW3 和 Series 8 `7900-7999` EPUB。

## 配置模型

在 `PageOverride` 和 `PageTransformOptions` 中新增布尔字段：

```text
remove_paperstack_theme_logo
```

默认值为 `false`。仅在以下配置的 `page_overrides.scp-7900` 中启用：

- `config/featured-scp.yaml`
- `config/series-8.yaml`

配置解析继续拒绝未知字段和非布尔值。

## 清洗规则

只有页面启用该选项时，才检查 `#page-content` 内的 `div.logo`。容器必须包含图片，并且图片 URL 的路径必须精确指向：

```text
/local--files/theme%3Apaperstack/lgtrans.png
```

匹配时允许 HTTP 与 HTTPS，以及 URL 编码十六进制大小写差异；不以图片文件名、`alt` 或单独的 `logo` class 作为充分条件。

符合条件时删除整个 `div.logo` 容器。以下内容必须保留：

- 未启用页面选项时的同一 Paperstack Logo；
- `div.logo` 中来源不同的图片；
- SCP-7900 的普通 `.scp-image-block` 图片；
- 仅在 CSS `background-image` 中引用同一资源的主题规则。

## 数据流

1. 配置加载器解析 `remove_paperstack_theme_logo`。
2. 流水线将页面覆写值传入 `PageTransformOptions`。
3. `transform_page` 在正文清洗阶段按精确资源指纹移除目标容器。
4. 目标图片不再进入资源收集和 EPUB 资源清单。
5. 普通 EPUB、Kindle 和 Kindle Scribe 继续使用同一份已清洗 XHTML。

## 失败与兼容性

- 页面不存在目标 Logo 时保持原样，不视为构建错误。
- 选项关闭时输出行为保持不变。
- URL 或 DOM 结构不满足精确条件时不删除，避免误伤正文图片。
- 不清理其他页面中的 Paperstack Logo，也不增加全局主题识别规则。

## 测试与验收

新增测试覆盖：

- 配置字段可解析并传入页面转换选项；
- 非布尔配置被拒绝；
- 开关启用时精确 Logo 容器被删除；
- 开关关闭时同一 Logo 保留；
- 相同容器但不同图片 URL 保留；
- SCP-7900 普通正文图片继续存在；
- Featured 与 Series 8 均为 SCP-7900 启用选项。

最终重建并检查：

- `SCP基金会档案精选.epub`
- `SCP基金会档案精选-Kindle-Scribe.epub`
- `SCP基金会档案精选-Kindle-Scribe.azw3`
- `SCP基金会档案-故事系列-第8卷-第10册.epub`

验收标准是 SCP-7900 正文中不再包含 `lgtrans.png` 或目标 `div.logo`，同时正文图片数量和相应资源保持正常。
