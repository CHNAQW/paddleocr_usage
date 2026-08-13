This is an executable (and the original `.py` script for Linux and macOS users!) that uses PaddleOCR to convert scanned, non-searchable **Chinese** PDFs into searchable `.md` and `.json` files (`.md` is much easier for AI to read and understand than PDF!).

For more information, please read the README. Terms And Condition please read below.

这是一个可执行程序（还附带了供 Linux 和 macOS 用户使用的原始 `.py` 脚本！），通过 PaddleOCR 将扫描版、不可检索的**中文** PDF 转换为可检索的 `.md` 和 `.json` 文件（对 AI 来说，`.md` 可比 PDF 好读、好理解多了！）。

更多信息请参阅 README，使用条件请见下方条款。

# PaddleOCR PDF to Markdown GUI  
# PaddleOCR PDF 转 Markdown 图形化工具

**Version: 26.8.13.02**
**版本：26.8.13.02**

**Primary platform: Windows 10/11**  
**主要适用平台：Windows 10/11**

**Default model: `PaddleOCR-VL-1.6`**  
**默认模型：`PaddleOCR-VL-1.6`**

A Windows desktop tool for batch-converting PDF files to Markdown through the PaddleOCR online asynchronous API.  
本工具是一个 Windows 桌面程序，用于通过 PaddleOCR 在线异步 API 批量将 PDF 转换为 Markdown。

It supports page-level progress reporting, Markdown word-count quality checks with automatic resubmission, manual status checks, automatic retry when the submission queue is full, automatic splitting of PDFs larger than 50 MB, JSON/JSONL recovery, and one-click EXE packaging.  
本工具支持页级进度显示、Markdown 字数质量检测与自动重新提交、手动查询任务状态、提交队列已满时自动重试、自动拆分超过 50MB 的 PDF、JSON/JSONL 修复，以及一键打包 EXE。

---

## 1. Features  功能概述

- Batch-process all PDF files in a selected folder.  
  批量处理所选文件夹中的全部 PDF。

- Optionally scan subfolders recursively.  
  可选择递归扫描子文件夹。

- Preserve the original subfolder structure in the output directory.  
  可在输出目录中保留原始子文件夹结构。

- Convert each PDF to a same-name Markdown file.  
  为每个 PDF 生成同名 Markdown 文件。

- Save the PaddleOCR response as JSON for troubleshooting and recovery.  
  保存 PaddleOCR 返回的 JSON，便于排错和恢复。

- Display overall file progress.  
  显示全部文件的总体进度。

- Display the current PDF page progress.  
  显示当前 PDF 的页数进度。

- Display the current task status.  
  显示当前任务状态。

- Display detailed runtime logs.  
  显示详细运行日志。

- Manually query the current OCR job without waiting for the next automatic polling cycle.  
  可手动查询当前 OCR 任务，无需等待下一次自动轮询。

- Validate the saved PaddleOCR Access Token/API Key.  
  可检测已保存的 PaddleOCR Access Token/API Key 是否有效。

- Save the Access Token locally so it does not need to be entered every time.  
  在本地保存 Access Token，无需每次重新输入。

- Verify the generated Markdown contains at least 150 words/CJK characters per page; otherwise delete the result and job cache and resubmit up to three total attempts.  
  生成 Markdown 后检查平均每页是否至少包含 150 个词/汉字；不足时删除结果及 jobId 缓存并重新提交，最多共尝试三次。

- Automatically retry when PaddleOCR reports that the submission queue is full.  
  当 PaddleOCR 提示提交队列已满时自动重试。

- Automatically split PDFs larger than 50 MB, OCR each part, and merge the results.  
  自动拆分超过 50MB 的 PDF，逐段 OCR 后再合并结果。

- Repair existing `.json`, `.jsonl`, or `.raw.json` files into directly usable `.md` files.  
  可将已有的 `.json`、`.jsonl` 或 `.raw.json` 修复为可直接使用的 `.md` 文件。

- Safely request cancellation with a confirmation dialog.  
  通过二次确认对话框安全停止转换。

- Build a standalone Windows EXE with the included packaging script.
  可通过配套打包脚本生成独立的 Windows EXE。

---

## 2. Package Contents  文件组成

The package normally contains the following current-version files.  
安装包通常包含以下当前版本文件。

```text
paddleocr_pdf_to_md_gui.py
start_paddleocr_pdf_to_md_SAFE.bat
build_paddleocr_pdf_to_md_EXE.bat
README.md
app_icon.ico
app_icon.png
version_info_26.8.13.02.txt
requirements.txt
```

Old version snapshots such as `paddleocr_pdf_to_md_gui_26.7.12.02.py` and `README_26.7.12.01.txt` are no longer part of the current package.  
`paddleocr_pdf_to_md_gui_26.7.12.02.py`、`README_26.7.12.01.txt` 等旧版本快照不再属于当前发布包。

The ZIP release may contain the same current-version files.  
ZIP 发布包通常也包含上述当前版本文件。

---

## 3. Requirements  运行要求

### Running from Source   通过源码运行

Windows 10 or Windows 11 is recommended.  
建议使用 Windows 10 或 Windows 11。

Python 3.9 or later is required.  
需要安装 Python 3.9 或更高版本。

Internet access is required.  
必须能够正常访问互联网。

A valid PaddleOCR official API Access Token/API Key is required.  
必须具有有效的 PaddleOCR 官方 API Access Token/API Key。

The launcher automatically creates a local virtual environment.  
启动脚本会自动创建本地虚拟环境。

The launcher automatically installs the following packages.  
启动脚本会自动安装以下依赖。

```text
requests
pypdf
```

### Building the EXE   打包 EXE

