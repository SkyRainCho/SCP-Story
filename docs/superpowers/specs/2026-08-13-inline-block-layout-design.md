# EPUB 居中折叠卡片布局恢复设计

## 问题与根因

SCP-3934 的“外务部制备”卡片依靠两个条件居中：卡片本身使用
`display: inline-block` 按内容收缩，父级 `#page-content .collapsible-block` 使用
`text-align: center`。当前清洗流程分别删除了内联 `display`，并过滤整条交互折叠面板
CSS，因此只恢复其中任何一项都不能修复截图问题。

## 选定方案

仅在原页面同时满足以下条件时恢复静态布局：

1. 页面样式中存在针对 `#page-content .collapsible-block` 的 `text-align: center`；
2. 对应 `.collapsible-block-content` 内存在内联 `display: inline-block` 元素。

清洗器为命中的内容容器和卡片添加 EPUB 专用类，并写入两条静态 CSS：

```css
.centered-inline-block-container-epub { text-align: center; }
.centered-inline-block-card-epub { display: inline-block; }
```

原有段落级 `text-align: left` 规则继续生效。该方案不放开通用 `display` 白名单，
`display:none` 等值仍被删除，也不保留折叠控件的整套交互 CSS。

## 影响范围

按上述两个条件重新扫描当前 manifest，实际影响共 10 篇、25 个卡片节点：

1. SCP-287（2）
2. SCP-3221（2）
3. SCP-3304（2）
4. SCP-3442（1）
5. SCP-3599（1）
6. SCP-3703（8）
7. SCP-3872（3）
8. SCP-3934（1）
9. SCP-4002（4）
10. SCP-4612（1）

Featured 精选集只包含 SCP-3934 和 SCP-4612，共 2 个卡片节点。其余 8 篇会在以后
重建对应 Series 卷册时自动修正。

## 测试与验证

1. 最小失败测试复现居中规则与 inline-block 卡片同时存在的结构。
2. 证明缺少任一条件时不添加 EPUB 专用类或 CSS。
3. 证明 `display:none` 与无关 `display` 值仍不进入输出。
4. 运行完整测试套件。
5. 重建 Featured 普通 EPUB 与 Kindle Scribe 稳定版。
6. 结构与视觉核验 SCP-3934 和 SCP-4612：卡片居中，后续正文仍左对齐。

## 非目标

- 不全局恢复 `display:inline-block`。
- 不恢复折叠面板的交互行为或整套页面 CSS。
- 不加入 SCP-3934 slug 特判。
