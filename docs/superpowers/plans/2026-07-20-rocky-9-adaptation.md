# Rocky 9.x 适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让项目在 Rocky 9.x（实测 9.7 on WSL2）上一键搭建并完成 EPUB 构建，同时保留原有 Windows 工作流。

**Architecture:** 新增一个幂等 bash 脚本 `scripts/setup-rocky.sh`，依次完成系统检测、`dnf` 系统依赖、Python 3.11、venv、项目依赖安装与自检；README 与 AGENTS.md 对平台特定命令补充 bash/PowerShell 双示例；端到端验证走 `--skip-system-deps` 路径（验证环境无 sudo，使用 uv 提供的 python3.11）跑 pytest 与两卷 EPUB 构建。

**Tech Stack:** bash（setup 脚本）、Markdown（文档）、Python 3.11（运行时）、pytest（测试）。

## Global Constraints

- Python ≥ 3.11（项目 `pyproject.toml` 要求）。
- 不改 EPUB 清单、清洗、转换、报告、Kindle 等既有业务逻辑；仅当验证中发现平台假设问题才小改 `src/`，并补对应 `tests/`。
- 保留所有现有 PowerShell 示例，不删除、不替换。
- 不容器化、不强制验证 Kindle（AZW3）、不引入 uv 作为硬依赖（仅文档备选）。
- 验证环境无 sudo：走 `bash scripts/setup-rocky.sh --skip-system-deps`，使用 PATH 上的 uv python3.11（`/home/caoyiming/.local/bin/python3.11`）。
- WSL PATH（`/mnt/c/...`）只提示不清理。
- 区分平台问题（必修）与源站问题（外站图片 404/超时/证书，记 `missing_assets`，不阻断）。
- 提交信息使用 `feat:` / `docs:` 前缀，结尾附 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- `output/`、`data/raw/`、`.venv/` 不入 git（已在 `.gitignore`）。

## File Structure

| 文件 | 类型 | 职责 |
| --- | --- | --- |
| `scripts/setup-rocky.sh` | 新增（可执行 bash） | Rocky 9.x 一键环境搭建：系统检测 → dnf → Python 3.11 → venv → pip → 自检 |
| `README.md` | 修改 | 顶部"环境要求"改跨平台；新增"在 Rocky 9.x 上搭建"章节；venv 创建与批量循环段补 bash 双示例 |
| `AGENTS.md` | 修改 | "构建、测试与开发命令"段的 PowerShell 命令块补 bash 双示例 |
| `docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md` | 修改 | 追加"验证结果"段，记录实测耗时、产物、wheel 命中与系统依赖结论 |

`scripts/` 为本次新建目录（仓库此前无）。脚本单一职责，文档改动按锚点定位。

---

### Task 1: 创建 `scripts/setup-rocky.sh`

**Files:**
- Create: `scripts/setup-rocky.sh`

**Interfaces:**
- Consumes: 系统 `/etc/os-release`、PATH 上的 `python3.11`、`sudo`（默认模式）
- Produces: `.venv/`（venv）、可重复执行的安装入口；调用约定 `scripts/setup-rocky.sh [--skip-system-deps] [-h|--help]`

- [ ] **Step 1: 写脚本文件**

创建 `scripts/setup-rocky.sh`，完整内容如下：