The packaging script additionally installs the pinned Nuitka compiler and its build helpers. Because the pinned Nuitka 2.7.12 supports Python 3.9–3.13, the build script selects the newest installed interpreter in that range instead of an unsupported Python 3.14 installation.  
打包脚本还会额外安装固定版本的 Nuitka 编译器及其构建依赖。由于固定的 Nuitka 2.7.12 支持 Python 3.9–3.13，构建脚本会选择该范围内已安装的最新解释器，而不会误用不受支持的 Python 3.14。

Microsoft Visual Studio Build Tools is not required. On the first build, Nuitka automatically downloads and caches its supported MinGW64 toolchain; therefore, the first build requires internet access and can take longer.  
无需安装 Microsoft Visual Studio Build Tools。首次打包时，Nuitka 会自动下载并缓存它所支持的 MinGW64 工具链，因此首次打包需要联网，耗时也会更长。

```text
Nuitka
ordered-set
```

---

## 4. Quick Start   快速开始

### Option A: Run with the BAT Launcher  方式一：通过 BAT 启动

Place the following two files in the same folder.  
请将以下两个文件放在同一文件夹中。

```text
paddleocr_pdf_to_md_gui.py
start_paddleocr_pdf_to_md_SAFE.bat
```

Double-click the following file.  
双击以下文件。

```text
start_paddleocr_pdf_to_md_SAFE.bat
```

On first launch, the script locates Python.  
首次运行时，脚本会查找 Python。

It then creates a `.venv` virtual environment.  
随后会创建 `.venv` 虚拟环境。

It installs or updates `requests` and `pypdf`.  
接着会安装或更新 `requests` 与 `pypdf`。

Finally, it starts the graphical interface.  
最后会启动图形化界面。

### Option B: Run the Python File Directly   方式二：直接运行 Python 文件

Install the dependencies first.  
请先安装依赖。

```bat
python -m pip install --upgrade requests pypdf
```

Then run the application.  
随后运行程序。

```bat
python paddleocr_pdf_to_md_gui.py
```


### Option C: Run on Linux  方式三：在 Linux 上运行

The `.bat` launcher and packaged `.exe` are Windows-only.  
`.bat` 启动器和打包后的 `.exe` 仅适用于 Windows。

Linux users should run the `.py` file directly.  
Linux 用户应当直接运行 `.py` 文件。

Open a terminal in the folder containing `paddleocr_pdf_to_md_gui.py`.  
在包含 `paddleocr_pdf_to_md_gui.py` 的文件夹中打开终端。

Create a virtual environment.  
创建虚拟环境。

```bash
python3 -m venv .venv
```

Activate the virtual environment.  
激活虚拟环境。

```bash
source .venv/bin/activate
```

Upgrade pip and install the required packages.  
升级 pip 并安装所需依赖。

```bash
python3 -m pip install --upgrade pip requests pypdf
```

Start the graphical application.  
启动图形化程序。

```bash
python3 paddleocr_pdf_to_md_gui.py
```

The graphical interface requires Python Tkinter support.  
图形化界面需要 Python 的 Tkinter 支持。

If Linux reports `ModuleNotFoundError: No module named 'tkinter'`, install the Tkinter package supplied by your distribution.  
如果 Linux 提示 `ModuleNotFoundError: No module named 'tkinter'`，请安装当前发行版提供的 Tkinter 软件包。

On Debian or Ubuntu, you can usually run the following command.  
在 Debian 或 Ubuntu 上，通常可以运行以下命令。

```bash
sudo apt update
sudo apt install python3-tk
```

On Fedora, you can usually run the following command.  
在 Fedora 上，通常可以运行以下命令。

```bash
sudo dnf install python3-tkinter
```

On Arch Linux, you can usually run the following command.  
在 Arch Linux 上，通常可以运行以下命令。

```bash
sudo pacman -S tk
```

After installing Tkinter, restart the application.  
安装 Tkinter 后，请重新启动程序。

### Option D: Run on macOS   方式四：在 macOS 上运行

The `.bat` launcher and packaged Windows `.exe` cannot run on macOS.  
`.bat` 启动器和 Windows `.exe` 无法在 macOS 上运行。

macOS users should run the `.py` file directly with Python 3.  
macOS 用户应当使用 Python 3 直接运行 `.py` 文件。

Open Terminal in the folder containing `paddleocr_pdf_to_md_gui.py`.  
在包含 `paddleocr_pdf_to_md_gui.py` 的文件夹中打开“终端”。

Create a virtual environment.  
创建虚拟环境。

```bash
python3 -m venv .venv
```

Activate the virtual environment.  
激活虚拟环境。

```bash
source .venv/bin/activate
```

Upgrade pip and install the required packages.  
升级 pip 并安装所需依赖。

```bash
python3 -m pip install --upgrade pip requests pypdf
```

Start the graphical application.  
启动图形化程序。

```bash
python3 paddleocr_pdf_to_md_gui.py
```

The graphical interface requires a Python installation with Tkinter support.  
图形化界面需要所使用的 Python 支持 Tkinter。

If `import tkinter` fails, install a Python distribution that includes Tk support, such as the current installer from Python.org, or add compatible Tcl/Tk support to your existing Python installation.  
如果 `import tkinter` 失败，请安装包含 Tk 支持的 Python 发行版，例如 Python.org 提供的当前安装程序，或为现有 Python 安装兼容的 Tcl/Tk 支持。

You can test Tkinter with the following command.  
可以使用以下命令测试 Tkinter。

```bash
python3 -m tkinter
```

A small test window should appear if Tkinter is available.  
如果 Tkinter 可用，屏幕上应当弹出一个测试窗口。

The Windows EXE packaging BAT does not create a native Linux or macOS application.  
Windows EXE 打包 BAT 不会生成原生 Linux 或 macOS 应用程序。

