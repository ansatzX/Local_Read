# Local_Read

Local_Read 由一份用户级 CLI 和轻量 Skill 说明组成，以学术 PDF 阅读为重点。CLI 将文档转换为 Markdown、索引、图片和带来源信息的结构化文件；各智能体宿主通过自己的 Skill 说明调用同一份程序。也支持 Word、Excel、PowerPoint、HTML 和 ZIP 的本地转换。

项目通过 **Skill + CLI** 使用。MinerU 提供深度 PDF 解析与模型推理基础设施；Local_Read 负责本地资源准备、后端选择、页码与分段处理、结果保存、图片区域与图注复核及智能体使用流程。

## 开始使用

用户级统一安装目前面向 macOS/Linux，需要 Python 3.10+ 和 `uv`。在包含 pyproject.toml、uv.lock、scripts 和 src 的完整可信源码发行目录执行一次：

```bash
python3 scripts/install_cli.py
"$HOME/.local/bin/local-read" doctor
```

固定入口为 `~/.local/bin/local-read`，程序与依赖安装在 `~/.local/share/local-read/tools/local-read/`。安装器使用 uv tool、Python 3.12 和从 `uv.lock` 导出的依赖版本约束，安装非 editable 的程序副本，不下载模型权重。普通调用不需要 uv，不创建环境，也不跟随源码修改。

升级在选定的新版源码目录执行 `python3 scripts/install_cli.py --upgrade`。重复安装必须显式指定升级；安装器拒绝覆盖非托管的同名入口。只保留一个活动版本，回退需从可信旧发行目录重新安装。升级前结束正在执行的任务；托管 CLI 与安装器使用同一进程锁，但不提供零停机热升级或安装中断后的自动回滚。

CLI 安装后，再生成供智能体宿主使用的 Skill 分发包：

```bash
python3 scripts/package_skill.py
```

产物为 `.local_read_mcp/dist/Local_Read.zip`，内含 `local-read/` 目录。解压到宿主技能目录后即可发现该技能。包内仅有说明、引用、宿主元数据和许可证，不含源码或安装器。多个宿主各自保留说明，共用同一个 CLI；只安装 Skill 不会安装 CLI。

在需要读取文档的项目目录中执行：

```bash
# 使用固定入口离线读取
"$HOME/.local/bin/local-read" convert paper.pdf

# 读取第 11–20 个物理页面
"$HOME/.local/bin/local-read" convert paper.pdf --start-page 10 --end-page 19 --strict-page-range

# 同时提取图片并执行离线规则检查
"$HOME/.local/bin/local-read" convert paper.pdf --extract-images
```

也可以直接让智能体“使用 `$local-read` 阅读这份 PDF 的第 11–20 页”。调用时保持工作目录在自己的项目内，输出位置取决于工作目录。

## 安装诊断与迁移

`doctor` 只读报告当前 Python、包目录、版本、安装来源、固定入口、PATH 中的重复程序及默认旧缓存中的源码哈希环境。它不全盘搜索，也不自动删除安装。推荐固定入口，避免 PATH 中另一份同名程序被选中。

诊断返回成功只代表报告已生成，仍要检查 `warnings`。`managed=true` 只说明当前 Python 环境位于托管目录，不证明代码未被修改。版本和来源来自当前安装元数据；修改开发源码后，这份已安装程序不会自动改变。

| 安装问题 | 处理方式 |
| --- | --- |
| 已存在托管安装 | 在选定发行目录显式运行 `--upgrade` |
| 固定入口指向另一套安装 | 先确认旧入口来源并自行迁移，安装器不会直接覆盖 |
| 无网且依赖缓存缺包 | 联网执行安装；普通读取不会代为补装 |
| 升级中断或环境不完整 | 保留错误输出，选定可信发行后用 `--upgrade` 重试；不保证自动恢复旧版 |

安装约束文件写在调用目录的 `.local_read_mcp/install/constraints.txt`。安装日志走 stderr，成功时 stdout 返回安装路径 JSON；安装失败不保证 JSON。

旧版 `scripts/local_read.py`、`setup` 和 `LOCAL_READ_RUNTIME_DIR` 已退役。迁移时执行一次统一安装并更新 Skill；旧模型仍可复用，旧运行环境根据诊断结果自行清理。API 配置统一放在 `~/.config/local-read/.env`，不再自动加载仓库或技能目录中的 `.env`；绝对路径 `LOCAL_READ_CONFIG_DIR` 可覆盖配置目录。

