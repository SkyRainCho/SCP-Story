# SCP Story EPUB

用于将 SCP Wiki CN 的 Tales Edition 目录页下载、清洗并打包为 EPUB 电子书的 Python 工具。当前仓库已支持按配置文件生成 Series 1 到 Series 8 的分卷 EPUB，也支持从英文站 Featured SCP Archive 生成中文精选主文档 EPUB；构建过程中会缓存页面、下载正文图片等资源、生成中间 XHTML 与构建报告。

## 功能概览

- 从 SCP Wiki CN 目录页解析指定分卷的页面清单。
- 下载页面 HTML，并复用 `data/raw/` 中的本地缓存。
- 清洗页面正文，移除评分、导航、脚本、编辑区、授权区等不适合 EPUB 的内容。
- 保留正文中的图片、常见内容块、表格、引用块和安全的内联样式。
- 支持将 SCP-001 主页面中的提案列表补入 Series 1，并按主页面顺序排列。
- 支持根据英文站 Featured SCP Archive 生成 `SCP基金会档案精选`，主清单按 Featured 页面条目编号排序，并可纳入主文档中的高置信附属文档。
- 将部分 Wikidot 动态结构转换为适合 EPUB 阅读的静态结构，例如标签栏、CSS grid 表格和部分页面样式。
- 将目录内页面链接识别为 EPUB 内部链接，并保留外部链接。
- 可扫描并打包正文中尚未进入目录的高置信附属文档链接，生成后续复核报告。
- 构建时会自动查找 `cover/` 中与分卷输出名匹配的封面图片，并写入 EPUB 封面元数据。
- 按分卷生成 EPUB 3 文件和 JSON 构建报告。

## 环境要求

- Python 3.11 或更高版本
- Windows PowerShell、PowerShell Core 或其他可运行 Python 的终端
- 可选：Calibre（使用 `build --kindle` 生成 AZW3 时需要，命令 `ebook-convert` 必须可用）

建议在虚拟环境中安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

只运行构建、不运行测试时，也可以安装基础依赖：

```powershell
pip install -e .
```

## 快速开始

构建 Series 1 的 `001-099` 分卷：

```powershell
python -m scp_epub --config config/series-1.yaml build --volume 001-099
```

安装为可编辑包后，也可以使用控制台命令：

```powershell
scp-epub --config config/series-1.yaml build --volume 001-099
```

生成结果默认写入。以 Series 1 的 `001-099` 分卷为例：

```text
output/epub/SCP基金会档案-故事系列-第1卷-第1册.epub
output/reports/SCP基金会档案-故事系列-第1卷-第1册-report.json
```

构建 Series 1 的全部分卷：

```powershell
$volumes = @("001-099","100-199","200-299","300-399","400-499","500-599","600-699","700-799","800-899","900-999")
foreach ($volume in $volumes) {
  python -m scp_epub --config config/series-1.yaml build --volume $volume
}
```

构建 Featured SCP Archive 精选 EPUB：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

生成结果默认写入：

```text
output/epub/SCP基金会档案精选.epub
output/reports/SCP基金会档案精选-report.json
```

### 构建 Kindle Scribe 优化版

安装 Calibre 后，可为 Featured 精选集同时生成 Kindle 优化 EPUB 和 AZW3：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

生成结果：

```text
output/epub/SCP基金会档案精选-Kindle.epub
output/azw3/SCP基金会档案精选-Kindle.azw3
output/reports/SCP基金会档案精选-Kindle-report.json
```

Kindle EPUB 使用适合 AZW3/KF8 的专用样式，并由 Calibre 的
`kindle_scribe` 输出配置转换；已有目录会被复用，不会插入重复的正文目录。
该 AZW3 适用于通过 Calibre 和 USB 传入 Kindle Scribe。

Kindle 构建会按文件真实内容校验图片，将 WebP、BMP 等 AZW3 不安全的栅格格式
规范化为 PNG，并清理可能破坏 Calibre 转换的 PNG 元数据。实际为 HTML 错误页或
无法解码的图片不会写入 Kindle EPUB；页面会保留可用的 `alt` 文本占位，其原始 URL
会记录在 Kindle report 的 `missing_assets` 中。

`--kindle` 是可选参数。不带该参数时，原有 EPUB 文件名、样式和构建行为不变。
如果未安装 Calibre 或转换失败，命令会保留已生成的 Kindle EPUB 和报告、删除临时
AZW3，并以错误退出；不会用不完整文件覆盖已有 AZW3。

## 常用命令

生成或刷新页面清单：

```powershell
python -m scp_epub --config config/series-1.yaml manifest --volume 001-099
```

预先下载清单中的页面：

```powershell
python -m scp_epub --config config/series-1.yaml fetch --volume 001-099
```

完整构建 EPUB：

