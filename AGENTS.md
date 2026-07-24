# 仓库指南

## 项目结构与模块组织

本仓库用于生成 SCP Wiki Tales Edition 的 EPUB。源码位于 `src/scp_epub/`：

- `cli.py`、`__main__.py`：命令行入口。
- `pipeline.py`：构建流程编排。
- `fetcher.py`、`cache.py`、`assets.py`：页面、资源下载与缓存。
- `indexer.py`、`manifest.py`：目录解析、页面合并与排序。
- `linked_appendices.py`：扫描正文中尚未进入清单的高置信附属文档链接。
- `transform.py`、`epub.py`：HTML 清洗与 EPUB 写入。
- `models.py`、`config.py`、`urls.py`：数据模型、配置与 URL 工具。

配置文件位于 `config/`，当前包含 `series-1.yaml` 到 `series-8.yaml`，以及 Featured SCP Archive 精选配置 `featured-scp.yaml`。测试位于 `tests/`，HTML 样例放在 `tests/fixtures/`。`data/raw/`、`data/processed/`、`output/` 是下载缓存或生成产物，不应提交到 Git。

## 构建、测试与开发命令

安装开发依赖：

```powershell
pip install -e ".[dev]"
```

运行完整测试：

```powershell
pytest -q
```

构建 Series 1 的 001-099 样书：

```powershell
python -m scp_epub --config config/series-1.yaml build --volume 001-099
```

