# Featured 外语页面中文回退设计

## 背景

Featured SCP Archive 当前由英文站归档决定主清单，但正文默认抓取中文站同 slug 页面。以下五个条目已进入 Featured 清单，中文站同 slug 当前返回 404：

| slug | 外语来源 | 源语言 | 中文标题 |
| --- | --- | --- | --- |
| `scp-4846` | `https://scp-wiki.wikidot.com/scp-4846` | 英文 | `SCP-4846 - 友善化石` |
| `scp-8304` | `https://scp-wiki.wikidot.com/scp-8304` | 英文 | `SCP-8304 - 现代安慰` |
| `scp-8274` | `https://scp-wiki.wikidot.com/scp-8274` | 英文 | `SCP-8274 - 帝王蝶` |
| `scp-7875` | `https://scp-wiki.wikidot.com/scp-7875` | 英文 | `SCP-7875 - 患上正常症` |
| `yamizushi-file-no233` | `http://scp-jp.wikidot.com/yamizushi-file-no233` | 日文 | `暗寿司档案 No.233「简体字卷」` |

目标是在中文页缺失时使用这些指定外语页面的静态中文译文，同时保持页面排版、资源引用、目录排序和导航层级不变。普通 EPUB 与 Kindle 构建均使用同一回退结果。

## 方案选择

采用“配置化回退 + 仓库内静态中文 HTML 快照”。

未采用的方案：

- 直接修改 manifest URL 和下载缓存：缓存不提交 Git，清缓存或刷新后译文会丢失。
- 构建时在线机器翻译：依赖外部服务，结果不可复现，也难以可靠保护复杂 DOM 结构。

## 配置模型

在 `AppConfig` 中新增 `page_fallbacks: dict[str, PageFallback]`。配置文件使用以下结构：

```yaml
page_fallbacks:
  scp-4846:
    source_url: https://scp-wiki.wikidot.com/scp-4846
    source_language: en
    translated_title: SCP-4846 - 友善化石
    snapshot_path: translations/featured/scp-4846.zh-CN.html
    layout_signature: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

`PageFallback` 字段：

- `source_url`：绝对 HTTP 或 HTTPS URL，用于来源记录和相对链接解析。
- `source_language`：非空语言标识，本期使用 `en` 或 `ja`。
- `translated_title`：回退生效时写入 EPUB 目录的中文标题。
- `snapshot_path`：工作区内的相对路径；不得逃逸工作区。
- `layout_signature`：翻译快照结构签名的十六进制 SHA-256。

配置加载器拒绝未知字段、重复规范化 slug、绝对快照路径、工作区逃逸路径、非 HTTP(S) 来源 URL、无效签名和不存在的快照文件。

## 翻译快照格式

快照是经过人工整理的翻译资源，不是原始下载缓存。每个文件包含：

- 源页面中对正文适用的 `<style>` 元素；
- 一个且仅一个 `#page-content`；
- `#page-content` 内完整的渲染后 DOM。

不保留站点侧栏、登录区、页脚、评分模块、编辑工具和脚本。

允许翻译的内容：

- 可见文本节点；
- `alt`、`title`、`aria-label` 等人类可读说明属性；
- CSS `content:` 中会实际显示的文本。

必须原样保留的内容：

- 标签层级、标签顺序和元素数量；
- `class`、`id`、内联 `style`、表格和列表结构；
- 折叠块、Wikidot 标签页、自定义组件及其数据属性；
- 图片、附件和链接 URL；
- SCP 编号、公式、代码、遮挡符号和专有标识。

图片本身不重绘；只翻译图注和替代文字。

## 结构签名

新增一个独立、可测试的快照结构签名函数。签名输入包括：

- 所有保留的 `<style>` 内容，但忽略 CSS `content:` 字符串的具体文本；
- `#page-content` 中元素的标签名、嵌套关系和顺序；
- 属性名称以及非翻译属性的值；
- 文本节点的位置，但不包括文本内容；
- `alt`、`title`、`aria-label` 的存在性，但不包括其值。

构建加载快照时重新计算签名，并与配置中的 `layout_signature` 比较。签名不一致视为回退失败，防止后续编辑意外改变布局。

## 构建数据流