Linux and macOS users should keep the `.py` file and run it through the virtual environment described above.  
Linux 与 macOS 用户应保留 `.py` 文件，并通过上述虚拟环境运行。

---

## 5. Access Token Setup   Access Token 设置

Open the application.  
打开程序。

Click **Enter/Update Access Token**.  
点击“输入/更新 Access Token”。

Paste the PaddleOCR official API Access Token/API Key.  
粘贴 PaddleOCR 官方 API Access Token/API Key。

Click **Check API Key** to verify it.  
点击“检测 API Key”进行验证。

The token and application settings are stored at the following location.  
Token 与程序设置保存在以下位置。

```text
%APPDATA%\PaddleOCRBatchGUI\config.json
```

The configuration file is stored as plain text.  
该配置文件以明文形式保存。

Do not share it, upload it publicly, or include it in a public repository.  
请勿将其发送给他人、公开上传或提交到公开代码仓库。

---

## 6. Basic Conversion Workflow   基本转换流程

Select the PDF input folder.  
选择 PDF 输入文件夹。

Select the Markdown output folder.  
选择 Markdown 输出文件夹。

Choose a model.  
选择模型。

Choose whether to scan subfolders recursively.  
选择是否递归扫描子文件夹。

Choose whether to preserve the original subfolder structure.  
选择是否保留原始子文件夹结构。

Choose whether to overwrite existing output files.  
选择是否覆盖已有输出文件。

Click **Start Batch Conversion**.  
点击“开始批量转换”。

Confirm the task summary.  
确认任务摘要。

The application submits each PDF as an asynchronous PaddleOCR job.  
程序会将每个 PDF 作为异步 PaddleOCR 任务提交。

It stores the returned `jobId`.  
程序会保存接口返回的 `jobId`。

It then polls the server until the task is complete.  
程序会持续查询服务器，直至任务完成。

---

## 7. Available Models  可选模型

The application currently provides the following models.  
程序当前提供以下模型。

This list is current for version `26.8.13.02`.
以下列表对应 `26.8.13.02` 当前版本。

```text
PaddleOCR-VL-1.6
PaddleOCR-VL-1.5
PaddleOCR-VL
PP-StructureV3
```

The default model is `PaddleOCR-VL-1.6`.  
默认模型为 `PaddleOCR-VL-1.6`。

Version 26.8.13.02 adds a post-OCR word-count quality check and automatic resubmission while keeping `PaddleOCR-VL-1.6` as the default model.
26.8.13.02 版本新增 OCR 后字数质量检测与自动重新提交功能，同时继续使用 `PaddleOCR-VL-1.6` 作为默认模型。

Actual availability depends on the PaddleOCR account and server-side API configuration.  
模型是否实际可用，取决于 PaddleOCR 账户权限和服务端 API 配置。

---

## 8. Output Files  输出文件

### Normal PDFs of 50 MB or Less   50MB 及以下的普通 PDF

For a source file named `example.pdf`, the application normally creates the following files.  
对于名为 `example.pdf` 的源文件，程序通常会生成以下文件。

```text
example.md
example.raw.json
```

If an error occurs, the application may also create the following diagnostic file.  
如果处理失败，程序还可能生成以下诊断文件。

```text
example.error.txt
```

### PDFs Larger Than 50 MB   超过 50MB 的 PDF

Large PDFs are automatically split by page into parts of approximately 45 MB.  
程序会按页将大 PDF 自动拆分为约 45MB 的分段。

Each part contains no more than approximately 900 pages.  
每个分段最多约 900 页。

Each part is submitted separately.  
每个分段会分别提交。

The results are merged after all parts are complete.  
全部分段完成后，程序会合并结果。

The final output contains the following files.  
最终输出包含以下文件。

```text
example.md
example.json
```

The merged JSON contains source-file metadata and the OCR result of each split part.  
合并后的 JSON 包含源文件信息以及各拆分段的 OCR 结果。

Temporary split files are stored in the following directory.  
临时拆分文件保存在以下目录。

```text
_paddleocr_split_work
```

Temporary split PDFs and intermediate results are removed after a successful merge.  
合并成功后，临时 PDF 和中间结果会被自动清理。

Job cache files may remain for troubleshooting and task recovery.  
为便于排错和任务恢复，job 缓存文件可能继续保留。

### Log File   日志文件

The output directory contains the following log file.  
输出目录中会生成以下日志文件。

```text
paddleocr_batch_log.txt
```

The log records successful files, skipped files, failed files, model selection, input/output paths, and processing times.  
日志会记录成功、跳过、失败、模型选择、输入输出路径和处理时间。

### Job Cache   Job 缓存

Submitted task IDs are stored in the following directory.  
已提交任务的 ID 保存在以下目录。

```text
_paddleocr_jobs
```

If the application is interrupted, the saved `jobId` may allow the next run to continue querying the existing server task.  
如果程序中断，已保存的 `jobId` 可能使下次运行能够继续查询已有服务器任务。

This may avoid submitting the same document again.  
这样可能避免重复提交同一文档。

### Markdown Word-Count Quality Check   Markdown 字数质量检测

After each OCR job generates Markdown, the application counts its text before accepting the result. Chinese, Japanese, and Korean unified ideographs are counted one character at a time; non-CJK text is counted by word. Markdown punctuation and formatting symbols are not counted as words.  
每次 OCR 任务生成 Markdown 后，程序都会先统计文本数量，再决定是否接受该结果。中日韩统一表意文字按单个汉字计数，非 CJK 文本按单词计数；Markdown 标点和格式符号不计入字数。