统一安装解决副本与版本混乱；用户可写目录仍可被同一用户修改。目前未提供发行签名验证或操作系统级防篡改。

## PDF 的两条解析路线

| 路线 | 适用场景 | 所需资源 |
| --- | --- | --- |
| `simple` | 有文字层的 PDF、普通文档转换 | 使用统一安装的软件依赖，无需模型权重 |
| `vlm-hybrid` | 扫描件，以及需要布局、OCR、公式、表格等解析能力的 PDF | MinerU 依赖、本地模型及适用硬件 |

默认 `auto` 对 PDF 优先选择本地就绪的 MinerU，否则使用 Simple。请求 MinerU 后发生失败，也可能降级为 Simple；实际结果和警告会随返回值提供。其他格式走本地转换器。

`--backend auto` 只选择本地解析后端；后面的 `--visual-review auto` 才允许 API 复核可疑页面。这两个同名模式相互独立。

MinerU 模型通过它自己的下载器准备：

```bash
# 显式联网：缓存 pipeline 和 VLM 模型
"$HOME/.local/bin/local-read" models prepare --source huggingface
# 也支持 --source modelscope

# 离线检查本地包与模型文件
"$HOME/.local/bin/local-read" models status

"$HOME/.local/bin/local-read" convert paper.pdf --backend vlm-hybrid
```

统一安装包含 MinerU、PyTorch、Transformers 和 OpenAI SDK。如果已有模型，配置已有路径即可。下载失败会保留缓存供重试。解析阶段不自动下载模型或改用 API；后续 API 图片复核需显式指定模式。

## 文件存放在哪里

| 内容 | 默认位置 | 自定义方式 |
| --- | --- | --- |
| 模型、模型缓存和托管 MinerU 配置 | `~/.cache/local-read/models/` | `LOCAL_READ_MODEL_DIR`，绝对路径 |
| CLI、依赖、包缓存和托管 Python | `~/.local/share/local-read/` | 用户级固定位置 |
| API 配置 | `~/.config/local-read/.env` | `LOCAL_READ_CONFIG_DIR`，绝对路径 |
| 解析结果与工作临时文件 | 当前项目的 `.local_read_mcp/` | 通过调用时的工作目录确定 |

模型与 CLI 在用户范围共享；切换项目、复制 Skill 或修改开发源码不会新建安装环境。只有显式安装和升级会改动程序依赖。模型准备也有独立的进程锁。

每次转换创建独立输出目录，常用文件为：

```text
.local_read_mcp/<文件名>_<时间>_<唯一标识>/
  result.json          本次运行状态与文件路径
  output.md            可读正文
  intermediate.json    内容块、阅读顺序、来源页码与坐标
  index.json           内容索引
  images/              提取或渲染的图片
  visual_review/       请求 PDF 图片提取或复核时生成
    review.json        原始与有效判断、检查状态和修订依据
```

长文档还会产生分块目录和结构目录；MinerU 解析保留原始中间 JSON 与内容列表。具体位置以返回 JSON 中的 `files` 为准。

## 如何判断结果可用

| `status` | 退出码 | 含义 |
| --- | --- | --- |
| `complete` | 0 | 处理完成，内容质量仍需检查 |
| `partial` | 2 | 部分分块或图片处理失败 |
| `failed` | 1 | 处理失败 |

转换返回简洁 JSON，正文保存在磁盘。参数错误和依赖安装失败可能只在 stderr 提供说明，不保证 JSON；不能仅凭退出码 2 推断部分提取成功。

重点检查 `warnings`、`quality_state`、`requires_ocr` 和失败范围。Simple 可能把表格提取为文字，不能据此保证行列关系；图号关联应结合图片复核报告的状态使用，近重复图像分组仍是启发式结果。

命令行物理页索引从 **0** 开始、两端包含。统一中间结果的页码从 **1** 开始，指向原始 PDF；分块结果已经应用偏移。未知页码、坐标为 `null`。MinerU 原始文件则保留上游的分块内编号。引用印刷页码前，需核对它与物理页码的对应关系。

## 图片区域与图号校验

PDF 转换添加 `--extract-images` 后，Local_Read 默认在本地检查区域边界、元素类别和图注关联。图注从页面文字与 MinerU 原始结果取得，关联使用空间位置和栏位信息；正文中提到的图号不直接作为图注。重叠区域、共享图注、类别冲突或无法关联的对象会标记为疑点。

