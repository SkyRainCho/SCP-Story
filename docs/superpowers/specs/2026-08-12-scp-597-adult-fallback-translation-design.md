# Featured SCP-597 成人正文翻译回退设计

## 背景与目标

Featured SCP Archive 已包含 `SCP-597 - 万物之母`。精选构建默认抓取简体中文站同 slug 页面，但该页面目前只显示成人内容提示和一个继续阅读链接，没有简体中文正文。因为请求本身返回 HTTP 200，现有“抓取失败后使用翻译快照”的 `page_fallbacks` 机制不会触发，最终 EPUB 只收录门页。

目标是在精选集构建中识别这一已配置页面的成人门页，并使用英文原文的完整简体中文译文。译文页面保留并中文化英文站的详细成人内容警示，随后在同一 EPUB 页面中直接呈现完整正文，不要求读者再次点击确认。未来中文站若提供真实正文，构建应自动恢复优先使用中文站页面。

## 范围

本次只为 `scp-597` 增加一个配置化、可验证的门页回退，不建立通用成人内容抓取系统，也不改变其他精选页面、Series 构建、目录排序、Kindle 模式或附属文档规则。

译文来源固定为：

- URL：`https://scp-wiki.wikidot.com/scp-597`
- 语言：英文（`en`）
- 中文标题：`SCP-597 - 万物之母`
- 本地快照：`translations/featured/scp-597.zh-CN.html`

## 方案选择

采用“配置化门页检测 + 现有静态译文 fallback”。

未采用的方案：

- 永久强制覆盖 SCP-597：未来官方简中正文上线后仍会被本地译文遮蔽。
- 对所有页面启用通用成人门页启发式识别：容易误判其他提示页或结构特殊页面，超出本次需求。

## 配置模型

扩展现有 `PageFallback`，增加可选的主页面拒绝条件。配置形式为：

```yaml
page_fallbacks:
  scp-597:
    source_url: https://scp-wiki.wikidot.com/scp-597
    source_language: en
    translated_title: SCP-597 - 万物之母
    snapshot_path: translations/featured/scp-597.zh-CN.html
    layout_signature: 0000000000000000000000000000000000000000000000000000000000000000
    primary_page_rejection: adult-gate-only
```

`primary_page_rejection` 缺省时保持现有行为：仅在主页面抓取失败时回退。值为 `adult-gate-only` 时，主页面即使抓取成功，也要经过严格检测；只有确认它是纯成人门页后才回退。配置加载器只接受已知枚举值，拒绝其他字符串。

示例中的全零签名只说明字段格式；实施时必须替换为根据最终译文快照计算出的真实结构签名，全零值不得进入正式配置。

这项配置只放在 `featured-scp.yaml`，因此 Series 1 等其他配置继续按原行为使用中文站页面。

## 成人门页判定

检测逻辑放在 `page_fallbacks.py`，输入为成功抓取的 HTML，不依赖网络状态。`adult-gate-only` 必须同时满足以下条件才判定为门页：

1. 页面包含且只包含一个 `#page-content`。
2. 正文包含指向同一 slug 成人命名空间的继续阅读链接，例如 `/adult:scp-597/noredirect/true`。
3. 归一化后的可见正文包含明确的成人提示语和年龄门槛。
4. 除提示、继续链接、评分模块和前后篇导航外，没有 SCP 正文结构；尤其不得出现 `项目编号`、`Object Class`、`特殊收容措施`、`Special Containment Procedures` 或 `Description` 等正文标记。

检测使用解析后的 DOM 和有限的规范化文本检查，不以正则跨整个 HTML 页面扫描。检测结果为“不是门页”时必须保留成功抓取的中文页面，即使其排版或措辞发生变化；安全默认是不用本地回退。

## 翻译快照

从英文站实际渲染页面提取适用于正文的 `<style>` 和唯一 `#page-content`，移除脚本、站点导航、评分模块、编辑工具和前后篇导航。快照沿用现有 fallback 格式与结构签名校验。

翻译规则：

- 完整翻译可见英文正文、标题、成人警示、图注与可访问性说明。
- 成人警示明确列出原站标注的性暗示、露骨性内容、性侵和血腥内容类别。
- 警示之后直接呈现全文，不保留依赖浏览器交互的“继续”按钮或折叠门槛。
- 保留原文段落、列表、强调、链接、删节位置和附录顺序。
- SCP 编号、文档编号、日期占位、公式、专有标识以及 `[DATA EXPUNGED]` 的语义保持一致；后者统一译为 `[数据删除]`。
- 不补写原文没有的信息，不弱化或扩写成人内容，不翻译图片像素中的文字。
- 文件头部保存英文来源 URL、源语言和翻译说明；构建报告继续通过 `fallback_pages` 记录来源和快照路径。