```powershell
python -m scp_epub --config config/series-1.yaml build --volume 001-099
```

如果存在匹配的封面图片，构建时会自动附加到 EPUB 中。封面文件放在工作区根目录的 `cover/` 下，命名规则为：

```text
cover/<output_slug>-cover.png
```

例如 Series 1 第一册会使用：

```text
cover/SCP基金会档案-故事系列-第1卷-第1册-cover.png
```

扫描当前分卷中可能需要额外打包的高置信附属文档：

```powershell
python -m scp_epub --config config/series-1.yaml scan-linked-appendices --volume 001-099
```

该命令只读取已生成的 manifest 和 `data/raw/pages/` 页面缓存，不会自动下载页面，也不会修改 EPUB 目录。扫描结果会写入：

```text
output/reports/SCP基金会档案-故事系列-第1卷-第1册-linked-appendices.json
```

忽略已有缓存并重新请求页面：

```powershell
python -m scp_epub --config config/series-1.yaml build --volume 001-099 --refresh
```

`index` 与 `manifest` 当前都会生成页面清单。`clean` 命令目前只是占位提示，尚未实现对生成文件的清理。

## 配置说明

配置文件位于 `config/`：

- `config/series-1.yaml`：Series 1，分卷范围为 `001-099` 到 `900-999`。
- `config/series-2.yaml`：Series 2，分卷范围为 `1000-1099` 到 `1900-1999`。
- `config/series-3.yaml` 到 `config/series-8.yaml`：后续系列分卷配置。
- `config/featured-scp.yaml`：从英文站 Featured SCP Archive 递归读取归档分页，并用中文站同 slug 的 SCP 主文档生成 `SCP基金会档案精选.epub`。

配置中的关键字段包括：

- `base_url`：SCP Wiki CN 根地址。
- `title`：EPUB 主书名，当前统一为 `SCP基金会档案：故事系列`。
- `creator`：EPUB 作者，当前统一为 `SCP基金会`。
- `index_path`：Tales Edition 目录页路径。
- `series_index_path`：主系列目录页路径，用于补齐缺失条目。
- `scp001_path`：SCP-001 主页面路径，用于在启用时解析提案列表。
- `index_mode`：目录解析模式，默认 `tales`；`featured-scp-archive` 会按 Featured SCP Archive 解析 SCP 主文档列表。
- `featured_archive_url`：Featured SCP Archive 起始页的绝对 URL，仅 `index_mode: featured-scp-archive` 使用。
- `featured_title_index_paths`：Featured 精选模式额外读取的中文 SCP 系列索引页，用于补齐英文归档中只有编号的目录标题；当前读取 Series 9 和 Series 10。
- `front_matter_pages`：构建前插入目录最前面的前置文档；精选配置当前插入 `关于SCP基金会`。
- `include_scp001_proposals`：是否将 SCP-001 主页面中的提案补入清单。Series 1 当前启用该选项，提案会作为与 `SCP-001` 同层级的顶层目录项出现。
- `include_linked_appendices`：是否在构建时自动纳入高置信原文附属文档。精选配置启用该选项，主文档清单仍由 Featured Archive 决定，附属文档插入来源页面下的 `原文附属文档` 分组中。
- `explicit_linked_appendices`：显式指定某个页面必须收录的附属文档链。该配置不会放开全局递归；精选配置用它为 `scp-5170` 收录 `offset/1`、`offset/2`、`offset/3` 三个附件。
- `page_tab_includes`：按页面 slug 限定 Wikidot 标签页展开范围。精选配置用它让 `about-the-scp-foundation` 只保留 `简介` 标签内容。
- `cache_dir`：原始页面和资源缓存目录。
- `manifest_dir`：页面清单输出目录。
- `processed_dir`：清洗后的 XHTML 中间产物目录。
- `output_dir`：EPUB 和报告输出目录。
- `request_delay_seconds`、`request_timeout_seconds`、`retry_count`：页面请求节流、超时与重试设置。
- `asset_timeout_seconds`、`asset_retry_count`：图片等资源下载的超时与重试设置。
- `volumes`：分卷定义，包含起止编号、书名和输出文件名。当前命名规则为 `SCP基金会档案：故事系列 第X卷-第Y册`，其中 `X` 是 Series 编号，`Y` 是该 Series 内的册序号；输出文件名使用 `SCP基金会档案-故事系列-第X卷-第Y册`。

新增系列时，优先复制现有 YAML 配置并调整 `series_id`、目录路径和 `volumes`。

## 项目结构

