# 仓库指南

## 项目结构与模块组织

本仓库用于生成 SCP Wiki Tales Edition 的 EPUB。源码位于 `src/scp_epub/`：

- `cli.py`、`__main__.py`：命令行入口。
- `pipeline.py`：构建流程编排。
- `fetcher.py`、`cache.py`、`assets.py`：页面、资源下载与缓存。
- `indexer.py`、`manifest.py`：目录解析、页面合并与排序。
- `transform.py`、`epub.py`：HTML 清洗与 EPUB 写入。
- `models.py`、`config.py`、`urls.py`：数据模型、配置与 URL 工具。

配置文件位于 `config/`，当前主要使用 `config/series-1.yaml`。测试位于 `tests/`，HTML 样例放在 `tests/fixtures/`。`data/raw/`、`data/processed/`、`output/` 是下载缓存或生成产物，不应提交到 Git。

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

安装后也可使用控制台命令：

```powershell
scp-epub --config config/series-1.yaml build --volume 001-099
```

## 代码风格与命名约定

使用 Python 3.11+，四空格缩进。函数保持小而明确，公共结构优先使用类型标注；结构化数据优先使用 dataclass。函数、变量、测试名使用 `snake_case`。处理 HTML 时优先使用 BeautifulSoup 或现有 URL 工具，避免脆弱的手写字符串解析。

## 测试规范

测试框架为 `pytest`，配置在 `pyproject.toml` 中，已设置 `pythonpath = ["src"]` 和 `testpaths = ["tests"]`。修改清洗规则时补充 `tests/test_transform.py`，修改 EPUB 输出时补充 `tests/test_epub.py`，修改目录解析时补充 `tests/test_indexer.py` 或 `tests/test_manifest.py`。测试命名使用 `test_<行为>`，fixture 应保持最小化。

## 提交与 Pull Request 规范

提交信息保持简短、祈使语气；修复类提交可使用 `fix:` 前缀，例如 `fix: preserve hierarchical epub navigation`。每个提交应聚焦一个行为变化，并包含相应测试。PR 需要说明对流水线的影响、列出已运行命令、标明生成的 EPUB 或报告路径；仅在视觉渲染变化时附截图。

## 安全与配置提示

不要提交下载页面、缓存资源、生成 EPUB 或报告。SCP Wiki 页面属于外部输入，清洗、链接重写、资源处理逻辑必须有测试覆盖。浏览器 fallback 依赖可选的 `browser` 依赖；缓存应保留在工作空间内，便于后续复用构建结果。
