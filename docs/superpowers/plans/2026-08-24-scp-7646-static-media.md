# SCP-7646 静态图片与侧栏清理实施计划

1. 在 `tests/test_transform.py` 增加 SCP-7646 交互图片与饮水侧栏 fixture。
2. 先运行定向测试，确认当前实现会保留重复图片、全屏层与固定侧栏。
3. 在 `src/scp_epub/transform.py` 实现 slug 限定的静态化清洗，并接入转换流程。
4. 运行定向测试、相关转换测试和完整 `pytest -q`。
5. 重建 Series 8 的 `7600-7699`、Featured 普通版和 Featured Kindle Scribe 稳定版。
6. 检查三个 EPUB 内 SCP-7646 XHTML，确认图片数量、静态尺寸、说明文字与侧栏删除结果。
7. 检查工作区差异，只提交本次 SCP-7646 相关文件，并记录产物路径。