快照必须包含一个且仅一个 `#page-content`，不得包含 `<script>`，并由现有 `layout_signature` 防止意外结构变更。

## 构建数据流

1. Featured manifest 仍按现有逻辑生成 `scp-597` 条目、排序和中文标题。
2. 流水线正常抓取中文 `https://scp-wiki-cn.wikidot.com/scp-597`。
3. 若抓取失败，沿用现有 fallback 流程。
4. 若抓取成功且该 slug 配置了 `primary_page_rejection: adult-gate-only`，读取 HTML 并执行严格门页检测。
5. 不是纯门页时，使用中文抓取结果，不产生 fallback 记录。
6. 是纯门页时，验证并加载本地中文快照，将转换基准 URL 设为英文来源 URL，并记录 `FallbackPageRecord`。
7. 后续 HTML 清洗、资源本地化、普通 EPUB、Kindle 高清版和 Kindle Scribe 稳定版继续共享现有处理路径。

该流程不写回或覆盖 `data/raw/pages/scp-597.html`。`--refresh` 仍会重新抓取中文页面，因此官方译文上线后可以自动被发现。

## 错误处理

- 主页面抓取成功但不是严格匹配的纯门页：使用主页面。
- 主页面抓取失败：按现有 fallback 逻辑尝试快照。
- 识别为门页但快照不可读、含脚本、正文节点数量错误或签名不匹配：将 SCP-597 记入 `missing_pages`，原因同时说明门页拒绝与快照验证失败；不得把只有提示的门页伪装成成功正文。
- 门页检测读取失败：按单页失败处理并提供可定位的错误原因，不中断整本精选集构建。

## 测试设计

### 配置

- 解析 `primary_page_rejection: adult-gate-only`。
- 缺省该字段时现有五个 fallback 的行为不变。
- 拒绝未知拒绝模式和未知字段。
- `featured-scp.yaml` 精确声明 SCP-597 的来源、标题、快照、签名和拒绝模式。

### 门页检测

- 当前简中成人门页被识别。
- 含相似警示但同时包含正文标记的页面不被识别。
- 普通 SCP 页面不被识别。
- 成人链接指向其他 slug 时不被识别。
- 缺少年龄提示、继续链接或唯一 `#page-content` 时不被识别。

### 流水线

- 主页面为门页时使用快照，保留 manifest 顺序、slug、角色和父子层级。
- 主页面已有正文时优先使用主页面且不记录 fallback。
- 门页命中但快照无效时进入 `missing_pages`，不收录门页占位内容。
- 英文来源 URL 继续作为快照内相对资源和链接的解析基准。
- 普通 EPUB、Kindle 高清版和 Kindle Scribe 稳定版共享相同的页面选择结果。

### 翻译快照与转换

- 快照结构签名与配置一致且不含脚本。
- 转换后保留成人内容警示、项目编号、项目等级、收容措施、描述、四份附录文档和关键列表结构。
- 转换后正文包含中文，不残留成段的英文正文。
- 警示不依赖 CSS `content` 或浏览器脚本才可见。

## 验收

运行目标测试和完整测试：

```powershell
pytest -q tests/test_page_fallbacks.py tests/test_config.py tests/test_pipeline.py tests/test_transform.py
pytest -q
```

随后构建精选集，并检查生成页面与报告：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

验收条件：

- 精选 EPUB 中 `SCP-597 - 万物之母` 包含中文成人警示和完整中文正文。
- `fallback_pages` 包含 `scp-597`、英文来源 URL 和译文快照路径。
- `missing_pages` 不包含 `scp-597`。
- 目录顺序、页面标题和其他精选页面不变。
- 不带 Kindle 参数的既有命名、CSS、资源处理和报告字段兼容。

## 非目标

- 不绕过网站访问控制；使用的是公开英文页面中已返回的正文。
- 不提供在线机器翻译或构建时动态翻译。
- 不自动同步英文页后续修订。
- 不改变其他成人内容页面的策略。
- 不修改 Series 1 中 SCP-597 的页面选择逻辑。
