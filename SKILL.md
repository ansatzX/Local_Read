---
name: local-read
description: 离线读取本地 PDF、Word、Excel、PowerPoint、HTML 和 ZIP，将文档转换为 Markdown、索引、图片和可追溯的结构化文件。当任务需要提取论文正文、指定页、公式、表格或图像，而普通文本读取不足以完成时使用。
---

# Local_Read

围绕用户的问题调用已安装的 Local_Read CLI 提取文档。此 Skill 只负责使用流程；普通文本和已有图片可直接用宿主的原生读取能力。

## 调用入口

使用固定用户级入口，保持工作目录为用户项目。解析结果写入该目录下的 `.local_read_mcp/`。

```bash
"$HOME/.local/bin/local-read" doctor
"$HOME/.local/bin/local-read" convert "/absolute/path/paper.pdf"
```

首次调用或出现安装异常时使用 `doctor`，无需每个文件都重复诊断。本技能不携带程序或安装器。入口缺失时报告需要安装用户级 Local_Read CLI，不用 uvx、uv run、pip 或复制源码临时补装。`doctor` 显示实际版本、路径、来源及重复安装警告；`success=true` 不代表没有警告，`managed=true` 不证明文件未被修改。

默认 `auto` 对 PDF 优先选择本地可用的 MinerU，否则使用无模型的 Simple；其他文档使用本地转换器。解析阶段不会安装依赖、下载模型或调用远程视觉 API；只有显式选择 `--visual-review auto|online` 才允许后续图片复核使用已配置的 API。

`--backend auto` 与 `--visual-review auto` 相互独立，自动选择本地后端不会启用联网复核。

## 按问题读取

1. 用户指定范围时只提取所需页。以下命令读取 PDF 的第 11–20 个物理页面；`--strict-page-range` 防止章节规划扩大范围。

   ```bash
   "$HOME/.local/bin/local-read" convert book.pdf --start-page 10 --end-page 19 --strict-page-range
   ```

2. 检查返回 JSON 的 `status`、`warnings`、`quality_state`、`requires_ocr` 和失败信息。`complete` 只表示处理完成，不能据此认定内容可读或准确；后端降级必须体现在回答中。
3. 根据 `files.index_json` 定位材料，再读取 `files.markdown` 的相关部分。用 `files.intermediate_json` 核对页码与位置；`files.result_json` 保存本次摘要。索引没有表格条目，不代表原文没有表格。
4. 需要图像元素时加 `--extract-images`；PDF 成功解析部分会执行离线区域、类别与图注关联检查。若有 `files.visual_review`，读取各区域的 `effective` 和校验状态；若复核失败或报告缺失，说明标签尚未验证。原始图片清单的首选匹配仍只是候选，不要求宿主代替程序确认标签。
5. 回答时保留原文页码及材料来源。部分失败只支持对成功提取部分的回答；通过 `files.chunks` 定位缺失范围后可单独重试。

**页码约定：**命令的物理页范围从 **0** 开始，两端包含；统一 `intermediate.json` 中的块页码从 **1** 开始，指向原始 PDF，分块结果也无需再次加偏移。`page` 或 `bbox` 为 `null` 表示未知。MinerU 原始 JSON 保留上游的块内页码。印刷页码与物理页码可能不同；逻辑页映射的用法见参考文档。

## 图片校验模式

```bash
# 默认离线：提取图片并执行几何、类别与图注一致性检查
"$HOME/.local/bin/local-read" convert paper.pdf --extract-images
# 用户明确启用 API：只复核有疑点的页面
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review auto
# 用户明确启用 API：复核所有检测到视觉区域的页面，最多 8 次请求
"$HOME/.local/bin/local-read" convert paper.pdf --visual-review online --review-max-pages 8
```

`--visual-review offline` 也会启用图片提取，无需另加 `--extract-images`；这三个模式仅支持 PDF。未请求图片提取或复核时，不保证存在 `files.visual_review`。

`auto` / `online` 会发送页面原图、编号框预览、裁图和图注到配置的 VLM。复核状态与转换状态独立：`rule_passed` 仅代表规则未发现冲突，`vlm_reviewed` 代表模型已复核，`needs_review` 代表仍有疑点、API 不可用或预算不足。`no_regions_detected` 不证明页面没有图片。API 出错保留离线结果，不把失败当作确认。

有效的类别、图注关联和边界修订会记录依据；改动边界后另存裁图。拆分与合并建议保留为歧义项，不自动删除或替换原区域。更多状态和文件约定见使用参考。

## 本地资源不足时

模型缓存跨项目共享。仅在用户任务包含模型下载时执行 `models prepare`；它不安装或升级 CLI。

```bash
# 扫描件或复杂版面：显式联网缓存模型
"$HOME/.local/bin/local-read" models prepare --source huggingface

# 检查包版本和模型文件；不加载模型
"$HOME/.local/bin/local-read" models status

# 使用本地 MinerU；仍须检查返回结果中的降级提示
"$HOME/.local/bin/local-read" convert paper.pdf --backend vlm-hybrid
```

程序与依赖统一安装在 `~/.local/share/local-read/`，模型默认在 `~/.cache/local-read/models/`，可用绝对路径 `LOCAL_READ_MODEL_DIR` 指定另一磁盘。技能副本或源码变化不会改变已安装 CLI；升级由用户集中执行。

API 配置默认来自 `~/.config/local-read/.env` 或进程环境；项目和技能目录的 `.env` 不会自动加载。已有配置的诊断与路径覆盖见使用参考，不读取或输出用户密钥。

`requires_ocr=true` 时，不能把空白提取结果当成原文没有内容。检查本地 MinerU 是否可用；`models_ready=true` 仅表示包与文件检查通过，不证明推理成功或识别准确。

## 状态与进一步操作

转换的 `complete` / `partial` / `failed` 分别对应退出码 **0 / 2 / 1**。参数错误也可能返回 2；若没有 JSON，应读取 stderr，而不是按“部分成功”解释。依赖安装失败也不保证返回 JSON。

`analyze` 会把图片发送到配置的外部 API，仅在用户任务包含该外部分析时使用，不能作为离线转换失败后的自动后备。

需要章节控制、逻辑页范围、完整产物说明、已有模型配置或视觉 API 用法时，读取 [references/usage.md](references/usage.md)。