```bash
#!/usr/bin/env bash
# Rocky 9.x setup: install system deps, Python 3.11, venv, project deps, and self-check.
set -euo pipefail

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''
fi

info() { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s==>%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%sWARNING:%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
fail() { printf '%sERROR:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SKIP_SYSTEM_DEPS=0

print_usage() {
  cat <<'EOF'
Usage: scripts/setup-rocky.sh [OPTIONS]

Prepare a Rocky 9.x environment for building SCP Story EPUBs.

Options:
  --skip-system-deps   Skip the sudo dnf step. Use when Python 3.11 is already
                       available on PATH (e.g. via uv).
  -h, --help           Show this help and exit.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-system-deps) SKIP_SYSTEM_DEPS=1; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)" ;;
  esac
done

if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  if [[ "${ID:-}" == *rocky* || "${ID:-}" == *rhel* ]] && [[ "${VERSION_ID:-}" == 9.* ]]; then
    ok "Detected ${PRETTY_NAME:-Rocky/RHEL 9.x}."
  else
    warn "Detected ${PRETTY_NAME:-unknown OS}, not Rocky/RHEL 9.x. Continuing anyway."
  fi
else
  warn "/etc/os-release not found; cannot detect OS. Continuing anyway."
fi

if [[ ":${PATH}:" == *":/mnt/c/"* ]]; then
  warn "WSL PATH contains /mnt/c entries. If commands resolve to Windows binaries, check WSL PATH interop."
fi

SYSTEM_PACKAGES=(python3.11 python3.11-pip gcc redhat-rpm-config)
if [[ "$SKIP_SYSTEM_DEPS" -eq 1 ]]; then
  info "Skipping system dependencies (--skip-system-deps)."
else
  info "Installing system packages: ${SYSTEM_PACKAGES[*]}"
  sudo dnf install -y "${SYSTEM_PACKAGES[@]}"
fi

PY=python3.11
if [[ -x /usr/bin/python3.11 ]]; then
  PY=/usr/bin/python3.11
elif ! command -v "$PY" >/dev/null 2>&1; then
  fail "python3.11 not found. Run without --skip-system-deps, or install Python 3.11 (e.g. via uv)."
fi
info "Using Python: $PY ($("$PY" --version))"

VENV_DIR="$REPO_ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating venv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
else
  info "venv already exists at $VENV_DIR; reusing."
fi
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

info "Upgrading pip"
python -m pip install --upgrade pip

info "Installing project dependencies (editable, with dev extras)"
pip install -e ".[dev]"

info "Self-check"
python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python in venv is not 3.11+."
python -c "import lxml, PIL, resvg_py, ebooklib, bs4, httpx, tinycss2, yaml" \
  || fail "Required Python modules not importable; run 'pip install -e .[dev]' first."
ok "All required modules importable."

if command -v ebook-convert >/dev/null 2>&1; then
  ok "Calibre ebook-convert found; Kindle builds (--kindle) are available."
else
  warn "Calibre ebook-convert not found. Kindle builds need it; see README's Calibre section."
fi

ok "Setup complete. Next steps:"
printf '  source .venv/bin/activate\n'
printf '  pytest -q\n'
printf '  python -m scp_epub --config config/series-1.yaml build --volume 001-099\n'
printf '  python -m scp_epub --config config/featured-scp.yaml build --volume featured\n'
```

- [ ] **Step 2: 赋予可执行权限**

Run: `chmod +x scripts/setup-rocky.sh`
Expected: 无输出，退出码 0。

- [ ] **Step 3: shellcheck 静态检查（若可用）**

Run: `command -v shellcheck >/dev/null 2>&1 && shellcheck scripts/setup-rocky.sh || echo "shellcheck not installed, skipped"`
Expected: 若 shellcheck 可用，无 error 级输出（warning 可接受但应尽量清零）；不可用则打印 "shellcheck not installed, skipped"。

- [ ] **Step 4: 验证 `--help` 与参数解析**

Run: `bash scripts/setup-rocky.sh --help`
Expected: 打印 `Usage: scripts/setup-rocky.sh [OPTIONS]` 及选项说明，退出码 0。

Run: `bash scripts/setup-rocky.sh --bogus`
Expected: 退出码非 0，stderr 打印 `ERROR: Unknown option: --bogus (try --help)`。

- [ ] **Step 5: 提交**

