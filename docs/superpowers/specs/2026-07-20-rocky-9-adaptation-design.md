# Rocky 9.x 适配设计

## 背景

仓库当前面向 Windows PowerShell 环境：README 顶部"环境要求"写明 Windows PowerShell，所有命令示例使用 PowerShell 语法（`.\.venv\Scripts\Activate.ps1`、`$volumes = @(...)`、`foreach`），venv 激活路径为 Windows 风格。

目标是让项目在 Rocky 9.x Linux（实测环境为 Rocky 9.7 on WSL2，对 9.5 等同代版本同样适用）上一键搭建并完成 EPUB 构建。代码层经初步审查已具备跨平台能力：路径全部使用 `pathlib.Path`，`urls.py` 已处理 Windows 保留文件名，`kindle.py` 通过 `shutil.which("ebook-convert")` 跨平台查找 Calibre，未发现硬编码的 `\` 分隔符或 `os.name` 判断。真正的平台耦合集中在文档示例和环境准备步骤。

本设计采用全面适配 + 实际验证路线：新增一个一键 setup 脚本，文档补充 bash 双示例，并在 Rocky 9.7 上实跑 pytest 与两卷 EPUB 构建作为验收。

## 方案选择

采用"完整 setup 脚本 + 自检 + 文档双示例 + 实际验证"。

未采用的方案：

- 仅改文档：缺少可执行的自检与可复现的安装路径，新机器上仍需人工照着敲命令。
- 容器化（Dockerfile / Podmanfile）：交付形态改变较大，对"能在 Rocky 上运行"的目标过重。
- 完全替换 PowerShell 示例为 bash：破坏现有 Windows 用户的工作流。
- 转向 uv 作为主交付路径：引入第三方工具链作为硬依赖，不够"Rocky 原生"；保留为文档备选。

## 环境现状（实测）

| 项目 | 现状 |
| --- | --- |
| 系统 | Rocky Linux 9.7（Blue Onyx），WSL2 内 |
| 系统默认 `python3` | 3.9.25（不满足项目 ≥3.11 要求） |
| Python 3.11 | 已通过 uv 安装在 `~/.local/bin/python3.11`（指向 `~/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu`） |
| EPEL | 已启用（`epel-release-9-10`） |
| Calibre (Linux) | 未安装；PATH 中的 `/mnt/c/Program Files/Calibre2/` 是 Windows 版，WSL 互操作不可靠，不可作为 Linux 构建依赖 |
| dnf | 可用，但验证环境无 sudo 权限 |

WSL2 特有隐患：PATH 混入大量 `/mnt/c/...` Windows 路径（含 Windows 的 Calibre2、Python310），偶发干扰 Linux 命令解析。脚本对此只做提示，不强制清理。

## 交付物

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `scripts/setup-rocky.sh` | Rocky 9.x 一键环境搭建脚本（bash，可执行） |
| 修改 | `README.md` | 顶部"环境要求"改跨平台；新增"在 Rocky 9.x 上搭建"章节；平台特定命令改双示例 |
| 修改 | `AGENTS.md` | 构建、测试与开发命令补 bash 双示例 |
| 可能修改 | `src/scp_epub/` | 仅当验证中发现平台假设问题才动，预期尽量不动 |
| 新增 | 本设计文档 | `docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md` |
| 不入 git | `output/`、`data/raw/`、`.venv/` | 验证产物，已在 `.gitignore` |

新建 `scripts/` 目录（仓库尚无此目录）。代码层以"验证驱动"为原则：仅在验证发现平台问题时小改，不预先重构。

## `setup-rocky.sh` 结构

### 调用约定

```bash
scripts/setup-rocky.sh                       # 完整流程（默认）
scripts/setup-rocky.sh --skip-system-deps    # 无 sudo 时跳过 dnf（配合 uv 路径）
scripts/setup-rocky.sh --help
```

### 执行流程

脚本以 `set -euo pipefail` 运行，幂等可重复。步骤如下：

1. 定位 `REPO_ROOT`（脚本上一级目录）并 `cd` 过去；定义着色输出辅助函数。
2. 系统检测：读取 `/etc/os-release`，确认 `ID` 含 `rocky` 或 `rhel` 且 `VERSION_ID` 以 `9.` 开头。不匹配时打印警告但继续，便于其他 EL9 兼容场景。
3. 系统依赖（`--skip-system-deps` 时跳过）：`sudo dnf install -y` 安装候选系统包（见下节）。无 sudo 时引导用户加 `--skip-system-deps` 并参考 README 的 uv 备选路径。
4. Python 确认：检查 `python3.11` 可用，优先 `/usr/bin/python3.11`。
5. venv：`python3.11 -m venv .venv`，已存在则跳过；激活 `.venv`，`pip install --upgrade pip`。
6. 项目依赖：`pip install -e ".[dev]"`（含 pytest）。
7. 自检：
   - `python --version` 命中 3.11+；
   - `python -c "import lxml, PIL, resvg_py, ebooklib, bs4, httpx, tinycss2, yaml"` 全部成功；
   - `which ebook-convert`：找到则提示 Kindle 构建可用；找不到则提示参见 README 的 Calibre 安装段。
8. 收尾：打印下一步指引（`source .venv/bin/activate`、`pytest -q`、`python -m scp_epub ...`）。
9. WSL PATH 提示：检测到 PATH 含 `/mnt/c/` 时打印一行提醒，不清理。

### 关键设计点

- 幂等：venv 已存在不覆盖；`dnf install` 天然幂等；`pip install -e` 可重复。
- 错误处理：`set -euo pipefail`，任一步失败立即退出并打印失败命令。
- Calibre：自检段只检查并提示，不自动安装；安装留给 README 指引。

## 系统依赖策略

验证前无法确定 Rocky 9 上哪些 `-devel` 包必需，采用"候选清单 + 验证回填"。

候选清单（写入脚本初始版本）：

| 包 | 用途 | 置信度 |
| --- | --- | --- |
| `python3.11` | 项目要求 ≥3.11 | 必需 |
| `python3.11-pip` | 装 venv 与项目依赖 | 必需 |
| `gcc` | 防御性，防个别包回退源码编译 | 防御 |
| `redhat-rpm-config` | RHEL 系编译胶水 | 防御 |

预测不需要的包：`libxml2-devel`、`libxslt-devel`、`libjpeg-turbo-devel`、`zlib-devel`。依据：lxml、Pillow、resvg-py、PyYAML 在 PyPI 均提供 `manylinux` x86_64 wheel，已 bundle 所需原生库；Rocky 9（glibc 2.34）满足 manylinux2014 兼容线；纯 Python 包（bs4、ebooklib、httpx、tinycss2）无系统依赖。

回填流程：在干净 venv 跑 `pip install -e ".[dev]"`，观察是否触发源码编译或缺库；据此回填脚本第 3 步的 `dnf install` 行。若全部 wheel 命中则维持最小集，否则补对应 `-devel`。

Calibre 不进脚本默认流程，README 单独给出：

```bash
sudo dnf install calibre   # EPEL 已启用
```

并附 Calibre 官方 installer 备选链接。

## 文档改动策略

### README.md

1. "环境要求"段：从"Windows PowerShell、PowerShell Core 或其他可运行 Python 的终端"改为"Python 3.11+；Windows PowerShell / Linux（含 Rocky 9.x）/ macOS 的任意能运行 Python 的终端；可选 Calibre（仅 `--kindle` 时）"。
2. 新增"在 Rocky 9.x 上搭建"章节（紧接"环境要求"之后）：指向 `bash scripts/setup-rocky.sh`，说明它完成系统依赖、Python 3.11、venv、项目依赖安装与自检；无 sudo 时用 `--skip-system-deps` 并参考 uv 备选；附 Calibre 可选安装段。
3. 平台特定命令改双示例，保留原 PowerShell，新增 bash，覆盖：venv 创建与激活、`pip install -e ".[dev]"`、批量循环构建、测试命令块。
4. 保留不变：单条 `build`/`manifest`/`fetch` 命令（已跨平台）、配置说明、项目结构、流水线说明、转换规则等描述性章节。

双示例格式约定：

````markdown
**Windows (PowerShell)：**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Linux / Rocky (bash)：**
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
````

批量循环 bash 示例：

```bash
for v in 001-099 100-199 200-299 300-399 400-499 500-599 600-699 700-799 800-899 900-999; do
  python -m scp_epub --config config/series-1.yaml build --volume "$v"
