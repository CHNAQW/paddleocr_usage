# 文献处理软件

**版本：26.10.17.1** · Python / Tkinter 桌面程序 · 推荐 Windows 10/11

把扫描版 PDF 转成 Markdown，再按需翻译、核对与校对，最后将核验通过的文献上传到指定 GitHub 仓库。

Literature Processing Software provides PDF-to-Markdown OCR, translation through OpenAI-compatible models, optional quality checks, and publishing of reviewed Markdown to GitHub. Windows is the primary desktop platform; the Python source also runs on Linux/macOS with Tkinter and a graphical display.

## 功能与入口

| 入口 | 主要用途 | 可选后续处理 |
| --- | --- | --- |
| PDF OCR 转 MD功能 | 调用 PaddleOCR 在线异步 API，批量转换扫描 PDF | LLM 核验、外文检测与翻译、核验后上传 GitHub |
| 外文文献翻译功能 | 扫描已有 `.md`，检测语言并翻译为目标语言 | 二次翻译核对、人工或模型裁决、文本校对、核验后上传 GitHub |

- 可递归处理子文件夹，保留目录层级。
- OCR 支持页级进度、jobId 恢复、队列满重试，以及超过 50MB 的 PDF 自动拆分与合并。
- 翻译支持 Kimi/Moonshot、Doubao/火山方舟、DeepSeek 和其他兼容 OpenAI Chat Completions 的服务。
- 翻译、二次核对、文本校对、争议裁决可分别指定模型，支持拉取模型列表及手工输入模型 ID。
- 上方设置可滚动，底部日志独立显示，可拖动分隔条调节高度；最小窗口为 540×420。
- 保留原文件；译文可选择输出位置和文件名前缀/后缀；GitHub 远端同名文件不会被自动覆盖。

## 快速开始

### Windows：从源码启动

完整下载或解压源码，保留同目录下的 Python 模块、依赖清单和图标文件，双击：

```text
start_paddleocr_pdf_to_md_SAFE.bat
```

启动器查找 Python 3.9 或更新版本，创建本地 `.venv`，检查并安装 `requests`、`pypdf`，然后打开程序。首次安装依赖需要联网。仅使用翻译入口时不需要 PaddleOCR Token；程序启动时不会强制要求填写它。

也可以在源码目录手动运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe paddleocr_pdf_to_md_gui.py
```

### Linux / macOS：从源码启动

需要 Python 3.9+、Tkinter 和可用的图形显示环境。在源码目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python paddleocr_pdf_to_md_gui.py
```

若无法导入 `tkinter`，请安装与当前 Python 匹配的 Tk 支持。例如 Debian/Ubuntu 的系统 Python 通常使用 `python3-tk`；macOS 可使用带 Tk 的 Python.org 发行版。可用 `python3 -m tkinter` 检查是否能打开测试窗口。

无显示服务的云端终端可以运行非 GUI 测试，但不能直接显示桌面窗口。Windows 的 `.bat` 与 `.exe` 不适用于 Linux/macOS。

### 使用 Windows EXE

使用实际构建的 `PaddleOCR_PDF_to_MD_26.10.17.1.exe` 时，直接双击即可，无需安装 Python。源码中的版本更新不等于已经提供该版本的 EXE；构建方法见下文。

## 入口1：PDF OCR 转 MD

1. 选择 PDF 输入文件夹与 Markdown 输出文件夹。
2. 按需勾选递归扫描、保留子文件夹结构、覆盖已有 `.md`。
3. 输入 PaddleOCR 官方 API Access Token/API Key；可点击检测按钮检查鉴权。
4. 选择 OCR 模型。默认 `PaddleOCR-VL-1.6`；界面还提供 `PaddleOCR-VL-1.5`、`PaddleOCR-VL`、`PP-StructureV3`，实际可用性由服务端决定。
5. 如需 OCR 质量核验，配置 OpenAI compatible Base URL、API Key 与模型并启用 LLM 核验。
6. 如需接着翻译，勾选“是否自动检测外文文献并提供翻译”，先在入口2配置目标语言、翻译及可选检查模型和输出设置。
7. 点击“开始批量转换”，确认后查看文件、页数、分段进度与日志。