```bash
git add scripts/setup-rocky.sh
git commit -m "feat: add rocky 9 setup script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 实跑脚本 `--skip-system-deps`，验证环境搭建

本任务验证脚本的非 dnf 部分，并确认 wheel 命中情况（供 Task 6 回填）。

**Files:**
- 无文件改动（除非诊断出脚本或代码问题）

- [ ] **Step 1: 跑脚本（跳过 dnf，使用 uv python3.11）**

Run: `bash scripts/setup-rocky.sh --skip-system-deps`
Expected:
- 打印 `==> Detected Rocky Linux 9.7 (Blue Onyx).`（或当前 PRETTY_NAME）
- 打印 WSL PATH 提示（PATH 含 `/mnt/c/`）
- `==> Skipping system dependencies (--skip-system-deps).`
- `==> Using Python: python3.11 (Python 3.11.x)`
- 创建 `.venv` 或提示 `venv already exists ... reusing`
- `pip install -e ".[dev]"` 成功
- 自检：`==> All required modules importable.`
- Calibre 提示（Linux 侧未装 → WARNING）
- `==> Setup complete. Next steps:` 加四行指引

- [ ] **Step 2: 记录 wheel 命中情况**

观察 Step 1 的 `pip install` 输出，记录以下包是否使用了预编译 wheel（`Using cached ...whl`）vs 触发源码编译（`Building wheel ... `）：
- `lxml`、`Pillow`、`resvg-py`、`PyYAML`（带原生扩展的包）

记录结论到临时笔记（脑内或会话内），供 Task 6 使用。预期全部命中 manylinux wheel。

- [ ] **Step 3: 验证 venv 可用**

Run: `source .venv/bin/activate && python --version && python -c "import scp_epub; print('ok')"`
Expected: `Python 3.11.x` 与 `ok`。

- [ ] **Step 4: 诊断分支（仅当 Step 1 或 3 失败时执行）**

若失败：
- `ImportError` / `OSError` / 编译失败 → 判定为平台问题，按"小改 + 加测试 + 不重构"修复 `src/` 或脚本，回到 Step 1 重跑。
- 网络超时 / pip 源问题 → 重试，非平台问题。

若本步触发了代码或脚本修改，按修改内容单独 commit；否则本任务不产生 commit。

---

### Task 3: README.md 双示例 + Rocky 章节 + 跨平台环境要求

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 的脚本入口（`bash scripts/setup-rocky.sh`）
- Produces: 面向 Rocky/Linux 用户的环境准备文档；原有 Windows 内容保留

- [ ] **Step 1: 改"环境要求"段**

定位 `## 环境要求` 段（当前内容为 Windows-only 表述）。把第二条改为跨平台：

把：
```markdown
- Windows PowerShell、PowerShell Core 或其他可运行 Python 的终端
```

替换为：
```markdown
- Windows PowerShell、PowerShell Core，或 Linux（含 Rocky 9.x）/ macOS 上任意能运行 Python 的终端
```

其余两条（Python 3.11、可选 Calibre）保持不变。

- [ ] **Step 2: 新增"在 Rocky 9.x 上搭建"章节**

在 `## 环境要求` 段结束之后、`建议在虚拟环境中安装依赖` 之前，插入新章节：

```markdown
## 在 Rocky 9.x 上搭建

仓库提供一键搭建脚本，自动安装系统依赖、Python 3.11、虚拟环境和项目依赖，并完成自检：

​```bash
bash scripts/setup-rocky.sh
​```

该命令需要 `sudo`（用于 `dnf install`）。无 `sudo` 时可跳过系统依赖安装，改用已有的 Python 3.11（如通过 uv 安装）：

​```bash
bash scripts/setup-rocky.sh --skip-system-deps
​```

可选安装 Calibre 以启用 Kindle 构建：

​```bash
sudo dnf install calibre   # EPEL 仓库
​```

脚本完成后按提示激活虚拟环境即可开始构建。以下章节同时给出 Windows (PowerShell) 与 Linux / Rocky (bash) 两套命令示例。
```

（注意：上面内层代码块的反引号在最终文件中应为正常三个反引号；本计划中为避免嵌套冲突用 `​` 零宽占位示意，实际写入时去除。）

