# Local_Read 使用参考

本参考随轻量 Skill 分发。保持 cwd 为用户项目，使用固定入口 `"$HOME/.local/bin/local-read"`。缺少 CLI 时报告缺失，不在技能或项目内临时安装。

## 命令与联网边界

| 命令 | 用途 | 网络行为 |
| --- | --- | --- |
| `doctor` | 查看安装位置、版本、来源及入口冲突 | 不联网，不创建安装或文档产物 |
| `--version` | 查看程序版本 | 不联网 |
| `models status` | 检查 MinerU 包与模型文件 | 不下载，不加载模型推理 |
| `models prepare` | 用 MinerU 下载器缓存模型 | 显式联网，不安装或升级 CLI |
| `convert FILE` | 解析本地文档 | 解析阶段离线 |
| `convert FILE --visual-review auto` | 解析后复核可疑 PDF 页面 | 显式允许调用配置的 VLM API |
| `analyze IMAGE --question TEXT` | 对现有图片提问 | 调用配置的外部 API |

`--backend auto` 选择本地解析后端；`--visual-review auto` 决定哪些可疑页发送到 API。两者独立，前者不会启用后者。

## 安装诊断

```bash
"$HOME/.local/bin/local-read" doctor
"$HOME/.local/bin/local-read" --version
```

| doctor 字段 | 含义 |
| --- | --- |
| `version`、`python`、`environment`、`package_directory` | 当前进程实际使用的版本、解释器和程序位置 |
| `managed` | 当前 Python 环境是否位于预期托管位置 |
| `canonical_cli`、`installation_root` | 固定入口与用户级安装根目录 |
| `installation_source` | 安装元数据记录的来源；没有记录时标记未知 |
| `path_candidates` | PATH 中可执行的同名入口及其目标 |
| `legacy_environments` | 默认旧缓存 `~/.cache/local-read/runtime/` 下发现的环境 |
| `warnings` | 非托管执行、入口缺失、重复安装、editable 安装等提示 |

`success=true` 和退出码 0 表示诊断已返回，不代表没有冲突。仍须查看 warnings；`managed=true` 只检查环境位置，不验证签名或文件完整性。扫描不覆盖全盘、自定义旧缓存或所有虚拟环境，也不删除文件。

程序环境固定为 `~/.local/share/local-read/tools/local-read/`。安装器只存在于完整源码发行中：`python3 scripts/install_cli.py`，升级加 `--upgrade`；它不在 Skill 包里。运行时不需要 uv，不跟随源码变化，只保留一个活动版本。升级前结束活动任务；回退需从可信旧发行重新安装，没有中断后的自动回滚。

## PDF 范围与分段

```bash
# 第 11–20 个物理页面，两端包含
"$HOME/.local/bin/local-read" convert book.pdf --start-page 10 --end-page 19 --strict-page-range
# 根据目录规划章节
"$HOME/.local/bin/local-read" convert book.pdf --chapter-split chapter
# 请求规划大小，有目录时仍可能优先使用目录
"$HOME/.local/bin/local-read" convert book.pdf --chapter-split 32
"$HOME/.local/bin/local-read" convert book.pdf --chapter-split off
# 按逻辑页号解析，须核对映射证据
"$HOME/.local/bin/local-read" convert book.pdf --page-range-mode logical --start-page 1 --end-page 8 --strict-page-range
```

默认 `--chapter-split auto` 对超过 30 页的 PDF 分段，使用目录、检测标题或固定分块；`--page-batch-size` 默认 64，供固定分块后备用。分块可能重叠，整数参数不是精确每块页数保证，应检查实际范围。

物理范围从 0 开始、两端包含；逻辑页号可依据 PageLabels 或推测偏移映射。查看 `resolved_page_map`、`toc_confidence` 和警告。精确摘取优先使用物理页与 `--strict-page-range`，避免章节规划扩大范围。

统一 `intermediate.json` 的块页码为原始 PDF 的 **1-based 物理页码**，分块文件也已经映射，不要再加偏移。未知 page、bbox 为 null。MinerU 原始 JSON 保留上游分块内编号；引用原文以统一页码为准。

