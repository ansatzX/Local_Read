# AGENTS.md — Local_Read 代码维护约定

## 项目目标

Local_Read 是以离线 PDF 阅读为重点的 Skill 与 Python CLI。它为智能体提供文档提取、范围选择、分段组织和可追溯的磁盘产物，也支持 Office、HTML、ZIP 等格式。

MinerU 是常规软件依赖，负责模型与深度 PDF 解析；模型权重仍按需显式准备。维护 Local_Read 时复用它的下载器、模型目录、推理引擎、hybrid analyzer 和输出构建能力，不复制模型实现、不维护 MinerU 分叉。项目没有 MCP 服务。

命名保持一致：产品与分发为 `Local_Read`，技能与命令为 `local-read`，Python 包为 `local_read`。

## 运行约定

- 保持调用者的 cwd。文档产物及工作临时文件写入 cwd 下的 `.local_read_mcp/`，不得写进技能安装目录。
- 模型默认在 `~/.cache/local-read/models/`；运行环境默认在 `~/.cache/local-read/runtime/`。分别支持绝对路径 `LOCAL_READ_MODEL_DIR`、`LOCAL_READ_RUNTIME_DIR`。
- 运行环境按平台、包代码与依赖锁内容区分，相同版本跨项目和安装位置复用。修改代码后需为新版本准备环境。
- `setup` 和 `models prepare` 是显式准备操作；`convert` 解析阶段使用已安装环境与本地模型，不隐式下载、安装或调用远程 API。显式 `--visual-review auto|online` 可在离线解析完成后使用配置的 VLM；默认 offline 不得调用 API。
- 仅保留 `AUTO`、`SIMPLE`、`VLM_HYBRID` 后端选择。Simple 无模型依赖；MinerU 仅处理 PDF。`analyze` 是独立的外部视觉 API 操作。
- 保持运行环境锁，避免安装与读取互相干扰。模型准备锁必须覆盖下载、校验及配置和清单发布；失败不得发布未验证配置。托管配置读取遵守同一锁约定。
- 不把 Python 网络防护描述成操作系统沙箱；不把文件就绪描述成推理就绪或识别准确。

## 输出与来源约定

- 每次处理使用独立输出目录。CLI stdout 保持简洁 JSON，正文和大对象落盘，诊断走 stderr。
- `complete` / `partial` / `failed` 对应 0 / 2 / 1；参数解析和安装错误不保证 JSON。全部分块失败必须报告失败。
- 后端失败可警告并降级；保留实际处理信息，不把降级后的结果说成 MinerU 结果。
- `quality_state`、`requires_ocr` 与执行状态分别处理。提取为空不能证明原文为空。
- 命令的物理页范围为 0-based inclusive。统一 IR 块页码为原始 PDF 的 1-based 物理页；切片保存前映射一次，合并时不可重复偏移。
- 保留逻辑页映射的证据与不确定性。未知 `page`、`bbox`、识别置信度使用 `null`，不得用第 1 页、零矩形或固定高分代替未知。
- 坐标需明确坐标系和页旋转信息。原始 MinerU JSON 保持上游语义，与统一 IR 区分。
- 处理重叠页时避免重复正文；章节与表格注释不能再次输出同一份正文。图号关联、图片去重和表格恢复不得冒充已验证事实。

图片复核保留 `original` 与 `effective`，不得改写原始提取证据。区域、类别、关联分别记录检查结果；规则通过、VLM 复核与仍有歧义必须区分。VLM 响应在应用前完整校验当前页的区域 ID、图注 ID、坐标、类别及覆盖范围；失败保留离线状态。拆分/合并提议仍是歧义项，不能冒充已完成的区域重建。复核状态与 CLI 转换状态分开，异常不得丢弃成功提取的文档。任何显式 `--visual-review` 模式都启用图片提取，且仅用于 PDF；未指定模式时，PDF 的 `--extract-images` 触发离线复核。`auto` 仅复核规则标记的可疑页，`online` 复核检测到区域的页；二者均受 `--review-max-pages` 限制，不能把预算耗尽报告成全部完成。

## 代码入口

| 路径 | 职责 |
| --- | --- |
| `SKILL.md` | 使用技能的智能体如何选择、调用和读取结果 |
| `README.md` | 用户安装、使用、配置与能力边界 |
| `references/usage.md` | 按需读取的高级选项及产物说明 |
| `scripts/local_read.py` | 定位技能、共享运行环境与启动 CLI |
| `scripts/package_skill.py` | 按白名单打包技能 |
| `src/local_read/cli.py` | 参数、状态摘要与退出码 |
| `src/local_read/local_runtime.py` | 共享路径、运行环境标识、进程锁与离线防护 |
| `src/local_read/models.py` | 模型准备、配置与文件就绪检查 |
| `src/local_read/processing.py` | 文档处理入口和结果组织 |
| `src/local_read/orchestrator.py`、`segmenter/` | 页范围、章节、切片与合并 |
| `src/local_read/backends/`、`converters/` | 后端适配与格式转换 |
| `src/local_read/intermediate_json.py`、`index_generator.py`、`markdown_converter.py` | 统一结构、索引与正文输出 |
| `src/local_read/vision.py`、`vision_batch.py` | 可选图片 API 分析 |
| `src/local_read/visual_review.py` | 页面区域、类别、图注规则检查及显式 VLM 复核 |

## 修改与验证

包内使用相对导入，测试使用绝对导入。共享处理逻辑放在 Python 模块中，CLI 只负责调用与呈现。模型推理模块保持延迟导入；软件依赖统一安装，但 Simple 转换不应加载模型，API 客户端只在显式 `analyze` 或 `--visual-review auto|online` 中使用。

用 `make test` 运行回归测试。针对行为变更检查可观察结果：真实文件流、JSON 与退出码、文件位置、来源页码、失败恢复和并发互斥。PDF 回归优先生成可核对的样本；MinerU 与 API 适配使用 mock。真实模型、真实论文和外部 API 验收是单独任务，不以单元测试替代。

测试与审计产物放在 `.local_read_mcp/`。验证全局缓存行为时，将路径覆盖到测试目录，避免修改真实用户模型和配置。依赖调整先隔离解析与验证，保留锁文件及其他正在进行的工作。

修改命令、后端、目录或配置时同步更新 `SKILL.md`、`README.md`、`references/usage.md` 和本文件中的相关约定。`CLAUDE.md` 仅引用本文件，不维护另一套规则。文档描述当前行为，避免添加阶段总结、完成宣言或重复操作手册。Skill 保持精简，高级细节放在引用文档中。

发布前运行 `make skill`，核对必要入口和引用文件。压缩包只能包含白名单文件，不能包含 `.env`、实际 `mineru.json`、模型、运行环境、测试输出或密钥。不要因普通代码修改自动下载模型、调用 API、提交 Git 或发布版本。
