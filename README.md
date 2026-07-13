# SCP Story EPUB

用于将 SCP Wiki CN 的 Tales Edition 目录页下载、清洗并打包为 EPUB 电子书的 Python 工具。当前仓库已支持按配置文件生成 Series 1 和 Series 2 的分卷 EPUB，并会在构建过程中缓存页面、下载正文图片等资源、生成中间 XHTML 与构建报告。

## 功能概览

- 从 SCP Wiki CN 目录页解析指定分卷的页面清单。
- 下载页面 HTML，并复用 `data/raw/` 中的本地缓存。
- 清洗页面正文，移除评分、导航、脚本、编辑区、授权区等不适合 EPUB 的内容。
- 保留正文中的图片、常见内容块、表格、引用块和安全的内联样式。
- 将目录内页面链接识别为 EPUB 内部链接，并保留外部链接。
- 按分卷生成 EPUB 3 文件和 JSON 构建报告。

## 环境要求

- Python 3.11 或更高版本
- Windows PowerShell、PowerShell Core 或其他可运行 Python 的终端

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

生成结果默认写入：

```text
output/epub/scp-series-1-001-099-tales.epub
output/reports/scp-series-1-001-099-tales-report.json
```

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

忽略已有缓存并重新请求页面：

```powershell
python -m scp_epub --config config/series-1.yaml build --volume 001-099 --refresh
```

`index` 与 `manifest` 当前都会生成页面清单。`clean` 命令目前只是占位提示，尚未实现对生成文件的清理。

## 配置说明

配置文件位于 `config/`：

- `config/series-1.yaml`：Series 1，分卷范围为 `001-099` 到 `900-999`。
- `config/series-2.yaml`：Series 2，分卷范围为 `1000-1099` 到 `1900-1999`。

配置中的关键字段包括：

- `base_url`：SCP Wiki CN 根地址。
- `index_path`：Tales Edition 目录页路径。
- `series_index_path`：主系列目录页路径，用于补齐缺失条目。
- `cache_dir`：原始页面和资源缓存目录。
- `manifest_dir`：页面清单输出目录。
- `processed_dir`：清洗后的 XHTML 中间产物目录。
- `output_dir`：EPUB 和报告输出目录。
- `request_delay_seconds`、`request_timeout_seconds`、`retry_count`：页面请求节流、超时与重试设置。
- `asset_timeout_seconds`、`asset_retry_count`：图片等资源下载的超时与重试设置。
- `volumes`：分卷定义，包含起止编号、书名和输出文件名。

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
2. 从 Tales Edition 目录页解析分卷条目。
3. 从主系列目录页补齐目录中可能缺失的 SCP 条目。
4. 下载或读取缓存中的页面 HTML。
5. 清洗正文，标准化资源 URL 与链接。
6. 下载正文资源并写入 EPUB。
7. 生成 EPUB 文件和 JSON 构建报告。

如果某些页面或资源下载失败，构建报告会记录 `missing_pages` 和 `missing_assets`，便于后续排查。

## 测试

运行完整测试：

```powershell
pytest -q
```

修改清洗规则时重点关注：

- `tests/test_transform.py`
- `tests/test_assets.py`
- `tests/test_epub.py`

修改目录或清单逻辑时重点关注：

- `tests/test_indexer.py`
- `tests/test_manifest.py`
- `tests/test_pipeline.py`

修改 CLI 或配置加载时重点关注：

- `tests/test_cli.py`
- `tests/test_config.py`

## 开发注意事项

- `data/raw/`、`data/processed/`、`data/manifests/` 和 `output/` 是缓存或生成产物，已在 `.gitignore` 中忽略。
- 外部页面内容不可信，新增 HTML 清洗、链接重写或资源处理逻辑时应补充测试。
- 处理 HTML 时优先使用 BeautifulSoup 和仓库内已有 URL 工具。
- 生成大批量 EPUB 前，建议先构建单个分卷并检查报告中的缺失页面和缺失资源。
- 对 SCP Wiki CN 发起请求时请保留合理延迟，避免过于频繁地刷新缓存。

## 内容来源说明

本工具仅用于生成电子书文件，页面正文和图片等内容来源于 SCP Wiki CN。使用、分发生成的 EPUB 时，请遵守原站点及相关作品的授权要求。