## 提取选项与其他格式

| 参数 | 作用 |
| --- | --- |
| `--backend auto\|simple\|vlm-hybrid` | 自动选择或请求指定后端；失败仍可能降级 |
| `--extract-images` | 提取图片；PDF 成功解析部分同时进行离线复核 |
| `--render-images`、`--render-dpi 200`、`--render-format png\|jpeg` | 转换器的图片渲染选项 |
| `--include-coords` | 请求位置数据；未知位置仍为 null |
| `--extract-forms`、`--inspect-struct` | 请求 PDF 表单与结构检查 |
| `--no-page-breaks`、`--no-metadata` | 通过通用 IR 转换器重新生成 Markdown |
| `--format FORMAT` | 覆盖扩展名推断的格式 |

Simple 提图需要显式请求。MinerU 即使未指定 `--extract-images`，也可能为 Markdown 重建保存图片、表格裁图；这些裁图不代表已运行 Local_Read 复核。保留 MinerU 原生公式与表格排版时，通常不要启用重新生成 Markdown 的两个 `--no-*` 参数。

格式覆盖支持 pdf、word、excel、ppt、html、zip，默认按扩展名识别。旧 Office 二进制格式取决于实际转换器能力。

```bash
"$HOME/.local/bin/local-read" convert report.docx --backend simple
"$HOME/.local/bin/local-read" convert data.xlsx
"$HOME/.local/bin/local-read" convert slides.pptx
```

## 产物与失败恢复

每次转换创建 `.local_read_mcp/<文件名>_<时间>_<标识>/`，包含 output.md、intermediate.json、index.json、result.json。分段文档另有分块产物及 structural_toc.json；提图可能产生 images/、image_manifest.json 和图号映射模板。具体路径以返回值中的 files 为准。

MinerU 另存 mineru_middle.json、mineru_content_list.json，可从顶层或分块文件条目找到。统一 IR 保留原始 MinerU 块和来源信息；识别置信度未知时为 null。原生 Markdown 由上游构建器重建。

stdout 返回摘要 JSON，大对象与正文落盘。`complete` / `partial` / `failed` 对应退出码 0 / 2 / 1；参数错误也可能是 2，且不一定有 JSON。partial 时通过 `files.chunks` 定位失败范围，只重试缺失部分。`quality_state=unreadable` 仍可与转换完成同时出现，不能将空提取解释为原文为空。

图号映射仍有启发式成分，底层块置信度不等于校准概率；多分块的顶层 backend_used 在降级后可能仍表示原先选定后端。结合分块来源和警告判断实际路线。

## 本地 MinerU 模型

```bash
"$HOME/.local/bin/local-read" models status
"$HOME/.local/bin/local-read" models prepare --source huggingface
"$HOME/.local/bin/local-read" convert paper.pdf --backend vlm-hybrid --mineru-effort medium
```

models prepare 复用 MinerU 3.4.5 下载器的 `--model_type all`，准备 pipeline 和 VLM 权重；来源可选 huggingface、modelscope、auto。中断下载保留上游缓存，不同来源或修订可能分别占用空间。

全局模型根目录默认 `~/.cache/local-read/models/`，包含缓存、托管 mineru.json 和 model_manifest.json。其他磁盘可在启动前设置绝对路径 LOCAL_READ_MODEL_DIR。就绪检查不加载模型，不核验权重签名，也不能证明硬件足够或 OCR 准确。

配置选择顺序：进程环境 MINERU_TOOLS_CONFIG_JSON → 全局模型目录托管配置 → cwd 的 .local_read_mcp/models/mineru.json → 用户配置目录中的 mineru.json。配置的 models-dir.pipeline 和 models-dir.vlm 指向模型目录，相对路径按配置所在目录解析，推荐绝对路径。源码中的 mineru.json.template 仅为占位示例，需替换两个目录再使用。准备命令始终更新托管配置，显式配置覆盖仍优先，直到取消该变量。

