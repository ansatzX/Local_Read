# Local_Read

Local_Read 是一个以学术 PDF 阅读为重点的本地文档技能包。它把文档转换为 Markdown、索引、图片和带来源信息的结构化文件，供智能体按问题继续阅读。也支持 Word、Excel、PowerPoint、HTML 和 ZIP 的本地转换。

项目通过 **Skill + CLI** 使用。MinerU 提供深度 PDF 解析与模型推理基础设施；Local_Read 负责本地资源准备、后端选择、页码与分段处理、结果保存及智能体使用流程。

## 开始使用

需要 Python 3、`uv`，以及支持技能与命令执行的智能体。将完整项目放入宿主支持的技能目录，目录名为 `local-read`；只安装 Python 包不会安装技能说明。

也可以生成分发包：

```bash
python3 scripts/package_skill.py
```

产物为 `.local_read_mcp/dist/Local_Read.zip`，内含 `local-read/` 目录。解压到宿主的技能目录后即可发现该技能；压缩包不包含个人配置、模型或运行环境。

在需要读取文档的项目目录中执行：

```bash
# 换成实际技能目录
SKILL_DIR="/absolute/path/to/local-read"

# 首次联网安装完整软件依赖（不下载模型权重）
python3 "$SKILL_DIR/scripts/local_read.py" setup

# 之后离线读取
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf

# 读取第 11–20 个物理页面
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --start-page 10 --end-page 19 --strict-page-range

# 同时提取图片，供后续查看
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --extract-images
```

也可以直接让智能体“使用 `$local-read` 阅读这份 PDF 的第 11–20 页”。调用时保持工作目录在自己的项目内，输出位置取决于工作目录。

## PDF 的两条解析路线

| 路线 | 适用场景 | 所需资源 |
| --- | --- | --- |
| `simple` | 有文字层的 PDF、普通文档转换 | 使用统一安装的软件依赖，无需模型权重 |
| `vlm-hybrid` | 扫描件，以及需要布局、OCR、公式、表格等解析能力的 PDF | MinerU 依赖、本地模型及适用硬件 |

默认 `auto` 对 PDF 优先选择本地就绪的 MinerU，否则使用 Simple。请求 MinerU 后发生失败，也可能降级为 Simple；实际结果和警告会随返回值提供。其他格式走本地转换器。

MinerU 模型通过它自己的下载器准备：

```bash
# 显式联网：安装推理依赖，缓存 pipeline 和 VLM 模型
python3 "$SKILL_DIR/scripts/local_read.py" models prepare --source huggingface
# 也支持 --source modelscope

# 离线检查本地包与模型文件
python3 "$SKILL_DIR/scripts/local_read.py" models status

python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --backend vlm-hybrid
```

`setup` 默认安装 MinerU、PyTorch、Transformers 和 OpenAI SDK。如果已有模型，执行 `setup` 后配置已有模型路径即可。下载失败会保留缓存供重试。转换过程不自动下载模型，也不自动改用 API。

## 文件存放在哪里

| 内容 | 默认位置 | 自定义方式 |
| --- | --- | --- |
| 模型、模型缓存和托管 MinerU 配置 | `~/.cache/local-read/models/` | `LOCAL_READ_MODEL_DIR`，绝对路径 |
| 运行环境、包缓存和托管 Python | `~/.cache/local-read/runtime/` | `LOCAL_READ_RUNTIME_DIR`，绝对路径 |
| 解析结果与工作临时文件 | 当前项目的 `.local_read_mcp/` | 通过调用时的工作目录确定 |

模型与运行环境在用户范围共享。同一技能版本换项目或移动安装目录，无需重复准备；代码或依赖锁内容改变会选择新的运行环境。运行环境的使用与安装受进程锁保护，同一环境的调用会串行执行。模型准备也有独立的进程锁。

每次转换创建独立输出目录，常用文件为：

```text
.local_read_mcp/<文件名>_<时间>_<唯一标识>/
  result.json          本次运行状态与文件路径
  output.md            可读正文
  intermediate.json    内容块、阅读顺序、来源页码与坐标
  index.json           内容索引
  images/              提取或渲染的图片
```

长文档还会产生分块目录和结构目录；MinerU 解析保留原始中间 JSON 与内容列表。具体位置以返回 JSON 中的 `files` 为准。

## 如何判断结果可用

| `status` | 退出码 | 含义 |
| --- | --- | --- |
| `complete` | 0 | 处理完成，内容质量仍需检查 |
| `partial` | 2 | 部分分块或图片处理失败 |
| `failed` | 1 | 处理失败 |

转换返回简洁 JSON，正文保存在磁盘。参数错误和依赖安装失败可能只在 stderr 提供说明，不保证 JSON；不能仅凭退出码 2 推断部分提取成功。

重点检查 `warnings`、`quality_state`、`requires_ocr` 和失败范围。Simple 可能把表格提取为文字，不能据此保证行列关系；图号关联和近重复图像分组也需要核对。

命令行物理页索引从 **0** 开始、两端包含。统一中间结果的页码从 **1** 开始，指向原始 PDF；分块结果已经应用偏移。未知页码、坐标为 `null`。MinerU 原始文件则保留上游的分块内编号。引用印刷页码前，需核对它与物理页码的对应关系。

## 配置与可选 API

基础离线转换不需要 `.env`。它只用于可选配置，例如视觉 API 的 `VISION_API_KEY`、`VISION_BASE_URL` 和 `VISION_MODEL`；`.env.example` 是填写示例。

`mineru.json` 配置模型路径及 MinerU 选项，选择顺序为：显式 `MINERU_TOOLS_CONFIG_JSON` → 用户全局托管配置 → 旧项目内配置 → 技能根目录配置。`mineru.json.template` 是手动配置模板，不会自动加载。

仅在需要外部图片分析时调用：

```bash
python3 "$SKILL_DIR/scripts/local_read.py" analyze figure.png --question "解释坐标轴与图例"
```

该命令会发送图片到配置的服务商。离线 `convert` 不会调用它。当前离线防护包括模型离线设置与 Python 网络调用限制，不是操作系统级网络隔离。

## 开发与验证

```bash
make test     # 使用项目内开发环境运行测试
make coverage # 按需生成覆盖率报告
make skill    # 构建技能压缩包
```

开发工具使用 `dev` 依赖组（`uv sync --group dev`），MinerU、本地推理组件与 OpenAI SDK 均为常规依赖，不需要选择 extras。覆盖率报告保存在 `.local_read_mcp/coverage/`。代码检查配置统一在 `pyproject.toml`。

Python 接口的分发名为 `Local_Read`，包名为 `local_read`，CLI 名为 `local-read`。已有 Python 环境可用 `uv pip install -e /absolute/path/to/local-read` 安装，再运行 `local-read convert paper.pdf`。

测试覆盖生成文档、页码与分块处理、错误与降级、共享环境、进程锁和技能打包使用。`models_ready` 只检查本地包和文件；测试通过不等于真实论文识别质量或目标硬件推理能力已得到验证。

详细用法见 [使用参考](references/usage.md)。源码仓库中的 `AGENTS.md` 说明代码维护约定。项目代码采用 MIT 许可证，依赖和模型遵循各自许可证。