The result passes when it contains at least **150 words/CJK characters per PDF page**. For example, a two-page PDF must contain at least 300 counted units. The page count is read from the PaddleOCR job result when available and otherwise from the local PDF.  
当结果达到**平均每页至少 150 个词/汉字**时即通过。例如，两页 PDF 至少需要 300 个计数单位。程序优先读取 PaddleOCR 任务返回的页数，若返回结果没有页数，则读取本地 PDF。

If the result is below the threshold on the first or second attempt, the application deletes all artifacts from that attempt before submitting a completely new OCR job:  
如果第一次或第二次结果低于阈值，程序会删除该次尝试产生的全部文件，然后重新提交一个全新的 OCR 任务：

```text
example.md
example.json (when present)
example.raw.json
_paddleocr_jobs\<document>.job.json
```

Deleting the job-cache JSON prevents the previous `jobId` from being reused. Each quality attempt receives a distinct batch ID. There are at most **three OCR attempts in total**; this is separate from queue-full submission retries.  
删除 Job 缓存 JSON 可以防止程序复用上一次的 `jobId`。每次质量重试都会使用不同的批次 ID。每个文档**最多共执行三次 OCR**；此流程与“队列已满”时的提交重试相互独立。

If the third OCR result is still below the threshold, the application keeps that final Markdown and JSON for inspection instead of entering an infinite retry loop. It records the count, page count, threshold, attempt number, and warning in the raw JSON, and appends the following warning to the runtime log and final batch summary:  
如果第三次 OCR 结果仍低于阈值，程序会保留最后一次 Markdown 和 JSON 供人工检查，而不会无限重试。Raw JSON 会记录计数、页数、阈值、尝试次数和警告，并在运行日志与最终批处理摘要中追加以下警告：

```text
请核验原件字数，PaddleOCR返回结果可能存在问题。
```

For PDFs larger than 50 MB, the check is applied to every automatically split part using that part's page count. A warning from any part is propagated to the final batch summary.  
对于超过 50MB 并被自动拆分的 PDF，程序会按照每个分段自身的页数分别检查字数；任一分段产生警告时，最终批处理摘要也会显示该警告。

---

## 9. Automatic Large-PDF Splitting  超过 50MB 的 PDF 自动拆分

The PaddleOCR local upload path has a 50 MB file-size limit.  
PaddleOCR 本地上传路径存在 50MB 的文件大小限制。

When the application detects a PDF larger than 50 MB, it reads the PDF by page.  
检测到超过 50MB 的 PDF 后，程序会按页读取文件。

It splits the PDF into ordered parts of approximately 45 MB.  
程序会按照原页序拆分为约 45MB 的分段。

It verifies each part before submission.  
提交前会校验每个分段。

It submits each part separately.  
每个分段会分别提交。

It maps the progress of each part back to the original PDF page range.  
程序会将各分段进度映射回原 PDF 的页码范围。

It merges all Markdown output in the original page order.  
程序会按原始页序合并全部 Markdown。

It creates one final `.md` file and one final `.json` file.  
最终只生成一个 `.md` 文件和一个 `.json` 文件。

If a single isolated page is still larger than the safe split target, the application cannot split it further.  
如果某一页单独拆出后仍超过安全拆分目标，程序将无法继续拆分。

The application will report the relevant page number.  
程序会明确提示对应页码。

Encrypted or damaged PDFs may also fail to split.  
加密或损坏的 PDF 也可能无法拆分。

---

## 10. Progress and Manual Query   进度与手动查询

The application provides a file-progress indicator.  
程序提供文件总进度条。

This shows the number of completed PDFs out of all discovered PDFs.  
该进度条显示已完成 PDF 数量与全部 PDF 数量。

The application also provides a page-progress indicator.  
程序还提供当前页数进度条。

This shows the extracted pages out of the current PDF’s total pages.  
该进度条显示当前 PDF 已解析页数与总页数。

Automatic status polling normally occurs every 3 seconds.  
程序通常每 3 秒自动查询一次任务状态。

Click **Manual Query Current Result** to force an immediate status check.  
点击“手动查询当前结果”可立即查询任务状态。

This skips the current polling wait.  
该操作会跳过当前轮询等待。

It immediately queries the active `jobId`.  
程序会立即查询当前活动的 `jobId`。

It does not submit a duplicate job.  
该功能不会重复提交任务。

---

## 11. Queue-Full Retry Behavior   队列已满时的自动重试

PaddleOCR may return the following message.  
PaddleOCR 可能返回以下提示。

```text
任务提交队列已满，请稍后重试
```

The application also recognizes the equivalent queue-full error code.  
程序也会识别对应的队列已满错误码。

The application waits 20 seconds before retrying.  
程序会等待 20 秒后重试。

It automatically resubmits the current document.  
程序会自动重新提交当前文档。

It attempts submission up to 3 times.  
程序最多尝试提交 3 次。

If all three attempts fail, the current PDF is skipped.  
如果三次尝试均失败，程序会跳过当前 PDF。

The batch then continues with the next file.  
随后继续处理下一个文件。

Rate-limit responses are also retried after a delay.  
遇到请求频率过高时，程序也会等待后重试。

---

## 12. Stopping a Conversion  停止转换

The **Stop Conversion** button uses a red background and white text.  
“停止转换”按钮采用红底白字。

Clicking it opens a second confirmation dialog.  
点击该按钮后会弹出二次确认窗口。

After confirmation, the application stops submitting new files.  
确认后，程序不再提交新的文件。

It attempts to exit the current polling workflow safely.  
程序会尽量安全退出当前查询流程。

A job already submitted to the PaddleOCR server cannot be cancelled by this application.  
已经提交到 PaddleOCR 服务器的任务无法由本程序撤销。

Its saved `jobId` may be reused during the next run.  
其已保存的 `jobId` 可在下次运行时复用。

Stopping the application does not necessarily stop server-side processing.  
停止本程序并不一定会终止服务器端已经开始的 OCR。