**自动翻译开关**：不勾选时只进行 OCR；勾选后，每份新完成的 OCR Markdown 会进入翻译流程。OCR 跳过的已有输出不会自动重译，处理这些文件请使用入口2。

### OCR 质量检查与恢复

- 每次 OCR 后按页检查 Markdown，默认要求平均每页至少 150 个词/汉字。中文按汉字计数，拉丁文本按单词计数；该阈值是质量提示，不是准确性证明。
- 可选 LLM 核验逐段覆盖全文，每段最多 50,000 字符。确认缺页、少页或破坏原意的严重逻辑错误时会触发重提；普通 OCR 错字、排版、表格、公式、顺序或局部重复不触发重提。
- 字数或 LLM 核验未通过时，会删除本次输出、检查结果与 jobId 缓存后重提，最多共三次。重试耗尽仍有问题时保留结果并给出质量警告。
- LLM 请求失败会记录警告，保留已经成功生成的 OCR 结果；该文件不能被视为通过 LLM 核验。
- 中断后的 jobId 可供下次继续查询；“手动查询当前结果”可以提前触发当前任务查询。
- “停止转换”会停止后续提交和轮询；已经提交到 PaddleOCR 服务端的任务不能从本程序撤销。

### 大 PDF 与 JSON 修复

超过 50MB 的 PDF 会按页拆成约 45MB 的分段，逐段 OCR 后合并为同名 Markdown 与 JSON。需要 `pypdf`；异常巨大的单页、加密或损坏的 PDF 仍可能无法处理。

如果已下载 `.json`、`.jsonl` 或 `.raw.json` 而 Markdown 缺失，可使用“修复JSON为MD”重新提取文本。修复不是重新 OCR，也不等于质量核验。

“手动字数检验”和“手动LLM检验”可检查已有 Markdown，并展示结果或生成报告。

## 入口2：外文文献翻译

### 扫描、语言识别与输出

1. 选择包含已有 `.md` 的文件夹，按需递归扫描。
2. 设置目标语言，默认简体中文。来源语言可选“自动检测”，也可从常用 PaddleOCR 语言代码列表选择，或手填语言名称。列表不是远程大模型能力保证，实际翻译能力取决于所选模型。
3. 配置翻译/语言识别模型。
4. 选择“输出到原文所在文件夹”，或取消该选项并指定独立输出目录；独立目录保留输入中的相对目录层级。
5. 选择译文文件名标记：`TRANSLATED_原文件名.md` 或 `原文件名_TRANSLATED.md`。
6. 按需启用二次翻译核对和文本校对，点击开始翻译。

每份文件先使用**前 300 字符**调用模型识别主要语言，并判断是否属于目标语言。已经是目标语言时跳过；手工来源语言用于后续翻译提示，不取消目标语言判断。若开头只有代码、链接或元数据而不能可靠识别，会报错并继续其他文件。

扫描会排除 `TRANSLATED_*.md`、`*_TRANSLATED.md` 及位于输入内的独立输出子目录。已有同名译文不会覆盖，也不会沿用旧报告把它视为本次核验通过。输入 Markdown 应为 UTF-8，可带 BOM。

### 模型服务配置

每个步骤都可在自己的模型标签页选择服务商预设、填写 Base URL 与 API Key，并拉取或手填模型。

| 服务商 | Base URL 预设 | 模型设置 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | 拉取或手填服务端提供的模型 ID |
| Kimi / Moonshot | `https://api.moonshot.cn/v1` | 拉取或手填账户可用模型 |
| Doubao / 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | 按服务要求填写模型或推理接入点 ID，如 `ep-…` |
| 其他 OpenAI compatible 服务 | 自行填写 | 需支持 `/chat/completions` 文本输入与输出 |

- Base URL 应包含服务要求的版本前缀，程序会追加 `/models` 或 `/chat/completions`。
- 服务不支持 `/models` 时，可以手填模型或接入点 ID；支持拉取列表不代表每个模型都支持文本翻译。
- “测试接口”发送一个最小文本请求；成功只能说明本次请求可用，不能保证后续长文请求的额度与上下文容量。
- 切换服务商预设会清空该模型配置的旧 Key，避免误用。
- 长文默认按最多 4000 字符分段，优先在换行处分段。提示模型保留引用、数字、公式、代码、图片与链接；跨段上下文和 Markdown 完整性仍需复核。
- 空响应、截断响应、无效核验 JSON 均不会作为成功结果。

