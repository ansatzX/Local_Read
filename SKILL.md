---
name: local-read
description: 离线读取本地 PDF、Word、Excel、PowerPoint、HTML 和 ZIP，将文档转换为 Markdown、索引、图片和可追溯的结构化文件。当任务需要提取论文正文、指定页、公式、表格或图像，而普通文本读取不足以完成时使用。
---

# Local_Read

围绕用户的问题提取和阅读文档。优先使用已准备的本地资源；普通文本和已有图片可直接用宿主的原生读取能力。

## 调用入口

将 `SKILL_DIR` 设为本文件所在目录的绝对路径。保持工作目录为用户的项目目录，解析结果会写入该目录下的 `.local_read_mcp/`。

```bash
python3 "$SKILL_DIR/scripts/local_read.py" convert "/absolute/path/paper.pdf"
```

启动器需要 Python 3 和 `uv`；运行环境支持 Python 3.10–3.13。`setup` 统一安装 MinerU、PyTorch、Transformers 和 OpenAI SDK。默认 `auto` 对 PDF 优先选择本地可用的 MinerU，否则使用无模型的 Simple；其他文档使用本地转换器。解析阶段不会自动安装依赖、下载模型或调用远程视觉 API；只有显式选择 `--visual-review auto|online` 才允许后续图片复核使用已配置的 API。

## 按问题读取

1. 用户指定范围时只提取所需页。以下命令读取 PDF 的第 11–20 个物理页面；`--strict-page-range` 防止章节规划扩大范围。

   ```bash
   python3 "$SKILL_DIR/scripts/local_read.py" convert book.pdf --start-page 10 --end-page 19 --strict-page-range
   ```

2. 检查返回 JSON 的 `status`、`warnings`、`quality_state`、`requires_ocr` 和失败信息。`complete` 只表示处理完成，不能据此认定内容可读或准确；后端降级必须体现在回答中。
3. 根据 `files.index_json` 定位材料，再读取 `files.markdown` 的相关部分。用 `files.intermediate_json` 核对页码与位置；`files.result_json` 保存本次摘要。索引没有表格条目，不代表原文没有表格。
4. 需要图像元素时加 `--extract-images`，Local_Read 自动执行离线区域、类别与图注关联检查。读取 `files.visual_review`，使用每个区域的 `effective` 和校验状态；原始图片清单的首选匹配仍只是候选。规则未解决的问题由 Local_Read 标记，不要求宿主代替它确认标签。
5. 回答时保留原文页码及材料来源。部分失败只支持对成功提取部分的回答；通过 `files.chunks` 定位缺失范围后可单独重试。

**页码约定：**命令的物理页范围从 **0** 开始，两端包含；统一 `intermediate.json` 中的块页码从 **1** 开始，指向原始 PDF，分块结果也无需再次加偏移。`page` 或 `bbox` 为 `null` 表示未知。MinerU 原始 JSON 保留上游的块内页码。印刷页码与物理页码可能不同；逻辑页映射的用法见参考文档。

## 图片校验模式

```bash
# 默认离线：提取图片并执行几何、类别与图注一致性检查
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --extract-images
# 用户明确启用 API：只复核有疑点的页面
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --visual-review auto
# 用户明确启用 API：复核所有检测到视觉区域的页面，最多 8 次请求
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --visual-review online --review-max-pages 8
```

`--visual-review offline` 也会启用图片提取，无需另加 `--extract-images`；这三个模式仅支持 PDF。未请求图片提取或复核时，不保证存在 `files.visual_review`。

`auto` / `online` 会发送页面原图、编号框预览、裁图和图注到配置的 VLM。复核状态与转换状态独立：`rule_passed` 仅代表规则未发现冲突，`vlm_reviewed` 代表模型已复核，`needs_review` 代表仍有疑点、API 不可用或预算不足。`no_regions_detected` 不证明页面没有图片。API 出错保留离线结果，不把失败当作确认。

有效的类别、图注关联和边界修订会记录依据；改动边界后另存裁图。拆分与合并建议保留为歧义项，不自动删除或替换原区域。更多状态和文件约定见使用参考。

## 本地资源不足时

安装与模型下载是显式准备操作；文档解析保持离线，API 图片复核另由显式模式控制。仅在任务包含安装或模型准备时执行准备命令；否则报告缺失资源。

```bash
# 安装完整软件依赖，不下载模型权重
python3 "$SKILL_DIR/scripts/local_read.py" setup

# 扫描件或复杂版面：准备运行环境并缓存模型
python3 "$SKILL_DIR/scripts/local_read.py" models prepare --source huggingface

# 检查包版本和模型文件；不加载模型
python3 "$SKILL_DIR/scripts/local_read.py" models status

# 使用本地 MinerU；仍须检查返回结果中的降级提示
python3 "$SKILL_DIR/scripts/local_read.py" convert paper.pdf --backend vlm-hybrid
```

同一技能代码与依赖版本的运行环境在 `~/.cache/local-read/runtime/` 共享；模型在 `~/.cache/local-read/models/` 共享。切换项目不需重新准备；代码或锁文件变化后需为新版本执行一次 setup。其他磁盘可通过绝对路径 `LOCAL_READ_RUNTIME_DIR`、`LOCAL_READ_MODEL_DIR` 指定。

`requires_ocr=true` 时，不能把空白提取结果当成原文没有内容。检查本地 MinerU 是否可用；`models_ready=true` 仅表示包与文件检查通过，不证明推理成功或识别准确。

## 状态与进一步操作

转换的 `complete` / `partial` / `failed` 分别对应退出码 **0 / 2 / 1**。参数错误也可能返回 2；若没有 JSON，应读取 stderr，而不是按“部分成功”解释。依赖安装失败也不保证返回 JSON。

`analyze` 会把图片发送到配置的外部 API，仅在用户任务包含该外部分析时使用，不能作为离线转换失败后的自动后备。

需要章节控制、逻辑页范围、完整产物说明、已有模型配置或视觉 API 用法时，读取 [references/usage.md](references/usage.md)。