```bash
# 离线规则检查
"$HOME/.local/bin/local-read" convert paper.pdf --extract-images
# 已配置 VISION_*，显式允许向 API 发送有疑点的页面
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review auto
# 所有检测到视觉区域的页面都复核，API 请求上限为 8 页
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review online --review-max-pages 8
```

`--visual-review offline` 等价地启用图片提取和离线检查。所有显式复核模式仅支持 PDF；普通 `convert` 未请求提图时不自动运行复核。`auto` 依据规则筛选疑点，可能漏掉规则未发现的错误；`online` 的覆盖仍受检测结果和页数预算限制。

联网复核发生在离线解析结束之后。发送内容包括整页、编号框图、区域裁图和图注；程序校验 VLM 返回的区域 ID、类别、坐标和图注目标，再应用合法修改。每页一次请求，默认最多 8 页、单次超时 60 秒，不自动重试。API 不可用、超时、返回非法结果或达到预算时保留离线结果并记录未完成状态。

返回值中的 `files.visual_review` 指向 `visual_review/review.json`，保留原始判断、有效判断、各项规则检查和修订依据。复核状态独立于转换的 `complete` / `partial` / `failed`；转换完成也可能仍有 `needs_review`。修改区域边界会另存裁图；拆分/合并建议暂保留为歧义，不自动变更区域拓扑。`rule_passed` 不等于视觉识别正确，`vlm_reviewed` 也不是科学结论验证。复核仅覆盖成功提取页面上检测到的区域，不能证明没有遗漏图片。

## 配置与可选 API

基础离线转换不需要 `.env`。API 配置统一填写到 `~/.config/local-read/.env`，可参考源码中的 [.env.example](.env.example)。同名进程环境变量优先；模型与配置目录等路径覆盖应在启动 CLI 前 export，不依赖 API 配置文件的加载时机。

常用配置为 `VISION_API_KEY`、`VISION_BASE_URL`、`VISION_MODEL` 和 `VISION_MAX_IMAGE_SIZE_MB`。密钥支持 `OPENAI_API_KEY` 后备；模型需按服务商实际能力填写。配置密钥本身不会启用联网复核，详细变量见 [使用参考](references/usage.md)。

`mineru.json` 配置模型路径及 MinerU 选项，选择顺序为：显式 `MINERU_TOOLS_CONFIG_JSON` → 全局模型目录中的托管配置 → cwd 的 `.local_read_mcp/models/mineru.json` → 用户配置目录中的 `mineru.json`。源码中的 [mineru.json.template](mineru.json.template) 仅供复用已有模型，两个目录占位符必须替换为实际路径，不会自动加载。一般使用 `models prepare` 生成托管配置即可。

仅在需要外部图片分析时调用：

```bash
"$HOME/.local/bin/local-read" analyze figure.png --question "解释坐标轴与图例"
```

该命令会发送图片到配置的服务商。默认离线 `convert` 不会调用它；显式 `--visual-review auto|online` 则使用专门的结构化 VLM 图片复核接口。当前离线防护包括模型离线设置与 Python 网络调用限制，不是操作系统级网络隔离。

## 开发与验证

```bash
make test     # 使用项目内开发环境运行测试
make coverage # 按需生成覆盖率报告
make skill    # 构建技能压缩包
```

Makefile 使用 `dev` 依赖组，将源码测试环境固定在 `.local_read_mcp/dev-runtime/`，测试不依赖用户级安装。MinerU、本地推理组件与 OpenAI SDK 均为常规依赖，不需要选择 extras。覆盖率报告保存在 `.local_read_mcp/coverage/`，代码检查配置统一在 `pyproject.toml`。不要为运行测试向各项目安装日常 CLI。

Python 接口的分发名为 `Local_Read`，包名为 `local_read`，CLI 名为 `local-read`。源码开发使用 Makefile 的独立测试环境；日常使用统一安装入口，不将开发入口放进日常 PATH。

测试覆盖生成文档、页码与分块、失败降级、统一入口与配置、重复安装诊断、安装器调用、进程锁、技能打包和模拟 API 复核。安装器 mock、最小包的真实 uv 安装演练、完整依赖安装及真实模型推理是不同验证层级，不能互相替代。`models_ready` 只检查本地包和文件；测试通过不等于真实论文识别质量或目标硬件推理能力已得到验证。

用户安装与配置以本文件为准；智能体调用流程见 [SKILL.md](SKILL.md)，完整选项与产物见 [使用参考](references/usage.md)，代码维护见 [AGENTS.md](AGENTS.md)。项目代码采用 MIT 许可证，依赖和模型遵循各自许可证。