### 二次翻译核对与争议裁决

启用后，核对模型先独立翻译同一段原文，再结合原文比较首次和二次译文，检查漏译、误译、数字与引文等问题。

发现问题时可选择：

- **用户自行裁决**：窗口分别展示原文、首次译文、二次译文及核对报告。可接受首次译文、接受二次译文，或保留首次译文并标记待处理。
- **大模型裁决**：使用另行指定的裁决模型对照原文选择可接受的译文。两份都有问题或未明确批准时，保持待处理状态。

二次翻译核对与首次翻译可以使用不同服务商和模型。

### 文本校对

可单独启用，也可接在二次核对/裁决之后。指定模型结合原文检查最终选定译文的语句不通、缺字少字、漏译等问题，不自动润色或改写。

发现问题时仍保存译文及报告，但标记待处理并禁止自动上传。

### 译文报告与状态

每份译文旁保存 `*.translation.json`，记录识别语言、目标语言、输入/输出 SHA-256、所用模型、各段检查与裁决；有争议时保留两份候选译文。报告不含 API Key。

| 状态 | 含义 | 自动上传 |
| --- | --- | --- |
| `verified` | 至少启用一项质量检查，所有启用检查均通过 | 可以；仍须满足 GitHub 配置与上游 OCR 条件 |
| `needs_review` | 存在未解决的核对或校对问题 | 禁止 |
| `unverified` | 未启用质量检查 | 禁止 |
| `target_language` | 已属于目标语言，跳过翻译 | 不上传 |
| `existing` | 已有同名译文，跳过 | 不上传 |

状态代表本次模型检查或人工裁决结果，不保证译文完全正确。再次处理待处理文献前，请先另存并移走已有译文和报告，以免被覆盖保护跳过。

停止翻译会在当前网络请求返回后退出；此前完成的文件会保留，未完成文件不会被当作核验通过。

## 核验后自动上传 GitHub

在翻译入口的 GitHub 区域勾选自动上传，填写：

- 仓库：`owner/repository`。
- 已有目标分支，例如 `main`；程序不自动创建分支。
- 可选仓库内目录，使用相对路径。
- 对目标仓库有 **Contents 读写权限**的 Token。Token 只在本次运行内存中保留，也可使用进程已有的 `GITHUB_TOKEN` / `GH_TOKEN`。

上传开关由两个入口共用，适用于本次 OCR / 翻译流程完成的输出：

- OCR 原文必须有通过的 LLM 核验结果，并且没有字数检查失败或质量警告；大 PDF 的全部分段都需通过。
- 译文至少启用一项质量检查，且所有启用检查通过；有上游 OCR 质量警告时，即使译文检查通过也不会自动上传。
- 上传前会比对已核验文件内容，文件发生变化时拒绝沿用核验结果。
- 仅上传 Markdown，保留相对目录；不会上传 PDF、配置、Token、报告或图片附件。
- 使用 GitHub Contents API 创建提交；每文件限制 20MB，远端同名文件不覆盖。上传失败会保留本地文件并记录日志。

该功能会向所选分支创建提交，**不会创建 PR**。需要审阅时，可自行选择已有的专用分支，再在 GitHub 上创建 PR。仓库权限、分支保护和 API 限额均可能阻止上传。

## 文件与配置

```text
paddleocr_pdf_to_md_gui.py          主入口与原有 OCR 流程
literature_processing.py           翻译、核验与 GitHub 上传逻辑
literature_ui.py                   翻译界面与任务协调
start_paddleocr_pdf_to_md_SAFE.bat  Windows 源码启动器
build_paddleocr_pdf_to_md_EXE.bat   Windows EXE 构建脚本
version_info_26.10.17.1.txt         Windows 版本信息参考文件
requirements.txt                  运行依赖
app_icon.ico / app_icon.png        应用图标
tests/                            测试
License                           许可证原文
使用说明.txt                      简明使用说明
```