`--mineru-engine auto|transformers|mlx|vllm|lmdeploy` 交给 MinerU 选择引擎。常规安装提供 transformers 路线；加速引擎需另行验证兼容安装，不能在 Skill 中临时创建第二套 CLI。`--mineru-effort medium|high` 控制 hybrid effort。

解析使用本地配置与模型离线设置，禁用上游 LLM API 后处理。Python 层阻止外部 DNS/socket，允许本地引擎回环连接；这不等于原生代码和子进程的操作系统网络沙箱。缺少资源时本地失败或降级 Simple，不自动切换托管 API。

## PDF 图片区域复核

| 模式 | 触发与覆盖 |
| --- | --- |
| offline | PDF 的 --extract-images 默认触发；也可显式指定 --visual-review offline |
| auto | 显式允许 API，只处理规则标记的可疑页 |
| online | 显式允许 API，处理检测到视觉区域的页，受页数预算限制 |

任何显式 --visual-review 都启用提图且仅支持 PDF。复核只覆盖成功解析页上检测到的区域；普通转换未请求提图时不生成复核报告。联网或配置密钥本身不会启用 API。

```bash
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review offline
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review auto --review-max-pages 8
```

--review-max-pages 为正整数，默认每次转换最多 8 个页面请求。请求逐页串行，超时 60 秒，不自动重试。API 接收整页原图、编号框图、区域裁图和图注元数据，发生在离线解析结束之后。

files.visual_review 指向 visual_review/review.json；stdout 和 result.json 的 visual_review 摘要含模式、状态、区域数、未解决数量与请求数。转换状态和复核状态独立：

| 复核状态 | 含义 |
| --- | --- |
| rule_passed | 规则未发现冲突，未证明识别正确 |
| vlm_reviewed | VLM 已复核，不是科学结论验证 |
| needs_review | 尚有疑点，或 API 不可用、失败、预算耗尽 |
| no_regions_detected | 未检测到区域，不能证明没有图片 |
| failed | 复核准备失败；成功提取的文档仍保留 |

报告分别保存 original、effective、边界/类别/图注检查、模型决策与依据。original_crop、effective_crop 区分原裁图和修订裁图。页码为 1-based 物理页，坐标为未旋转页面的 PyMuPDF 点坐标。原始 MinerU 证据和图片清单不被覆盖；清单首选图号匹配仍是未验证候选。

每页 VLM 响应先完整校验区域 ID、图注 ID、类别、边界和覆盖范围，再应用修订。拆分/合并仅保留歧义建议，不自动重建区域。失败保留离线结果。

auto 会遗漏规则未标记的问题；整页扫描件可能只形成一个大区域；缺乏可靠映射的旋转 MinerU 坐标不直接复用，程序尝试 PDF 原生区域后备。所有状态均不能证明没有漏图。

## API 配置与单独图片分析

默认读取 `~/.config/local-read/.env`，进程环境的同名变量优先。LOCAL_READ_CONFIG_DIR 必须在启动前设为绝对目录；仓库/Skill .env 不会自动加载。模型目录等路径变量同样应在启动前 export，不依赖 API 配置文件的加载时机。

| 配置 | 用途与后备 |
| --- | --- |
| VISION_API_KEY | 密钥；后备 OPENAI_API_KEY |
| VISION_BASE_URL | 兼容 API 地址；后备 OPENAI_BASE_URL，否则使用 SDK 默认地址 |
| VISION_MODEL | 服务商支持的模型；后备 OPENAI_VISION_MODEL，程序默认 gpt-4o |
| VISION_MAX_IMAGE_SIZE_MB | 默认 20；单图分析文件大小上限，或单页复核发送图片的原始字节总量上限 |

```bash
"$HOME/.local/bin/local-read" analyze figure.png --question "解释坐标轴与图例"
"$HOME/.local/bin/local-read" analyze a.png b.png --question "逐一描述图片"
```

analyze 需要 API 配置，结果与内容缓存保存在 cwd 的 .local_read_mcp/analysis/。--batch-size 默认 6，但当前批处理仍逐图串行，不代表并发数。没有密钥时返回失败，不调用 API。不要把密钥写进技能说明或命令参数。