---

## 13. Repair JSON to Markdown  将 JSON 修复为 Markdown

Use **Repair JSON to MD** when OCR completed but no usable Markdown was produced.  
当 OCR 已完成但没有生成可用 Markdown 时，可以使用“修复JSON为MD”。

Use it when you downloaded the API `jsonUrl` result.  
当你已经下载接口返回的 `jsonUrl` 结果时，也可以使用该功能。

Use it when you have a previous `.raw.json`.  
当你持有旧版程序生成的 `.raw.json` 时，也可以使用该功能。

Use it when you have PaddleOCR output in JSONL format.  
当你持有 PaddleOCR 返回的 JSONL 文件时，也可以使用该功能。

Supported input formats are listed below.  
支持的输入格式如下。

```text
.json
.jsonl
.raw.json
```

The repair tool parses ordinary JSON and line-delimited JSON.  
修复工具同时支持普通 JSON 和逐行 JSON。

It looks for structures such as the following.  
程序会尝试提取以下结构。

```text
layoutParsingResults[*].markdown.text
```

It writes a same-name `.md` file to the selected output folder.  
程序会在所选输出文件夹中生成同名 `.md` 文件。

If repair fails, a diagnostic file may be created.  
修复失败时，程序可能生成诊断文件。

```text
filename.repair_error.txt
```

---

## 14. Building the Standalone EXE  打包独立 EXE

Keep the following files in the same folder.  
请将以下文件放在同一文件夹中。

```text
paddleocr_pdf_to_md_gui.py
build_paddleocr_pdf_to_md_EXE.bat
```

Double-click the following file.  
双击以下文件。

```text
build_paddleocr_pdf_to_md_EXE.bat
```

The script creates a virtual environment if needed.  
脚本会在需要时创建虚拟环境。

It installs the required packages.  
脚本会安装所需依赖。

It uses pinned Nuitka, the MinGW64 toolchain managed by Nuitka, and link-time optimization to compile the application into one uncompressed, windowed EXE. It automatically accepts Nuitka's toolchain download prompt, so a missing local C compiler no longer causes a fatal error. It does not use PyInstaller, UPX, or compressed payloads. The recipient needs only the resulting EXE.
脚本使用固定版本的 Nuitka、由 Nuitka 管理的 MinGW64 工具链和链接时优化，将程序编译为一个无压缩、无控制台窗口的 EXE。脚本会自动同意 Nuitka 的工具链下载提示，不会再因本机缺少 C 编译器而直接报 fatal error。它不使用 PyInstaller、UPX 或压缩载荷。接收者只需要最终 EXE。

The EXE and its SHA-256 record are generated at the following locations.
EXE 及其 SHA-256 校验文件会生成在以下位置。

```text
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD_26.8.13.02.exe
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD_26.8.13.02.exe.sha256.txt
```

Publish the EXE directly and provide the checksum alongside it. The script opens File Explorer with the generated EXE selected.
可以直接发布该 EXE，并同时提供校验文件。脚本会自动打开资源管理器并选中生成的 EXE。

The generated EXE contains the Python runtime and bundled dependencies.
生成的 EXE 已包含 Python 运行环境和打包依赖。

End users normally do not need to install Python.  
最终用户通常无需另外安装 Python。

Internet access and a valid PaddleOCR API token are still required.  
但仍然需要联网并配置有效的 PaddleOCR API Token。

---

## 15. Troubleshooting  常见问题

### Antivirus Reports AndroidOS/Multiverze or Another Threat   杀毒软件报告 AndroidOS/Multiverze 或其他威胁

The public artifact is now a single `PaddleOCR_PDF_to_MD_26.8.13.02.exe`, compiled with Nuitka rather than bundled with PyInstaller. It uses uncompressed one-file mode to avoid UPX and compressed PyInstaller bootloader patterns; no code-signing certificate is required.
现在的公开发布物就是单个 `PaddleOCR_PDF_to_MD_26.8.13.02.exe`。它改用 Nuitka 编译，不再使用 PyInstaller 打包，并采用无压缩单文件模式，以避开 UPX 和压缩式 PyInstaller 引导器特征；不要求代码签名证书。

The build no longer waits for an antivirus alert and then deletes the EXE. Instead, Python modules are translated to C, compiled with Nuitka's managed MinGW64 toolchain, linked with LTO, and placed in an uncompressed one-file payload. This targets the packaging characteristics that caused the previous alert while preserving direct EXE distribution.
构建流程不再等杀毒软件告警后删除 EXE。Python 模块会转换为 C，使用 Nuitka 管理的 MinGW64 工具链编译，以 LTO 链接，并放入无压缩单文件载荷中。这样是在保留单 EXE 直接发布的同时，针对旧版告警涉及的打包特征进行处理。

No unsigned build system can guarantee acceptance by every antivirus engine because cloud reputation and heuristic definitions change independently of the source code. If Microsoft still classifies this clean Nuitka build as `AndroidOS/Multiverze`, submit that exact EXE to Microsoft Security Intelligence as an incorrectly detected file. Do not disable antivirus protection or tell recipients to add an exclusion.  
任何无签名构建方式都无法保证被每个杀毒引擎接受，因为云信誉和启发式规则会独立变化。如果 Microsoft 仍把这一份干净的 Nuitka 构建识别为 `AndroidOS/Multiverze`，请将准确的 EXE 提交给 Microsoft Security Intelligence 并选择“错误检测”。不要关闭杀毒保护，也不要让接收者添加排除项。

```powershell
Get-FileHash -Algorithm SHA256 .\PaddleOCR_PDF_to_MD_26.8.13.02.exe
Get-Content .\PaddleOCR_PDF_to_MD_26.8.13.02.exe.sha256.txt
```

