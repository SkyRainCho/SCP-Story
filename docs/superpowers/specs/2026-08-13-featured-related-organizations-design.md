# Featured 附录相关组织子页面设计

## 背景与目标

Featured 精选集的“附录 → 相关组织”页面当前只作为一个二级附录页面收录。该页面实际包含 46 个组织卡片，每个卡片的标题链接指向对应组织介绍/中心页，例如：

- `Alexylva大学` → `/alexylva-university-hub`
- `安布罗斯餐厅` → `/ambrose-restaurant-hub`

目标是在保留“相关组织”概览正文的同时，自动从该页面提取当前全部组织中心页，将其作为三级目录子页面收录。以后网站新增或移除组织时，构建应随索引页面内容自动同步。

## 方案选择

为附录 section 新增专用模式 `organization-links`，复用现有 `AppendixSection.mode` 和附录抓取流程：

```yaml
    - title: 相关组织
      url: /groups-of-interest
      mode: organization-links
```

不采用以下方案：

- 在 YAML 中固定列出 46 个组织：无法自动同步网站后续变更。
- 通过通用 CSS 选择器配置：当前只有相关组织需要该结构，专用模式更易测试和维护。
- 使用全局高置信链接扫描：会递归或误收录组织卡片中的 SCP、故事、标签和普通引用。

## 数据流与目录层级

1. Featured manifest 构建按现有逻辑抓取 `/groups-of-interest`，并把该页面作为二级 `appendix-section` 保留。
2. `extract_organization_children` 只扫描该页面 `#page-content` 下的直接组织卡片：每个 `div.content-panel.standalone.series` 中取直接 `h1` 的第一个同站链接。
3. 子页面标题使用标题链接的可见中文文本，去除多余空白；不使用括号内英文全称。
4. 子页面 URL 通过现有同站 URL 规范化，仅保留 `scp-wiki-cn.wikidot.com` 页面链接，移除查询、片段和其他 URL 变体。
5. 子页面按卡片在索引中的出现顺序生成，层级为 3，父级为 `groups-of-interest`，角色为新的 `appendix-organization`。
6. 组织中心页作为真实 manifest 页面抓取、清洗并写入 EPUB；不递归追踪组织中心页中的链接。

最终目录形态：

```text
附录
└─ 相关组织
   ├─ Alexylva大学
   ├─ 安布罗斯餐厅
   ├─ 安德森机器人
   └─ ……按索引页面顺序
```

## 去重与过滤

- 同一规范化 URL 或 slug 只生成一个子页面，保留首次出现的中文标题和位置。
- 标题缺失、链接缺失、锚点链接、标签页链接、站外链接、邮件链接不进入子页面。
- 只接受与配置 `base_url` 同 authority 的 HTTP(S) 页面链接。
- 组织卡片中除标题链接外的地点、SCP、故事、标签和“回到顶部”链接全部忽略。
- 若页面结构不含任何有效组织卡片，保留“相关组织”正文，不生成空的子页面组，也不报错。

## 缓存、刷新与错误处理

- 普通构建继续沿用 manifest 和页面缓存，不额外强制联网。
- 使用 `--force` 时重新抓取“相关组织”索引，从新内容生成组织子页面并刷新其页面缓存。
- 某个组织中心页抓取失败时，沿用现有 manifest 页面缺失处理：记录 `missing_pages`，其余组织和索引正文继续构建。
- 不改变普通 Series 1–8 配置；该行为仅用于 Featured 的“相关组织”section。

## 配置与实现边界

- `src/scp_epub/models.py`：为 `AppendixSection` 模式增加 `organization-links` 的合法值说明（如当前类型无需变更则保持 dataclass 不变）。
- `src/scp_epub/config.py`：允许解析 `organization-links`。
- `src/scp_epub/appendix.py`：新增 `APPENDIX_ORGANIZATION_ROLE` 与 `extract_organization_children`，复用同站 URL 规范化辅助逻辑。
- `src/scp_epub/pipeline.py`：在 `_featured_appendix_entries` 中调用解析器，并把子页面挂在 `groups-of-interest` 下；现有 `facility-links`、`tabs-as-pages` 行为不变。
- `config/featured-scp.yaml`：将“相关组织” section 增加 `mode: organization-links`。

## 测试与验收

### 解析器测试

- 从最小 HTML 提取多个组织卡片，验证中文标题、规范化 URL、slug、顺序、level、parent_slug 和 role。
- 确认只读取卡片 `h1` 标题链接，不误收录卡片正文中的地点、SCP、故事、标签、站外和锚点链接。
- 验证相同 URL 的查询/片段变体去重。
- 验证缺少有效卡片时返回空列表。

### 配置测试

- Featured 的“相关组织”模式为 `organization-links`。
- 其他附录 section 的模式和现有配置保持不变。
- 非法模式仍被拒绝，并更新错误信息允许值列表。

### 流水线测试

- Featured manifest 在“附录 → 相关组织”后按输入顺序插入组织三级页面。
- 组织中心页只抓取一层；组织正文中的链接不产生额外 manifest 条目。
- 组织页面抓取失败只增加对应缺失记录，不移除其他组织或相关组织正文。
- 现有设施、标签页附录和普通 Featured 构建回归通过。

### 实际构建验收

运行目标测试和完整 `pytest -q`，再执行：

```powershell
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured
.\.venv\Scripts\python.exe -m scp_epub --config config/featured-scp.yaml build --volume featured --kindle-stable
```

检查普通精选 EPUB、Kindle Scribe EPUB/AZW3 与报告：

- 报告中存在 `groups-of-interest` 后的 46 个三级组织页面（以当前缓存为准）。
- 首两个页面标题分别为 `Alexylva大学`、`安布罗斯餐厅`，对应 slug 为 `alexylva-university-hub`、`ambrose-restaurant-hub`。
- 每个组织页面只出现一次，父级为 `groups-of-interest`，未把组织卡片正文中的普通链接递归纳入。
- 组织页面正文可在 EPUB 中读取，压缩包 `testzip()` 通过。

## 非目标

- 不修改组织页面正文或翻译内容。
- 不把组织页面中的 SCP、故事、地点或标签页面作为相关组织子页面。
- 不改变全局 linked appendix 扫描规则。
- 不把该自动解析模式扩展到 Series 1–8。