源码运行需要同目录下的三个 Python 模块，不能只复制主入口。Nuitka 构建会跟随入口导入其余模块；当前 BAT 直接传入版本参数，版本信息参考文件不作为独立构建输入。

本机配置继续保存在旧路径，便于沿用已有设置：

- Windows：`%APPDATA%\PaddleOCRBatchGUI\config.json`。
- Linux/macOS：默认 `~/PaddleOCRBatchGUI/config.json`。

PaddleOCR Token、模型 API Key 随设置以**明文**保存。不要将配置文件提交到仓库或放入共享诊断包。GitHub Token 不写入该配置。

常见输出包括 `.md`、`.raw.json` / `.json`、`.llm-review.json`、`.translation.json` 与 OCR 批处理日志。jobId 缓存用于中断恢复；手动删除后可能需要重新提交付费任务。

## Windows EXE 构建

在 Windows 完整源码目录双击：

```text
build_paddleocr_pdf_to_md_EXE.bat
```

构建脚本使用独立 `.venv-nuitka-2.7.12`，固定 Nuitka 2.7.12，并选择已安装的 Python 3.9–3.13。运行启动器可以使用更新的 Python，但当前固定编译器不应使用 Python 3.14。

首次构建会下载依赖及 Nuitka 管理的 MinGW64，需要联网；不要求安装 Visual Studio Build Tools。采用无压缩 one-file 模式与 LTO，不使用 UPX。构建速度与结果取决于本机工具链和资源。

输出为：

```text
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD_26.10.17.1.exe
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD_26.10.17.1.exe.sha256.txt
```

可通过 PowerShell 对比 SHA-256：

```powershell
Get-FileHash -Algorithm SHA256 .\PaddleOCR_PDF_to_MD_26.10.17.1.exe
Get-Content .\PaddleOCR_PDF_to_MD_26.10.17.1.exe.sha256.txt
```

编译版本元数据统一为 `26.10.17.1`。单文件运行组件缓存于 `%LOCALAPPDATA%\PaddleOCR\PDFToMarkdown\26.10.17.1`。首次释放被中断时，关闭程序后清理对应版本缓存，再次启动。

这些构建选项不保证不会被安全软件误报。发布前应正常检查最终产物；出现误报时向供应商提交复核，不要关闭防护或添加排除项。源码 PR 与版本号更新不表示 Windows EXE 已编译或发布。

## 开发与测试

