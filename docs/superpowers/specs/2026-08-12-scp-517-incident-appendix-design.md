# SCP-517 事件文档附属收录设计

## 背景与目标

`SCP-517 - 自动预言机` 正文链接到简体中文页面：

- 标题：`事件517-1997-M`
- URL：`https://scp-wiki-cn.wikidot.com/incident-517-1997-m`
- slug：`incident-517-1997-m`

目标是在 Featured 精选集和 Series 1 的 `500-599` 册中，都把该页面作为 SCP-517 下的“原文附属文档”收录。当前构建报告能看到主文档请求过此 URL，但保守的自动扫描没有把它加入目录；本次不放宽全局扫描规则。

## 方案选择

在 `config/featured-scp.yaml` 与 `config/series-1.yaml` 中分别使用现有 `explicit_linked_appendices` 声明同一附件：

```yaml
explicit_linked_appendices:
  scp-517:
    - title: 事件517-1997-M
      url: https://scp-wiki-cn.wikidot.com/incident-517-1997-m
```

未采用的方案：

- 放宽 `linked_appendices.py` 对所有 `incident-*` 链接的识别：会扩大所有页面的候选范围，增加普通交叉引用误报风险。
- 在流水线中硬编码 SCP-517：难维护，且绕过现有配置模型。

## 构建行为

1. manifest 仍按现有逻辑包含 SCP-517 主文档。
2. `_configured_linked_appendix_documents` 将配置转换为一个候选附件。
3. 配置候选与自动扫描候选通过现有 slug 去重逻辑合并。即使以后扫描规则能够识别同一 URL，正文中也只收录一次 `incident-517-1997-m`。
4. 成功抓取后，在 SCP-517 后插入一个二级“原文附属文档”分组，并在其下插入三级 `事件517-1997-M` 页面。
5. 附件只展开这一层，不继续追踪事件页中的其他链接。
6. Featured、Series 1 普通 EPUB 及其 Kindle 变体沿用相同的 manifest 与页面处理结果。

## 错误处理

事件页抓取失败时，沿用现有附属文档失败处理：SCP-517 主文档继续进入 EPUB，失败信息写入构建报告，事件页不以空白占位符进入正文。本次不增加 fallback 或浏览器抓取行为。

## 测试

### 配置测试

- `featured-scp.yaml` 精确声明 SCP-517 的附件标题、URL 和 slug。
- `series-1.yaml` 精确声明相同附件。
- Series 2–8 配置不受影响。

### 流水线测试

- SCP-517 的构建顺序为：主文档、`scp-517--linked-appendices` 分组、`incident-517-1997-m`。
- 附件标题为 `事件517-1997-M`，角色为 `linked-appendix`，父级为分组 slug。
- 同一 slug 同时出现在显式配置和扫描结果时只抓取、只收录一次。
- 事件页内的链接不递归展开。
- 事件页抓取失败不移除 SCP-517 主文档。

## 验收

运行：

```powershell
pytest -q tests/test_config.py tests/test_pipeline.py
pytest -q
python -m scp_epub --config config/featured-scp.yaml build --volume featured
python -m scp_epub --config config/series-1.yaml build --volume 500-599
```

检查两个报告和 EPUB：

- `scp-517--linked-appendices` 紧随 SCP-517。
- `incident-517-1997-m` 只出现一次，并位于该分组下。
- 正文包含“事件517-1997-M”及事件记录内容。
- SCP-517 和事件页均不在 `missing_pages` 中。

## 非目标

- 不改变全局高置信附属文档扫描规则。
- 不修改 SCP-517 或事件页正文。
- 不为其他 Series 配置加入该附件。
- 不递归抓取事件页中的链接。