done
```

### AGENTS.md

"构建、测试与开发命令"段：每个 PowerShell 命令块补 bash 双示例，包括 install、pytest、单卷 build、featured build、Kindle build、批量构建循环。修改 AGENTS.md 会影响后续 agent 行为，bash 版命令与 README 保持一致。

`request.md`（原始需求存档）与 `docs/` 下已有设计文档不动。

## 验证方案

### 验证路径

验证环境无 sudo 权限，因此走 uv python3.11 路径验证功能层，并实跑脚本的 `--skip-system-deps` 模式：

1. `bash scripts/setup-rocky.sh --skip-system-deps`（用 `/home/caoyiming/.local/bin/python3.11` 建 venv、装依赖、自检）。
2. `source .venv/bin/activate`。
3. `pytest -q`。
4. `python -m scp_epub --config config/series-1.yaml build --volume 001-099`。
5. `python -m scp_epub --config config/featured-scp.yaml build --volume featured`。
6. 记录耗时、产物路径、report 摘要（`missing_pages` / `missing_assets` 计数）。

### 成功标准

| 检查 | 通过线 |
| --- | --- |
| 脚本 `--skip-system-deps` 模式 | 一次跑通，自检段全绿 |
| `pytest -q` | 0 failed（warnings 可接受） |
| series-1 `001-099` | EPUB 生成；`missing_pages` 为空或个位数；构建本身无平台异常 |
| `featured` | 同上 |

### 平台问题与源站问题的区分

- 平台问题（适配失败，必须修）：`ImportError`、`OSError`、路径/编码/权限错误、依赖编译失败。修复后回到第 3 步重跑。
- 源站问题（适配无关，不阻断）：外站图片超时、404、证书错误，记录进 `missing_assets`。README 已声明这类常发。

### 已知局限（诚实记录）

- 功能层（Python 代码 + 依赖 wheel）在 Rocky 9.7 上实测通过。
- 脚本的 dnf 段（`sudo dnf install python3.11 …`）未在 sudo 下实跑。`python3.11` 模块是 RHEL 9 AppStream 官方支持，命令依据 Rocky 官方文档，风险极低；脚本逻辑经代码审查。
- 系统依赖回填基于"uv python3.11 下 wheel 命中情况"。dnf python3.11 与 uv python3.11 ABI 等价，结论可迁移。

## 错误处理

- 脚本系统检测不匹配时仅警告不阻断，便于 EL9 兼容场景。
- dnf 步骤需要 sudo；无 sudo 时引导 `--skip-system-deps` + uv 备选路径。
- venv 已存在不覆盖，避免破坏已有环境。
- 自检段任一项失败即非零退出并打印缺什么，便于定位。
- Calibre 缺失只提示不阻断（非 `--kindle` 构建不需要）。
- 验证中发现代码平台问题：按"小改、加测试、不重构"原则修复 `src/` 并补对应 `tests/`，不扩大改动范围。

## 质量保障

bash 脚本不纳入 pytest 体系，采用以下手段保障质量：

- `shellcheck` 静态检查脚本（若环境可用）。
- 脚本内置自检段作为运行时验证。
- 端到端验证流程（脚本 → pytest → 两卷构建）作为整体验收。
- 如验证中发现并修复代码层平台问题，按项目惯例补 pytest（`tests/test_*.py`），命名 `test_<行为>`。

## 非目标

- 不容器化（不产出 Dockerfile / Podmanfile）。
- 不在本期强制验证 Kindle（AZW3）构建；Calibre 安装仅文档化。
- 不替换或删除现有 PowerShell 示例。
- 不对代码层做与平台适配无关的重构。
- 不自动处理 WSL PATH 互操作（只提示）。
- 不引入 uv 作为硬依赖；仅作为文档备选。
- 不改变 EPUB 清单、清洗、转换、报告等既有业务逻辑。