- [ ] **Step 3: venv 创建段改双示例**

定位"建议在虚拟环境中安装依赖"段。把：

```markdown
建议在虚拟环境中安装依赖：

​```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
​```

只运行构建、不运行测试时，也可以安装基础依赖：

​```powershell
pip install -e .
​```
```

替换为：

```markdown
建议在虚拟环境中安装依赖。

**Windows (PowerShell)：**

​```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
​```

**Linux / Rocky (bash)：**

​```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
​```

只运行构建、不运行测试时，也可以安装基础依赖。

**Windows (PowerShell)：**

​```powershell
pip install -e .
​```

**Linux / Rocky (bash)：**

​```bash
pip install -e .
​```
```

- [ ] **Step 4: 批量循环段加 bash 双示例**

定位"构建 Series 1 的全部分卷"段。保留原 PowerShell 块，把整段替换为双示例：

```markdown
构建 Series 1 的全部分卷。

**Windows (PowerShell)：**

​```powershell
$volumes = @("001-099","100-199","200-299","300-399","400-499","500-599","600-699","700-799","800-899","900-999")
foreach ($volume in $volumes) {
  python -m scp_epub --config config/series-1.yaml build --volume $volume
}
​```

**Linux / Rocky (bash)：**

​```bash
for v in 001-099 100-199 200-299 300-399 400-499 500-599 600-699 700-799 800-899 900-999; do
  python -m scp_epub --config config/series-1.yaml build --volume "$v"
done
​```
```

- [ ] **Step 5: 校验改动落位**

Run: `grep -c "Linux / Rocky (bash)" README.md`
Expected: 输出 `3`（Rocky 章节 0 + venv 段 2 + 基础依赖段 1 + 批量循环段 1 = 至少 3；实际为 4，确认 ≥3 即可）。

Run: `grep -n "在 Rocky 9.x 上搭建" README.md`
Expected: 命中一行章节标题。

Run: `grep -c "Windows PowerShell、PowerShell Core，或 Linux" README.md`
Expected: `1`（环境要求段已改跨平台）。

- [ ] **Step 6: 提交**

```bash
git add README.md
git commit -m "docs: add rocky 9 setup guide and bash examples to README

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: AGENTS.md 双示例

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: 与 README 一致的命令集
- Produces: bash 版命令供后续 agent 在 Rocky 上执行

- [ ] **Step 1: "构建、测试与开发命令"段加 bash 双示例**

`AGENTS.md` 的 `## 构建、测试与开发命令` 段当前每个命令块为 PowerShell 标注。按下表对每个锚点追加 `**Linux / Rocky (bash)：**` 双示例块（PowerShell 原块保留不动）：

| 锚点（当前 PowerShell 块后的命令） | 追加的 bash 块 |
| --- | --- |
| `pip install -e ".[dev]"` | `pip install -e ".[dev]"`（bash 下相同） |
| `pytest -q` | `pytest -q`（bash 下相同） |
| `python -m scp_epub --config config/series-1.yaml build --volume 001-099` | 相同命令，bash 标注 |
| `python -m scp_epub --config config/featured-scp.yaml build --volume featured` | 相同命令，bash 标注 |
| `python -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle` | 相同命令，bash 标注 |
| `python -m scp_epub --config config/series-1.yaml scan-linked-appendices --volume 001-099` | 相同命令，bash 标注 |
| `scp-epub --config config/series-1.yaml build --volume 001-099`（控制台命令） | 相同命令，bash 标注 |

对每个锚点，在原 PowerShell 块之后插入：

```markdown

**Linux / Rocky (bash)：**

​```bash
<与上表对应的命令>
​```
```

- [ ] **Step 2: 批量构建循环加 bash 双示例**

定位 `$volumes = @(...) ... foreach ($volume in $volumes) { ... }` 块（PowerShell）。在其后插入：

