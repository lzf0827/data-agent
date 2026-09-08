# SKU Data Insight Agent UI Design Workplan

## Goal

将页面从“线性表单”升级为“分析工作台”，但保持 Excel 分析输出中的图表、表格、数值和下载格式完全不变。

## Design principles

1. 一个对话入口：用户先选择分析能力，再显示该能力的具体操作。
2. 渐进式披露：识别意图、数据审核、映射确认和计划审批只在 Excel 模式中出现。
3. 工作区上下文可见：当前文件、对话模式、运行状态和证据位置应可被快速确认。
4. 结果区稳定：`renderTrendChart`、月度对比表和正式报告下载区域只做容器适配，不改数据和可视化实现。
5. 失败可恢复：上传、解析、审批和生成状态使用明确的状态提示，不用静默 loading。
6. 安全边界可理解：页面清楚标注 Excel 严格链路与文档自由分析链路的差异。

## Phases

### Phase 1 — 已实施：模式入口与渐进式交互

- 增加统一“新建对话”模式选择器；
- Excel 与文档能力作为两个按钮；
- 默认隐藏两条功能链路的具体控件；
- 选择 Excel 后展示上传、Recognize intent、Review、Generate report；
- 选择文档后展示 Workspace、文件上传、多轮输入和 Markdown 导出；
- 保留原有结果卡片和输出可视化 DOM。

### Phase 2 — 分析工作台布局

- 增加响应式三栏布局：会话/文件、中央对话、右侧证据与执行状态；
- 将当前 `message`、计划审批和确认卡片改为可折叠状态面板；
- 对移动端退化为上下堆叠布局；
- 增加键盘焦点、空状态、上传进度和错误恢复。

### Phase 3 — 证据与轨迹交互

- Finding 以卡片展示，区分 verified fact、document claim、inference 和 hypothesis；
- 点击页码/幻灯片定位到 EvidenceRef；
- ToolEvent 默认折叠，失败事件可展开查看；
- 显示当前上下文包含哪些 Artifact、Finding 和最近 Turn。

### Phase 4 — 视觉与可用性验收

- 维持现有品牌色与正式报告视觉，不修改报告图例；
- 完成桌面端、窄屏和键盘操作验收；
- 用真实 Excel、PDF、PPTX、DOCX 完成上传、恢复、审批和导出走查；
- 验证原有 Excel 测试和输出哈希不变。

## Out of scope

- 不改 Excel 分析数值、图表、表格、DuckDB 和 PDF 生成逻辑；
- 不引入第二套前端框架；
- 不在 UI 层绕过映射确认、质量门禁或人工审批。
