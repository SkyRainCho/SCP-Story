# SCP-7804 Paperstack 主题标志移除设计

## 背景

SCP-7804 的原始 HTML 在正文开头包含 Paperstack 主题装饰标志：

```html
<div class="logo">
  <img src="https://scp-wiki.wdfiles.com/local--files/theme%3Apaperstack/lgtrans.png">
</div>
```

网页主题 CSS 会把它作为背景式装饰处理，但 EPUB 不执行同样的定位规则，因而将其显示为一张大型正文图片。该结构和资源路径与已处理的 SCP-7900 完全相同。

SCP-7804 同时收录于 Featured 精选集和 Series 8 第9册。当前两套配置只为 SCP-7900 启用了 `remove_paperstack_theme_logo`，所以 SCP-7804 未进入现有清洗路径。

## 方案

在以下两套配置的 `page_overrides` 中为 `scp-7804` 启用现有选项：

- `config/featured-scp.yaml`
- `config/series-8.yaml`

配置内容为：

```yaml
scp-7804:
  remove_paperstack_theme_logo: true
```

不修改转换器的选择器或匹配范围。现有转换器只会删除 `div.logo` 中资源路径精确等于 `/local--files/theme%3apaperstack/lgtrans.png` 的图片容器，因此正文图片不受影响。

## 数据流

构建读取相应配置后，为 `scp-7804` 创建 `PageOverride`。流水线将其转换为启用 `remove_paperstack_theme_logo` 的 `PageTransformOptions`。转换器在资源本地化之前删除匹配的主题标志容器，随后正常处理正文和正文图片。

## 测试

- 生产配置测试确认 Featured 与 Series 8 均为 `scp-7804` 和现有的 `scp-7900` 启用该选项。
- 现有转换器测试继续证明：启用时只删除精确 Paperstack 标志，其他图片保留；禁用或资源路径不同则不删除。
- 运行完整 `pytest -q`，验证其他页面覆盖和构建行为无回归。

## 构建与验收

同步重建：

- `SCP基金会档案精选.epub`
- `SCP基金会档案精选-Kindle-Scribe.epub`
- `SCP基金会档案精选-Kindle-Scribe.azw3`
- `SCP基金会档案-故事系列-第8卷-第9册.epub`

对三个 EPUB 中的 SCP-7804 章节逐一确认：

- 不再包含 `lgtrans.png` 或 Paperstack 主题标志容器；
- 正文图片 `radiomast` 仍存在；
- “项目编号”及 SCP-7804 正文仍存在；
- EPUB 压缩结构完整。

同时确认 Scribe AZW3 大于最小有效大小且具有 `BOOKMOBI` 文件头。

## 非目标

- 不修改 SCP Wiki 原始网页或缓存页面。
- 不对所有 Paperstack 页面进行全局自动删除。
- 不删除 SCP-7804 的正文图片 `radiomast`。