构建 Featured SCP Archive 精选 EPUB：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```

构建 Kindle Scribe 优化版精选样书：

```powershell
python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle
```

该命令生成 `output/epub/SCP基金会档案精选-Kindle.epub`、
`output/azw3/SCP基金会档案精选-Kindle.azw3` 和独立构建报告。它依赖系统中可用的
Calibre `ebook-convert`。Kindle 构建会按真实内容校验图片，把 WebP、BMP 等不兼容
栅格图规范化为 PNG；无效图片不会进入 Kindle EPUB，并会记录在 Kindle report 的
`missing_assets` 中。不带 `--kindle` 时，原有资源处理、report、EPUB 输出、CSS 和
命名必须保持不变。

该配置从英文站 Featured SCP Archive 起始页递归读取归档分页，但 EPUB 正文使用中文站同 slug 的 SCP 主文档。精选书的主清单由 Featured 页面决定，并按页面条目编号排序；构建时仍可按高置信规则纳入主文档中的原文附属文档。

扫描 Series 1 的 001-099 样书中可能需要额外处理的高置信附属文档链接：

```powershell
python -m scp_epub --config config/series-1.yaml scan-linked-appendices --volume 001-099
```

该命令只读取已有 manifest 和 `data/raw/pages/` 页面缓存，输出 `output/reports/*-linked-appendices.json`，不会修改 EPUB、manifest 或下载页面。正常 `build` 会使用同一套保守规则自动抓取并打包高置信附属文档。

当前 EPUB 书名和输出文件名使用中文卷册命名：主标题为 `SCP基金会档案`，副标题为 `故事系列`，作者为 `SCP基金会`。`第X卷-第Y册` 中 `X` 是 Series 编号，`Y` 是该 Series 内册序号；例如 Series 1 的 `001-099` 输出为 `SCP基金会档案-故事系列-第1卷-第1册.epub`。

构建 EPUB 时会自动查找工作区根目录 `cover/` 下的匹配封面图，命名规则为 `<output_slug>-cover.png`，例如 `cover/SCP基金会档案-故事系列-第1卷-第1册-cover.png`。存在时应写入 EPUB 的 `cover.xhtml`、`cover-image` manifest 项和封面 metadata；不存在时构建应继续。

构建 Series 1 的全部分卷：

```powershell
$volumes = @("001-099","100-199","200-299","300-399","400-499","500-599","600-699","700-799","800-899","900-999")
foreach ($volume in $volumes) {
  python -m scp_epub --config config/series-1.yaml build --volume $volume
}
```

安装后也可使用控制台命令：

```powershell
scp-epub --config config/series-1.yaml build --volume 001-099
```

## 性能与并发约束

当前构建包含两个并行阶段：

- 正文清洗由 `pipeline.py` 的 `_process_pages` 使用 `ProcessPoolExecutor` 执行，默认进程数为 `min(os.cpu_count(), 8)`；`SCP_EPUB_WORKERS=1` 强制走串行路径。当前实现会在任务数大于 1 且 worker 数大于 1 时创建进程池。Windows 的 `ProcessPoolExecutor` 最多接受 61 个 worker；修改 worker 解析或进程池启用阈值时，需要覆盖超大环境变量值和小任务构建的 spawn 开销。
- 页面抓取由 `_fetch_pages_concurrent` 使用 `ThreadPoolExecutor` 执行，高置信附属文档抓取也使用线程池；默认线程数为 6，可通过 `SCP_EPUB_FETCH_WORKERS` 调整，设为 `1` 时顺序抓取。线程并发主要加速缓存未就绪的后期 Series 和 Featured 构建。

并发实现必须保持 manifest 顺序、缺失页面与 fallback 处理顺序、附属文档分组、构建报告及最终 EPUB 与串行路径一致。页面缓存以 slug 为键；修改任务合并或调度时，必须避免相同 slug 并发写入同一缓存文件，并覆盖同 slug 跨来源、不同 URL、首个 URL 失败后后续 URL 成功等情形。不得依赖 future 的完成顺序决定输出顺序。

`tests/conftest.py` 默认将 `SCP_EPUB_FETCH_WORKERS` 设为 `1`，因此普通测试不会自动覆盖真实线程并发。修改并发抓取时，需要在目标测试中用 `monkeypatch` 显式提高 worker 数，并覆盖请求重叠、结果顺序、异常、fallback 和重复缓存键。修改多进程清洗时，应同时覆盖 `SCP_EPUB_WORKERS=1` 的串行基线和启用进程池的路径；性能断言应避免依赖绝对耗时，优先验证是否选择了预期执行路径。

`request_delay_seconds` 当前只是在单个请求的重试之间等待，不是跨线程的全局请求间隔；控制站点瞬时请求量应优先调整 `SCP_EPUB_FETCH_WORKERS`。当前 fetcher 会重试网络错误、5xx 以及 408 / 429，并对其他 4xx 提前停止；修改状态码分类时，需要在 `tests/test_fetcher.py` 中覆盖页面和资源请求的“瞬时错误后成功”与永久错误不重试行为。

## 代码风格与命名约定

使用 Python 3.11+，四空格缩进。函数保持小而明确，公共结构优先使用类型标注；结构化数据优先使用 dataclass。函数、变量、测试名使用 `snake_case`。处理 HTML 时优先使用 BeautifulSoup 或现有 URL 工具，避免脆弱的手写字符串解析。

## 测试规范

测试框架为 `pytest`，配置在 `pyproject.toml` 中，已设置 `pythonpath = ["src"]` 和 `testpaths = ["tests"]`。修改清洗规则时补充 `tests/test_transform.py`，修改 EPUB 输出时补充 `tests/test_epub.py`，修改目录解析时补充 `tests/test_indexer.py`、`tests/test_manifest.py` 或 `tests/test_scp001.py`。修改高置信附属文档扫描规则时补充 `tests/test_linked_appendices.py`；修改抓取重试策略时补充 `tests/test_fetcher.py`；修改构建并发、结果排序或 fallback 编排时补充 `tests/test_pipeline.py`。测试命名使用 `test_<行为>`，fixture 应保持最小化。

SCP-001 提案补全由 `include_scp001_proposals` 控制；Series 1 当前启用该选项。提案在 EPUB 目录中应作为与 `SCP-001` 同层级的顶层条目出现，而不是 `SCP-001` 的子目录。修改相关逻辑时，需要覆盖提案顺序、子故事分组、缺失提案补入和导航层级。

HTML 清洗逻辑需要特别注意以下已知模式：

- Wikidot `yui-navset` 标签栏在非 `scp-001` 页面中会展开为静态 `tabview-epub` 分节；`scp-001` 本页保持原标签栏结构。
- `<style>` 内容使用线性 CSS 规则扫描器处理，以避免大型或畸形样式块触发正则回溯；修改扫描逻辑时不得重新引入跨整个样式块的高回溯正则，并应在 `tests/test_transform.py` 中覆盖大型 CSS 输入。
- CSS grid 风格表格会转换为 EPUB 友好的表格。
- 浮动图片块需要避免覆盖后续虚线框、引用框或折叠内容。
- `authorbox` 等作者元数据卡片不应进入正文。
- `scene-break` SCP 图标应保持小尺寸居中，不应按普通图片放大。

修改 Kindle 输出时，需要覆盖 `tests/test_kindle.py`、`tests/test_cli.py`、
`tests/test_pipeline.py` 和 `tests/test_epub.py`。Kindle CSS 应避免依赖 KF8 不稳定的
Grid、Flexbox、生成内容伪元素和结构伪类；许可等级等语义内容必须写入真实 XHTML，
不能只存在于 CSS `content` 中。Calibre 转换必须使用临时 AZW3 和原子替换，失败时
保留 Kindle EPUB、报告及已有有效 AZW3。

`scan-linked-appendices` 的候选规则必须保持保守：宁可漏掉边缘链接，也不要把普通 SCP 交叉引用、系列推荐、作者页、授权页、论坛页或系统组件误报为需要打包的附属文档。正常 `build` 会并发抓取候选页面，把成功抓取的页面插入来源页面下的 `原文附属文档` 分组中，且只展开一层，不递归追踪附属页面里的链接。放宽规则、调整分组结构或修改并发去重时必须补充测试，证明普通链接不会被误报，已有故事子目录不会和附属文档混淆，并确保同 slug 候选的报告归属与 EPUB 中实际收录位置一致。

`featured-scp.yaml` 使用 `index_mode: featured-scp-archive` 和 `include_linked_appendices: true`。修改该模式时，必须确保 Featured 归档分页可递归解析、重复 SCP 条目会去重、目录标题优先复用已有中文 manifest 标题，主文档按 Featured 页面条目编号排序，并且高置信附属文档只插入来源页面下的 `原文附属文档` 分组。

Featured 精选模式可通过 `featured_title_index_paths` 配置额外中文 SCP 系列索引页补齐标题；当前应读取 `/scp-series-9` 和 `/scp-series-10`，以避免 Featured 归档中 Series 9/10 条目在目录中只显示编号。补齐逻辑只能填补缺失标题，不应覆盖已有中文 manifest 标题。

精选配置还可使用 `front_matter_pages` 插入前置文档，使用 `explicit_linked_appendices` 为特定主文档收录显式附件链，使用 `page_tab_includes` 对特定页面只展开指定 Wikidot 标签页。`explicit_linked_appendices` 不代表全局递归追踪；当前仅用于 `scp-5170` 的三个 `offset` 附件。`page_tab_includes` 当前用于 `about-the-scp-foundation`，只保留 `简介`，不纳入 `写作指南`。

## 提交与 Pull Request 规范

提交信息保持简短、祈使语气；修复类提交可使用 `fix:` 前缀，例如 `fix: preserve hierarchical epub navigation`。每个提交应聚焦一个行为变化，并包含相应测试。PR 需要说明对流水线的影响、列出已运行命令、标明生成的 EPUB 或报告路径；仅在视觉渲染变化时附截图。

## 安全与配置提示

不要提交下载页面、缓存资源、生成 EPUB 或报告。SCP Wiki 页面属于外部输入，清洗、链接重写、资源处理逻辑必须有测试覆盖。`pyproject.toml` 声明了可选的 `browser` 依赖，`Fetcher` 也允许程序化注入 `browser_fetcher`，但标准 CLI 的 `make_fetcher` 当前不会创建或启用浏览器 fallback；仅安装 `.[browser]` 不会改变构建行为。若将来把浏览器 fallback 接入生产构建，需要显式设计浏览器实例的线程归属，并覆盖并发调用测试。缓存应保留在工作空间内，便于后续复用构建结果。

缺失资源会记录在 `output/reports/*-report.json` 的 `missing_assets` 中。重试下载时优先在 `master` 主工作树中操作，并确认 `git status` 干净。部分外站资源可能因 Wikimedia/Imgur/Pinterest 超时、旧 `scp-wiki.net` 证书或源站 404 失败；不要把 HTML 错误页写入图片缓存。