### Bad Image / status 0xc0e90002   DLL 错误 / 状态 0xc0e90002

The release remains one independent EXE. The current one-file build uses a stable per-user cache under `%LOCALAPPDATA%\PaddleOCR\PDFToMarkdown\26.8.13.02` instead of a random `%TEMP%\onefile_*` directory. This avoids races with Temp cleanup and lets security software inspect the extracted runtime once rather than at every launch.
发布物仍然是一个独立 EXE。当前单文件构建使用 `%LOCALAPPDATA%\PaddleOCR\PDFToMarkdown\26.8.13.02` 下的固定用户缓存，不再使用随机 `%TEMP%\onefile_*` 目录。这样可避免与临时目录清理发生竞争，也无需安全软件在每次启动时重新检查运行组件。

If an older EXE reports this error, delete that old EXE and its old `%TEMP%\onefile_*` folder, rebuild with the current BAT, and send the newly generated EXE together with its SHA-256 record. The recipient should verify that the downloaded EXE hash matches before running it.
如果旧 EXE 出现此错误，请删除旧 EXE 及其旧 `%TEMP%\onefile_*` 目录，用当前 BAT 重新构建，并将新 EXE 与 SHA-256 记录一起发送。接收者运行前应确认下载所得 EXE 的哈希一致。

If the current build is interrupted during its first extraction, close the application, delete `%LOCALAPPDATA%\PaddleOCR\PDFToMarkdown\26.8.13.02`, and launch the same EXE again so it can recreate a clean cache. Do not disable antivirus protection or add an exclusion.
如果当前构建首次释放组件时被中断，请关闭程序，删除 `%LOCALAPPDATA%\PaddleOCR\PDFToMarkdown\26.8.13.02`，然后重新启动同一个 EXE，让它重建干净缓存。不要关闭杀毒保护，也不要添加排除项。

### The EXE Cannot Be Found   找不到生成的 EXE

Run the packaging BAT file again.  
重新运行打包 BAT 文件。

```text
build_paddleocr_pdf_to_md_EXE.bat
```

Then check the following path.  
随后检查以下路径。

```text
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD_26.8.13.02.exe
```

You can also open the following text file.  
也可以打开以下文本文件。

```text
EXE位置.txt
```

### The Model List Still Shows an Older Version  模型列表仍然显示旧版本

Confirm that the application title shows `26.8.13.02`.
确认程序标题中显示 `26.8.13.02`。

Check the folder from which you launched `paddleocr_pdf_to_md_gui.py` or the versioned EXE.  
检查你启动 `paddleocr_pdf_to_md_gui.py` 或带版本号 EXE 的所在文件夹。

An older BAT file may be launching a different copy.  
旧 BAT 可能正在启动其他目录中的旧副本。

### The API Key Check Fails   API Key 检测失败

Confirm that the token was copied completely.  
检查 Token 是否完整复制。

Check the network connection and proxy settings.  
检查网络连接和代理设置。

Confirm that the PaddleOCR API service is available to the account.  
确认当前账户具有 PaddleOCR API 使用权限。

Update the token and test again.  
更新 Token 后重新检测。

### A Job Appears Stuck   任务看起来卡住

Click **Manual Query Current Result**.  
点击“手动查询当前结果”。

Review the page-progress indicator.  
查看页数进度。

Check the runtime log.  
查看运行日志。

Restarting the application may reuse the stored `jobId`.  
重启程序后，程序可能复用已保存的 `jobId`。

### OCR Finishes but No Markdown Appears   OCR 完成但没有生成 Markdown

Use **Repair JSON to MD**.  
使用“修复JSON为MD”。

Select the generated `.raw.json`, downloaded `.json`, or `.jsonl` file.  
选择生成的 `.raw.json`、下载的 `.json` 或 `.jsonl` 文件。

### A Large PDF Cannot Be Split   大 PDF 无法拆分

The PDF may be encrypted.  
PDF 可能已经加密。

The PDF may be damaged.  
PDF 文件可能已经损坏。

A single isolated page may still be too large.  
某一页单独拆出后可能仍然过大。

`pypdf` may be missing or outdated.  
`pypdf` 可能缺失或版本过旧。

Run the following command to update it.  
运行以下命令进行更新。

```bat
python -m pip install --upgrade pypdf
```

### The BAT Window Reports a Dependency-Installation Error   BAT 显示依赖安装失败

Check the internet connection.  
检查网络连接。

Check the proxy configuration.  
检查代理设置。

Check the pip mirror or package-source configuration.  
检查 pip 镜像源或包源设置。

Check whether security software blocked Python or pip.  
检查安全软件是否拦截 Python 或 pip。

---

## 16. Privacy and Security  隐私与安全

PDF files are uploaded to the PaddleOCR online API for processing.  
PDF 文件会被上传至 PaddleOCR 在线 API 处理。

Do not process confidential, restricted, personal, or regulated documents unless external API processing is permitted.  
对于涉密、受限、个人信息或受监管材料，请先确认相关规定允许使用外部 API。

The Access Token is stored locally in plain text.  
Access Token 会以明文形式保存在本地。

Its location is shown below.  
其保存位置如下。

```text
%APPDATA%\PaddleOCRBatchGUI\config.json
```

Protect this file.  
请妥善保护该文件。

Remove the saved token before sharing the computer, application folder, screenshots, or diagnostic packages.  
在共享电脑、程序目录、截图或诊断文件前，请先清除已保存 Token。

---

## 17. Known Limitations   已知限制

The application requires internet access.  
本程序必须联网使用。

Server-side availability, queue capacity, and model access are controlled by PaddleOCR.  
服务可用性、队列容量和模型权限由 PaddleOCR 服务端控制。