```markdown

**Linux / Rocky (bash)：**

​```bash
for v in 001-099 100-199 200-299 300-399 400-499 500-599 600-699 700-799 800-899 900-999; do
  python -m scp_epub --config config/series-1.yaml build --volume "$v"
done
​```
```

- [ ] **Step 3: 校验改动落位**

Run: `grep -c "Linux / Rocky (bash)" AGENTS.md`
Expected: `≥ 7`（7 个命令锚点 + 1 个批量循环 = 8，确认 ≥7）。

Run: `grep -c 'foreach (\$volume in \$volumes)' AGENTS.md`
Expected: `1`（PowerShell 原块保留）。

- [ ] **Step 4: 提交**

```bash
git add AGENTS.md
git commit -m "docs: add bash examples to AGENTS.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 端到端验证（pytest + series-1 + featured）

**Files:**
- 无文件改动（验证步骤；产物 `output/`、`data/raw/` 不入 git）

**前置：** Task 2 已完成，`.venv` 可用。

- [ ] **Step 1: 跑全量测试**

Run:
```bash
source .venv/bin/activate
pytest -q
```
Expected: 全部通过，末行形如 `N passed, M warnings in Xs`，0 failed。记录 N、M、Xs。

若出现 failure：
- 与平台相关（import、路径、编码、依赖）→ 判定平台问题，修 `src/` + 补 `tests/`，重跑。
- 与平台无关（既有 bug）→ 记录，不阻断本任务，但反馈给用户。

- [ ] **Step 2: 构建 series-1 `001-099`**

Run:
```bash
python -m scp_epub --config config/series-1.yaml build --volume 001-099
```
Expected:
- 退出码 0
- 生成 `output/epub/SCP基金会档案-故事系列-第1卷-第1册.epub`
- 生成 `output/reports/SCP基金会档案-故事系列-第1卷-第1册-report.json`
- 构建过程本身无平台异常（无 ImportError/OSError/路径错误）

记录耗时、`missing_pages` 与 `missing_assets` 计数。`missing_pages` 应为空或个位数；`missing_assets` 允许非零（外站资源，适配无关）。

- [ ] **Step 3: 构建 featured 精选**

Run:
```bash
python -m scp_epub --config config/featured-scp.yaml build --volume featured
```
Expected:
- 退出码 0
- 生成 `output/epub/SCP基金会档案精选.epub`
- 生成 `output/reports/SCP基金会档案精选-report.json`
- 构建过程无平台异常

记录耗时与 report 摘要。featured 验证 `featured-scp-archive` 模式。

- [ ] **Step 4: 平台 vs 源站问题分流**

对 Step 2、3 中 report 的 `missing_assets` 与日志中的失败项逐项判定：
- 外站域名（wikimedia、imgur、pinterest、`scp-wiki.net` 证书等）超时/404 → 源站问题，记录，不修。
- 同站资源加载失败伴随 Python 异常 → 平台问题，修。

本步不 commit。

---

### Task 6: 系统依赖回填 + 设计文档"验证结果"段

**Files:**
- Modify: `scripts/setup-rocky.sh`（仅当 Task 2 发现需要补 `-devel`）
- Modify: `docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md`（追加"验证结果"段）

**Interfaces:**
- Consumes: Task 2 的 wheel 观察记录、Task 5 的验证记录
- Produces: 最终固化的系统依赖清单与设计文档验证结论

- [ ] **Step 1: 固化系统依赖清单**

根据 Task 2 Step 2 的观察：
- 若 lxml / Pillow / resvg-py / PyYAML 全部命中 manylinux wheel（预期）→ `SYSTEM_PACKAGES` 维持 `(python3.11 python3.11-pip gcc redhat-rpm-config)` 不变。
- 若某个包触发源码编译 → 在 `scripts/setup-rocky.sh` 的 `SYSTEM_PACKAGES` 数组中追加对应 `-devel` 包（如 `libxml2-devel libxslt-devel` 对应 lxml，`libjpeg-turbo-devel zlib-devel` 对应 Pillow），并注释说明触发包。

若脚本有改动，重新执行 Task 1 的 Step 3 shellcheck。

- [ ] **Step 2: 设计文档追加"验证结果"段**

在 `docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md` 末尾（`## 非目标` 段之前）插入：