```text
src/scp_epub/
  cli.py          命令行入口和参数解析
  pipeline.py     构建流程编排
  fetcher.py      页面与资源下载
  cache.py        本地缓存路径与读写
  indexer.py      目录页解析
  manifest.py     页面清单合并与读写
  transform.py    HTML 正文清洗与链接/资源标准化
  assets.py       图片等资源本地化
  epub.py         EPUB 写入与构建报告
  kindle.py       Kindle XHTML/CSS 适配与 Calibre AZW3 转换
  styles/         EPUB 打包使用的可选样式资源
  config.py       YAML 配置加载与校验
  models.py       数据模型
  urls.py         URL 与文件名工具

config/           系列配置文件
tests/            pytest 测试与 HTML fixture
docs/             设计与开发过程文档
data/             本地下载缓存和中间产物，默认不提交
output/           生成的 EPUB 与报告，默认不提交
```

## 流水线说明

一次 `build` 会依次执行以下步骤：

1. 读取 YAML 配置并定位目标分卷。
2. 从 Tales Edition 目录页解析分卷条目；若 `index_mode` 为 `featured-scp-archive`，则从 Featured SCP Archive 递归解析 SCP 主文档条目。
3. 在 Tales 模式下，从主系列目录页补齐目录中可能缺失的 SCP 条目。
4. 在启用 `include_scp001_proposals` 且目标分卷包含 SCP-001 时，从 SCP-001 主页面补入提案。
5. 下载或读取缓存中的页面 HTML。
6. 清洗正文，标准化资源 URL 与链接。
7. 下载正文资源并写入 EPUB。
8. 生成 EPUB 文件和 JSON 构建报告。

如果某些页面或资源下载失败，构建报告会记录 `missing_pages` 和 `missing_assets`，便于后续排查。

构建 EPUB 时，流水线会在抓取基础 manifest 页面后自动扫描这些高置信附属链接，并只额外抓取命中的附属页面。附属页面会插入到来源页面下的 `原文附属文档` 分组中，避免和 Tales Edition 中已有的故事子目录混淆；该扫描只展开一层，不递归追踪附属页面里的链接。

`scan-linked-appendices` 是独立的只读诊断命令。它会使用同一套保守规则扫描正文区域里的同站链接，排除已经在 manifest 中的页面以及作者页、系统页、论坛页、授权页、组件页和资源文件页，只报告明显像附录、日志、记录、测试、实验、报告、文件、同一 SCP 编号分支或同页面分卷的链接。该报告用于人工复核构建时会尝试纳入的附属文档候选。

## EPUB 转换规则

清洗和转换的目标是尽量保留正文可读性，同时避免网页交互结构在 EPUB 中失效或污染排版：

- SCP-001 提案在目录中保持与 SCP-001 同层级，并遵循 SCP-001 主页面中的提案顺序。
- 非 `scp-001` 页面中的 Wikidot `yui-navset` 标签栏会展开为带标题的静态分节；`scp-001` 本页的标签栏保持原结构。
- CSS grid 风格表格会转换为 EPUB 友好的表格。
- 浮动图片块会做排版稳定处理，避免覆盖后续虚线框、引用框或折叠内容。
- 作者元数据卡片、评分区、授权区等页面外围内容会被移除。
- `scene-break` SCP 图标会保持小尺寸居中，不按普通图片放大。

## 测试

运行完整测试：

```powershell
pytest -q
```

修改清洗规则时重点关注：

- `tests/test_transform.py`
- `tests/test_assets.py`
- `tests/test_epub.py`
- `tests/test_kindle.py`

修改目录或清单逻辑时重点关注：

- `tests/test_indexer.py`
- `tests/test_manifest.py`
- `tests/test_scp001.py`
- `tests/test_pipeline.py`

修改 CLI 或配置加载时重点关注：

- `tests/test_cli.py`
- `tests/test_config.py`

修改 Kindle 输出时，需要覆盖 CLI、pipeline、stylesheet、转换失败和普通构建回归，
重点关注 `tests/test_kindle.py`、`tests/test_cli.py`、`tests/test_pipeline.py` 和
`tests/test_epub.py`。

## 开发注意事项

- `data/raw/`、`data/processed/`、`data/manifests/` 和 `output/` 是缓存或生成产物，已在 `.gitignore` 中忽略。
- 外部页面内容不可信，新增 HTML 清洗、链接重写或资源处理逻辑时应补充测试。
- 处理 HTML 时优先使用 BeautifulSoup 和仓库内已有 URL 工具。
- 生成大批量 EPUB 前，建议先构建单个分卷并检查报告中的缺失页面和缺失资源。
- 对 SCP Wiki CN 发起请求时请保留合理延迟，避免过于频繁地刷新缓存。
- 重试缺失资源时，避免把 HTML 404/错误页写入图片缓存。旧 `scp-wiki.net`、Wikimedia、Imgur、Pinterest 等外站资源可能因证书、超时或源站删除而失败。

## 内容来源说明

本工具仅用于生成电子书文件，页面正文和图片等内容来源于 SCP Wiki CN。使用、分发生成的 EPUB 时，请遵守原站点及相关作品的授权要求。