1. Featured manifest 仍使用中文站 URL、原 slug、原排序、角色和导航层级。
2. `fetch_build_pages` 首先按现有逻辑抓取中文页面。
3. 中文抓取抛出异常时，查询同 slug 的 `page_fallbacks`。
4. 找到回退配置后，验证快照存在、包含唯一 `#page-content` 且结构签名匹配。
5. 创建指向静态快照的 `FetchResult`：
   - `url` 为外语 `source_url`；
   - `path` 为快照路径；
   - `status_code` 为 200；
   - `content_type` 为 `text/html; charset=utf-8`；
   - `from_cache` 为 true。
6. 可用 manifest 中该条目只替换为 `translated_title`，其余字段保持不变。
7. `_process_pages` 使用 `FetchResult.url` 而不是 `PageRef.url` 作为 `transform_page` 的 base URL。正常页面两者相同，因此原有构建行为不变；回退页面则能正确解析英文站或日文站的相对资源。
8. 后续 HTML 清洗、资源本地化、Kindle 图片规范化、EPUB 写入和 AZW3 转换沿用现有流程。

`--refresh` 仍然重新尝试中文页，但不会下载、生成或覆盖仓库中的译文快照。若中文页面未来上线，中文抓取成功后自动停止使用回退。

## 报告

`write_build_report` 新增可选的 `fallback_pages`。仅当构建实际使用至少一个回退页面时，报告顶层新增同名数组；未使用回退的现有配置继续产生原格式报告。每项包含：

```json
{
  "slug": "scp-4846",
  "title": "SCP-4846 - 友善化石",
  "source_url": "https://scp-wiki.wikidot.com/scp-4846",
  "source_language": "en",
  "snapshot_path": "translations/featured/scp-4846.zh-CN.html"
}
```

成功使用回退的页面不进入 `missing_pages`。正文不插入额外翻译提示，避免改变原页面排版；来源归因通过构建报告和快照文件头部注释保存。

## 错误处理

以下情况导致单页回退失败，但不终止整本构建：

- 快照在构建时不可读；
- HTML 缺少或包含多个 `#page-content`；
- 结构签名不匹配；
- HTML 不能以 UTF-8 解码或解析。

失败页面继续写入 `missing_pages`。`reason` 同时包含中文抓取错误和回退验证错误，便于定位问题。

配置本身格式错误、路径逃逸或快照在配置加载时不存在属于确定性配置错误，应立即终止并给出字段级错误信息。

## 测试

### 配置测试

- 正确解析 `page_fallbacks`。
- 拒绝未知字段、重复 slug、非法 URL、非法签名、绝对路径和路径逃逸。
- 拒绝不存在的快照。
- `featured-scp.yaml` 精确声明五个回退页面及中文标题。

### 流水线测试

- 中文页成功时不读取或记录回退。
- 中文页失败时加载快照并保留 slug、排序、角色和父子层级。
- 回退生效时使用中文标题。
- 相对图片和链接以 `source_url` 为基准解析。
- 快照失败时 `missing_pages.reason` 同时包含主抓取和回退错误。
- 普通 EPUB 和 Kindle 构建都使用回退页面。

### 报告测试

- `fallback_pages` 字段稳定输出并保持 manifest 顺序。
- 成功回退页面不出现在 `missing_pages`。
- 未实际使用回退的构建不新增 `fallback_pages`，报告格式和行为保持不变。

### 快照测试

- 五个快照均包含唯一 `#page-content`。
- 五个快照结构签名与配置一致。
- 已知标题、收容等级、主要章节和图注存在中文文本。
- 页面经过 `transform_page` 后仍保留关键表格、折叠块、标签页分节、图片和自定义组件。
- 不包含站点导航、编辑工具或可执行脚本。

### 验收构建

运行：

```powershell
pytest -q
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

验收条件：

- Kindle EPUB 和 AZW3 成功生成；
- 五个目标页面进入 EPUB 正文和目录；
- 最新 Kindle report 的 `missing_pages` 不再包含这五个 slug；
- `fallback_pages` 精确包含这五个 slug；
- EPUB 中五页显示中文文本，关键布局结构存在；
- 非 Kindle 构建行为、命名、CSS 和报告字段保持兼容。

## 非目标

- 不提供通用在线翻译服务或自动翻译命令。
- 不自动同步外语源页面的新修订。
- 不为其他缺失页面自动选择外语来源。
- 不翻译图片像素中的文字。
- 不改变 Featured 清单选择、排序或高置信附属文档规则。