```markdown
## 验证结果

在 Rocky Linux 9.7（WSL2）上，通过 uv 提供的 python3.11、运行 `bash scripts/setup-rocky.sh --skip-system-deps` 完成环境搭建。

- **Python 依赖安装**：lxml、Pillow、resvg-py、PyYAML <命中 manylinux wheel | 触发源码编译并补 -devel>；纯 Python 包无系统依赖。（按 Task 2 观察如实填写）
- **`pytest -q`**：<N> passed, <M> warnings in <Xs>，0 failed。
- **series-1 `001-099`**：EPUB 与 report 生成，耗时 <T1>；`missing_pages` <计数>，`missing_assets` <计数>（均为外站源站问题，适配无关）。
- **`featured`**：EPUB 与 report 生成，耗时 <T2>；`missing_pages` <计数>，`missing_assets` <计数>。
- **系统依赖结论**：最终 `SYSTEM_PACKAGES` 为 `(python3.11 python3.11-pip gcc redhat-rpm-config<+ 回填项>)`。
- **代码改动**：<无 | 列出修复的平台问题及对应测试>。

已知局限（验证环境无 sudo）：脚本 dnf 段未 sudo 实跑；`python3.11` 模块属 RHEL 9 AppStream 官方支持，命令依据 Rocky 官方文档。功能层结论基于 uv python3.11，与 dnf python3.11 ABI 等价，可迁移。
```

填写时把 `<...>` 占位替换为 Task 2、Task 5 的实测数据。**禁止在最终提交里保留尖括号占位。**

- [ ] **Step 3: 校验设计文档无占位残留**

Run: `grep -nE '<[^>]+>' docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md`
Expected: 无输出（所有 `<...>` 占位已替换为实测数据）。若命中，回到 Step 2 补全。

- [ ] **Step 4: 提交**

```bash
git add scripts/setup-rocky.sh docs/superpowers/specs/2026-07-20-rocky-9-adaptation-design.md
git commit -m "docs: record rocky 9 verification results

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

（若 Step 1 未改动脚本，则 `git add` 只含设计文档。）

---

## Self-Review

**1. Spec coverage（对照 spec 各节）：**
- 交付物表 → Task 1（脚本）、Task 3（README）、Task 4（AGENTS）、Task 6（设计文档）
- `setup-rocky.sh` 结构（调用约定、9 步流程、关键设计点）→ Task 1 完整脚本覆盖
- 系统依赖策略（候选 + 回填）→ Task 1 候选集 + Task 6 回填
- 文档改动策略（环境要求、Rocky 章节、双示例）→ Task 3、Task 4
- 验证方案（uv 路径、成功标准、平台 vs 源站、已知局限）→ Task 2、Task 5、Task 6
- 错误处理 → 脚本内 `fail()`、Task 2 Step 4 诊断分支、Task 5 Step 4 分流
- 质量保障（shellcheck + 自检 + 端到端）→ Task 1 Step 3 + 脚本自检段 + Task 5

**2. Placeholder scan：** Task 6 Step 2 的验证结果模板含 `<...>` 占位，但 Step 3 有校验步骤强制替换并 grep 验证无残留；其余步骤代码完整，无 TBD/TODO。

**3. Type / 命名一致性：** 脚本变量 `SKIP_SYSTEM_DEPS`、`SYSTEM_PACKAGES`、`VENV_DIR`、`PY`、`REPO_ROOT` 在各步骤用法一致；命令 `bash scripts/setup-rocky.sh --skip-system-deps` 在 Task 2/Task 6 一致；产物路径与 README 声明一致。

无遗漏，无需补充任务。