A server task already submitted cannot be cancelled from this application.  
已经提交的服务器任务无法通过本程序撤销。

Automatic splitting is page-based.  
自动拆分以页面为基本单位。

An unusually large single page may still remain above the upload threshold.  
异常巨大的单页可能仍然无法降至上传限制以下。

Markdown quality depends on the selected model, document layout, image quality, language, and server output.  
Markdown 质量取决于所选模型、文档版式、图像质量、语言和服务端输出。

# License   许可证

[![Creative Commons License](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)  
[![知识共享许可协议](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)

Unless otherwise stated in a specific file, the original software, source code, Python scripts, batch scripts, build scripts, compiled executable files, documentation, and other original materials in this repository are licensed under the [Creative Commons Attribution–NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/) (**CC BY-NC 4.0**).  
除特定文件另有说明外，本仓库中的原创软件、源代码、Python 脚本、批处理脚本、构建脚本、编译后的可执行文件、说明文档及其他原创材料，均采用[知识共享署名—非商业性使用 4.0 国际许可协议](https://creativecommons.org/licenses/by-nc/4.0/)（**CC BY-NC 4.0**）授权使用。

Under CC BY-NC 4.0, users may copy, redistribute, modify, and build upon the licensed materials for noncommercial purposes, provided that appropriate attribution is retained and any modifications are clearly indicated.  
根据 CC BY-NC 4.0，使用者可以出于非商业目的复制、传播、修改和演绎上述许可材料，但须保留适当署名，并明确说明是否进行了修改。

## Additional Academic Permissions   学术用途附加许可

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

## Attribution and Modification Notices  署名与修改声明

The attribution requirement under CC BY-NC 4.0 remains applicable to all permitted uses.  
CC BY-NC 4.0 规定的署名义务仍适用于所有获准使用情形。

Users who copy, modify, redistribute, demonstrate, present, or describe the licensed materials must retain the copyright, license, and attribution notices contained in this repository.  
复制、修改、再分发、演示、展示或介绍许可材料时，使用者应保留本仓库中已有的著作权、许可证和署名声明。

Users must clearly indicate whether modifications have been made.  
使用者还应明确说明是否对许可材料进行了修改。

## Software Distribution Notice  软件分发说明

This project is **source-available software** and is not distributed under an open-source license approved by the Open Source Initiative (**OSI**).  
本项目属于**代码公开软件**，并非依据开放源代码促进会（**OSI**）认可的开源许可证进行分发。

Distribution of a compiled executable does not alter, replace, or supersede the licenses applicable to Python, third-party libraries, runtimes, APIs, models, fonts, icons, or other bundled third-party components.  
分发编译后的可执行文件，不会改变、取代或覆盖 Python、第三方程序库、运行环境、API、模型、字体、图标及其他随附第三方组件各自适用的许可证。

Unless otherwise agreed in writing, this license does not require users who modify the software to publish, disclose, or provide the corresponding modified source code.  
除非另有书面约定，本许可证不要求修改本软件的使用者公开、披露或提供相应的修改后源代码。

However, users who redistribute a modified version must retain the applicable copyright, license, and attribution notices and must clearly indicate that modifications have been made.  
但是，使用者再分发修改后的版本时，仍须保留适用的著作权、许可证及署名声明，并明确说明该版本已经过修改。

## Third-Party Components   第三方组件

This license applies only to original materials for which the repository owner holds the relevant rights.  
本许可证仅适用于仓库权利人享有相应权利的原创材料。

Third-party libraries, runtimes, APIs, models, icons, fonts, and other third-party components remain subject to their respective licenses and terms.  
第三方程序库、运行环境、API、模型、图标、字体及其他第三方组件，分别适用其各自的许可证和服务条款。

Where this license conflicts with a third-party license or service term, the third-party license or service term governs the relevant component.  
本许可证与第三方许可证或服务条款存在冲突时，就相应第三方组件而言，以第三方许可证或服务条款为准。

## Input Documents and OCR Outputs   输入文档与 OCR 输出

This license does not grant any rights in PDF files, images, datasets, articles, books, or other materials supplied by users or third parties.  
本许可证不对用户或第三方提供的 PDF、图片、数据集、论文、图书及其他材料授予任何权利。

OCR output generated from such materials remains subject to the rights and restrictions applicable to the original materials.  
基于上述材料生成的 OCR 结果，仍受原始材料所涉及的权利和限制约束。

Users are responsible for ensuring that they have the authority to upload, process, reproduce, modify, publish, or distribute their input documents and OCR outputs.  
用户应自行确认其有权上传、处理、复制、修改、发表或传播输入文档及相应 OCR 输出。

## Disclaimer   免责声明

The licensed materials are provided “as is”, without warranties of any kind.  
本许可材料均按“现状”提供，不作任何形式的保证。

To the maximum extent permitted by applicable law, the Licensor shall not be liable for any loss, data loss, service interruption, API charge, or other liability arising from the use of the licensed materials.  
在适用法律允许的最大范围内，许可人不对因使用许可材料而产生的任何损失、数据丢失、服务中断、API 费用或其他责任承担赔偿责任。

For commercial licensing or permissions beyond those stated above, please contact the Licensor.  
如需商业许可或超出本文件范围的其他授权，请与许可人联系。


## Optional OpenAI-compatible LLM review  可选 LLM 核验

Version `26.8.13.02` can optionally send each generated Markdown file to an OpenAI-compatible Chat Completions API (for example DeepSeek) to identify obvious conversion failures. This feature is disabled by default and does not rewrite the Markdown. If the LLM reports a conversion problem, the app deletes the current `.md`, result JSON, review report, and jobId cache, then submits a fresh OCR job (up to three quality attempts). An LLM request failure is logged without deleting a successful OCR result.

`26.8.13.02` 可选接入 OpenAI-compatible Chat Completions API（例如 DeepSeek），检查每个已生成 Markdown 是否存在明显转换失败。该功能默认关闭，不会改写 Markdown。若 LLM 判定转换有问题，程序会删除本次 `.md`、结果 JSON、核验报告和 jobId 缓存，然后重新提交 OCR（质量核验最多三次）；LLM 请求失败只记录警告，不删除已成功生成的 OCR 结果。

1. Enable **使用 LLM 核验 .md 转换质量** in Settings.
2. Enter the provider Base URL (the default is `https://api.deepseek.com/v1`) and API Key.
3. Click **拉取模型列表** to query the compatible `GET /models` endpoint, then select a model. A model ID can also be entered manually for providers that do not expose model discovery.
4. Start the normal batch conversion. Long Markdown is reviewed in 50,000-character chunks so the whole file is covered.

The review prompt asks the model to detect garbled text, truncation, page/paragraph disorder, large duplicate regions, leaked JSON/HTML error responses, severely broken tables/formulas, missing pages, or nearly empty body text. It explicitly forbids rewriting and avoids treating ordinary OCR typos as a conversion failure. The model must return structured JSON with a boolean conclusion, severity, summary, issues, and short evidence.

1. 在“设置”中勾选 **使用 LLM 核验 .md 转换质量**。
2. 填写服务商 Base URL（默认 `https://api.deepseek.com/v1`）和 API Key。
3. 点击 **拉取模型列表**，程序会调用兼容的 `GET /models` 接口，然后选择模型；若服务商不支持模型发现，也可手工输入模型 ID。
4. 正常开始批处理。长 Markdown 会按每段 50,000 字符逐段核验，避免只检查文件开头。

API Key 会与 PaddleOCR Token 一样保存在当前用户配置文件中。请只在可信的个人电脑上使用，并确认服务商的数据处理政策；文档正文会发送给所配置的第三方 LLM 服务。

### Manual Markdown checks  手动检验

Use **手动字数检验** to select one or more existing `.md` files. The application reads the page count from a sibling `.raw.json`/`.json` or same-name PDF when available; otherwise it conservatively treats the document as one page. It reports the counted words/CJK characters and the required threshold without deleting files or resubmitting OCR.

Use **手动LLM检验** to review existing `.md` files with the configured OpenAI-compatible model. It runs in the background and writes a sibling `.llm-review.json`. Manual checks are diagnostic only: they never delete files or submit OCR jobs.

使用 **手动字数检验** 可选择一个或多个已有 `.md`。程序优先从同名 `.raw.json`、`.json` 或 PDF 获取页数，均不存在时按一页计算；该操作只显示字数与阈值，不删除文件，也不重新提交 OCR。

使用 **手动LLM检验** 可通过已配置的 OpenAI-compatible 模型核验已有 `.md`。检验在后台运行，并写入同名 `.llm-review.json`。两种手动检验都仅供诊断，不会删除文件或提交 OCR 任务。

### Why the build environment was rebuilt every time  为什么每次构建都重建虚拟环境

The previous BAT checked `%ERRORLEVEL%` inside a parenthesized block. Windows `cmd.exe` expands `%ERRORLEVEL%` when parsing the whole block, so it could reuse the status from an earlier command and incorrectly conclude that a supported Python was unsupported. The build script now branches directly from the Python version-check command with `|| goto :rebuild_venv`, so a valid Python 3.9–3.13 environment is reused.

旧 BAT 在括号块内检查 `%ERRORLEVEL%`。Windows `cmd.exe` 会在解析整个括号块时提前展开该值，因此可能沿用之前命令的状态，误判现有 Python 不受支持。现在版本检测命令使用 `|| goto :rebuild_venv` 直接按自身退出码跳转，合法的 Python 3.9–3.13 虚拟环境会被正常复用。

**Build environment correction:** the build script now uses `.venv-nuitka-2.7.12`, separate from the launcher's `.venv`. The launcher may create `.venv` with Python 3.14, which is valid for running this application but unsupported by pinned Nuitka 2.7.12. Sharing that directory made the build legitimately replace it. In addition, the old quoted Python version expression contained CMD caret escapes (`^<`); those characters can reach Python literally and make the probe fail with a syntax error, producing the same misleading rebuild message. The new probe avoids CMD metacharacters entirely and prints the rejected interpreter version before a real rebuild.

**构建环境修正：**构建脚本现在使用独立的 `.venv-nuitka-2.7.12`，不再与启动器的 `.venv` 共用。启动器可能用 Python 3.14 创建 `.venv`；它可以正常运行本程序，但固定的 Nuitka 2.7.12 不支持它，所以共用环境时构建脚本确实会替换该环境。此外，旧版放在引号内的 Python 版本表达式含有 CMD 脱字符（`^<`），这些字符可能被原样交给 Python，导致检测语句发生语法错误，进而显示同一条误导性的重建提示。新检测不再包含 CMD 元字符，并会在确实需要重建前显示被拒绝的 Python 版本。

### Test LLM API connectivity  测试 LLM API 连通性

After entering the Base URL, API Key, and model, click **测试LLM API**. The application sends a small `chat/completions` request asking the selected model to reply `OK`. A successful result therefore verifies the endpoint, authentication, selected model access, and actual generation path—not merely that `GET /models` is reachable. The test runs in the background and shows the model reply; it does not send document content.

填写 Base URL、API Key 和模型后，点击 **测试LLM API**。程序会向 `chat/completions` 发送一个仅要求所选模型回复 `OK` 的小请求。因此测试成功能够同时验证接口地址、鉴权、模型访问权限和实际生成链路，而不只是验证 `GET /models` 是否可访问。测试在后台运行，会显示模型回复，且不会发送文档内容。