安装运行依赖及测试工具：

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -v tests
```

标准库也可运行 unittest 测试：

```bash
python -m unittest discover -s tests -v
```

后一个命令不收集 `test_build_script.py` 中的 pytest 测试函数。GUI 测试需要图形显示，无显示时会明确跳过对应测试类；其余测试继续执行。

测试覆盖语言识别、原文保护、译文路径、独立重译、争议裁决、文本校对、停止与重启、OCR 自动翻译衔接、GitHub 上传条件和小窗口日志布局。API 测试使用模拟响应，不消耗线上模型额度，也不向真实仓库写入文献。真实 API 兼容性和 Windows EXE 构建仍需相应运行环境验证。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 小窗口看不到部分设置 | 滚动上方设置区，或拖动分隔条；日志区保持独立可见 |
| 无法导入 `literature_ui` / `literature_processing` | 完整解压源码，保证三个 Python 模块同目录 |
| `No module named tkinter` | 安装与当前 Python 匹配的 Tk 支持 |
| `no display name` / 无法连接 display | 使用有图形显示的桌面会话；云端纯终端不能直接显示 GUI |
| 401、403 或模型不可用 | 检查对应服务商 Key、账户模型权限与接口地址；不要混用服务商 Key |
| 无法拉取模型列表 | 确认 `/models` 是否可用；服务未提供时手填模型或接入点 ID |
| 前 300 字符无法识别语言 | 检查文献开头是否只有标记、链接或代码；该文件会明确失败，不会猜测成功 |
| 输出被截断或核验不是有效 JSON | 更换支持所需文本输出的模型，检查上下文/输出限制和接口兼容性 |
| 文件被跳过 | 检查是否已是目标语言、已有同名译文，或属于自动排除的译文/输出目录 |
| GitHub 上传被跳过 | 查看核验状态、上游 OCR 警告及远端同名文件；未核验输出不会上传 |
| GitHub 上传失败 | 检查联网、目标分支、Contents 写入权限、分支保护与单文件大小 |
| PDF 拆分失败 | 检查 `pypdf`、文件损坏/加密、单页大小 |

## 26.10.17.1 更新记录

- 软件入口改为“文献处理软件”，提供 OCR 与翻译双入口。
- 设置区与日志区分离，小窗口可滚动设置、拖动调整日志高度。
- OCR 完成后可选择自动识别外文并翻译。
- 新增已有 Markdown 文献的语言检测与翻译、分角色模型配置、二次核对和争议裁决、文本校对。
- 新增译文输出目录与文件名前后缀选择，以及核验通过后上传指定 GitHub 仓库的选项。
- 更新程序版本、启动器、EXE 文件名、编译元数据、缓存路径和使用说明。

## 数据、费用与已知限制

OCR 会向 PaddleOCR 上传 PDF；翻译、核对与校对会向选定模型服务发送相应文本；启用 GitHub 上传会把核验通过的 Markdown 提交到所选仓库。检查报告也可能包含文献片段或候选译文。请按材料权限与服务条款选择可处理的文献和输出仓库。

云端 OCR、独立重译、校对与裁决可能各自产生费用。语言检测基于开头样本，可能不能代表全文；模型可能漏检或误判，重要文献应人工复核。分段翻译可能影响跨段上下文、表格、代码、链接与图片引用。当前不会复制或上传图片附件，也不提供自动修订后重新核验或覆盖已有译文的流程。

## License   许可证

[![Creative Commons License](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)
[![知识共享许可协议](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)

Unless otherwise stated in a specific file, the original software, source code, Python scripts, batch scripts, build scripts, compiled executable files, documentation, and other original materials in this repository are licensed under the [Creative Commons Attribution–NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/) (**CC BY-NC 4.0**).
除特定文件另有说明外，本仓库中的原创软件、源代码、Python 脚本、批处理脚本、构建脚本、编译后的可执行文件、说明文档及其他原创材料，均采用[知识共享署名—非商业性使用 4.0 国际许可协议](https://creativecommons.org/licenses/by-nc/4.0/)（**CC BY-NC 4.0**）授权使用。

Under CC BY-NC 4.0, users may copy, redistribute, modify, and build upon the licensed materials for noncommercial purposes, provided that appropriate attribution is retained and any modifications are clearly indicated.
根据 CC BY-NC 4.0，使用者可以出于非商业目的复制、传播、修改和演绎上述许可材料，但须保留适当署名，并明确说明是否进行了修改。

### Additional Academic Permissions   学术用途附加许可

In addition to the permissions granted under CC BY-NC 4.0, the Licensor grants permission for the following uses, even where such uses might otherwise be regarded as commercial:
除 CC BY-NC 4.0 已经授予的权限外，即使下列使用可能被视为具有商业性质，许可人仍特别允许：

1. Use, modification, demonstration, and presentation of the software and other licensed materials by graduate students in academic conferences, forums, workshops, seminars, thesis defenses, and similar academic activities.
   研究生可以在学术会议、学术论坛、工作坊、研讨会、学位论文答辩及其他类似学术活动中使用、修改、演示和展示本软件及其他许可材料。

2. Use of the software and other licensed materials in academic research or academic publications for which an author receives royalties, honoraria, publication remuneration, or other comparable compensation.
   使用者可以在学术研究或学术出版成果中使用本软件及其他许可材料，即使成果作者因此获得版税、稿酬、出版报酬或其他类似报酬。

These additional permissions include the reasonable reproduction of source-code excerpts, interface screenshots, workflow descriptions, and results generated with the software where necessary for the permitted academic activity.
在上述获准的学术活动确有合理需要时，附加许可还包括引用适量源代码、展示程序界面截图、说明程序工作流程，以及展示使用本软件生成结果的权利。

The above additional permissions do **not** authorize the sale, rental, paid licensing, commercial hosting, provision of the software as a paid service, incorporation of the software into a commercial product or service, or use of the software on behalf of a for-profit entity.
上述附加许可**不包括**出售、出租、有偿授权、商业托管、将本软件作为收费服务提供、将本软件整合进商业产品或商业服务，或者代表营利性主体使用本软件。

Such uses require prior written permission from the Licensor.
实施上述行为，应事先取得许可人的书面许可。

### Attribution and Modification Notices  署名与修改声明

The attribution requirement under CC BY-NC 4.0 remains applicable to all permitted uses.
CC BY-NC 4.0 规定的署名义务仍适用于所有获准使用情形。

Users who copy, modify, redistribute, demonstrate, present, or describe the licensed materials must retain the copyright, license, and attribution notices contained in this repository.
复制、修改、再分发、演示、展示或介绍许可材料时，使用者应保留本仓库中已有的著作权、许可证和署名声明。

Users must clearly indicate whether modifications have been made.
使用者还应明确说明是否对许可材料进行了修改。

### Software Distribution Notice  软件分发说明

This project is **source-available software** and is not distributed under an open-source license approved by the Open Source Initiative (**OSI**).
本项目属于**代码公开软件**，并非依据开放源代码促进会（**OSI**）认可的开源许可证进行分发。

Distribution of a compiled executable does not alter, replace, or supersede the licenses applicable to Python, third-party libraries, runtimes, APIs, models, fonts, icons, or other bundled third-party components.
分发编译后的可执行文件，不会改变、取代或覆盖 Python、第三方程序库、运行环境、API、模型、字体、图标及其他随附第三方组件各自适用的许可证。

Unless otherwise agreed in writing, this license does not require users who modify the software to publish, disclose, or provide the corresponding modified source code.
除非另有书面约定，本许可证不要求修改本软件的使用者公开、披露或提供相应的修改后源代码。

However, users who redistribute a modified version must retain the applicable copyright, license, and attribution notices and must clearly indicate that modifications have been made.
但是，使用者再分发修改后的版本时，仍须保留适用的著作权、许可证及署名声明，并明确说明该版本已经过修改。

### Third-Party Components   第三方组件

This license applies only to original materials for which the repository owner holds the relevant rights.
本许可证仅适用于仓库权利人享有相应权利的原创材料。

Third-party libraries, runtimes, APIs, models, icons, fonts, and other third-party components remain subject to their respective licenses and terms.
第三方程序库、运行环境、API、模型、图标、字体及其他第三方组件，分别适用其各自的许可证和服务条款。

Where this license conflicts with a third-party license or service term, the third-party license or service term governs the relevant component.
本许可证与第三方许可证或服务条款存在冲突时，就相应第三方组件而言，以第三方许可证或服务条款为准。

### Input Documents and OCR Outputs   输入文档与 OCR 输出

This license does not grant any rights in PDF files, images, datasets, articles, books, or other materials supplied by users or third parties.
本许可证不对用户或第三方提供的 PDF、图片、数据集、论文、图书及其他材料授予任何权利。

OCR output generated from such materials remains subject to the rights and restrictions applicable to the original materials.
基于上述材料生成的 OCR 结果，仍受原始材料所涉及的权利和限制约束。

Users are responsible for ensuring that they have the authority to upload, process, reproduce, modify, publish, or distribute their input documents and OCR outputs.
用户应自行确认其有权上传、处理、复制、修改、发表或传播输入文档及相应 OCR 输出。

### Disclaimer   免责声明

The licensed materials are provided “as is”, without warranties of any kind.
本许可材料均按“现状”提供，不作任何形式的保证。

To the maximum extent permitted by applicable law, the Licensor shall not be liable for any loss, data loss, service interruption, API charge, or other liability arising from the use of the licensed materials.
在适用法律允许的最大范围内，许可人不对因使用许可材料而产生的任何损失、数据丢失、服务中断、API 费用或其他责任承担赔偿责任。

For commercial licensing or permissions beyond those stated above, please contact the Licensor.
如需商业许可或超出本文件范围的其他授权，请与许可人联系。
