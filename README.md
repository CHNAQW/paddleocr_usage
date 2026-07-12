This is an executable (and the original `.py` script for Linux and macOS users!) that uses PaddleOCR to convert scanned, non-searchable **Chinese** PDFs into searchable `.md` and `.json` files (`.md` is much easier for AI to read and understand than PDF!).

For more information, please read the README.

这是一个可执行程序（还附带了供 Linux 和 macOS 用户使用的原始 `.py` 脚本！），通过 PaddleOCR 将扫描版、不可检索的**中文** PDF 转换为可检索的 `.md` 和 `.json` 文件（对 AI 来说，`.md` 可比 PDF 好读、好理解多了！）。

更多信息请参阅 README。

# PaddleOCR PDF to Markdown GUI  
# PaddleOCR PDF 转 Markdown 图形化工具

**Version: 26.7.12.02**  
**版本：26.7.12.02**

**Primary platform: Windows 10/11**  
**主要适用平台：Windows 10/11**

**Default model: `PaddleOCR-VL-1.6`**  
**默认模型：`PaddleOCR-VL-1.6`**

A Windows desktop tool for batch-converting PDF files to Markdown through the PaddleOCR online asynchronous API.  
本工具是一个 Windows 桌面程序，用于通过 PaddleOCR 在线异步 API 批量将 PDF 转换为 Markdown。

It supports page-level progress reporting, manual status checks, automatic retry when the submission queue is full, automatic splitting of PDFs larger than 50 MB, JSON/JSONL recovery, and one-click EXE packaging.  
本工具支持页级进度显示、手动查询任务状态、提交队列已满时自动重试、自动拆分超过 50MB 的 PDF、JSON/JSONL 修复，以及一键打包 EXE。

---

## 1. Features  
## 1. 功能概述

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

## 2. Package Contents  
## 2. 文件组成

The package normally contains the following files.  
安装包通常包含以下文件。

```text
paddleocr_pdf_to_md_gui.py
start_paddleocr_pdf_to_md_SAFE.bat
build_paddleocr_pdf_to_md_EXE.bat
README.md
```

The ZIP release may contain the same files.  
ZIP 发布包通常也包含上述文件。

---

## 3. Requirements  
## 3. 运行要求

### Running from Source  
### 通过源码运行

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

### Building the EXE  
### 打包 EXE

The packaging script additionally installs PyInstaller.  
打包脚本还会额外安装 PyInstaller。

```text
pyinstaller
```

---

## 4. Quick Start  
## 4. 快速开始

### Option A: Run with the BAT Launcher  
### 方式一：通过 BAT 启动

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

### Option B: Run the Python File Directly  
### 方式二：直接运行 Python 文件

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


### Option C: Run on Linux  
### 方式三：在 Linux 上运行

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

### Option D: Run on macOS  
### 方式四：在 macOS 上运行

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

## 5. Access Token Setup  
## 5. Access Token 设置

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

## 6. Basic Conversion Workflow  
## 6. 基本转换流程

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

## 7. Available Models  
## 7. 可选模型

The application currently provides the following models.  
程序当前提供以下模型。

```text
PaddleOCR-VL-1.6
PaddleOCR-VL-1.5
PaddleOCR-VL
PP-StructureV3
```

The default model is `PaddleOCR-VL-1.6`.  
默认模型为 `PaddleOCR-VL-1.6`。

Actual availability depends on the PaddleOCR account and server-side API configuration.  
模型是否实际可用，取决于 PaddleOCR 账户权限和服务端 API 配置。

---

## 8. Output Files  
## 8. 输出文件

### Normal PDFs of 50 MB or Less  
### 50MB 及以下的普通 PDF

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

### PDFs Larger Than 50 MB  
### 超过 50MB 的 PDF

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

### Log File  
### 日志文件

The output directory contains the following log file.  
输出目录中会生成以下日志文件。

```text
paddleocr_batch_log.txt
```

The log records successful files, skipped files, failed files, model selection, input/output paths, and processing times.  
日志会记录成功、跳过、失败、模型选择、输入输出路径和处理时间。

### Job Cache  
### Job 缓存

Submitted task IDs are stored in the following directory.  
已提交任务的 ID 保存在以下目录。

```text
_paddleocr_jobs
```

If the application is interrupted, the saved `jobId` may allow the next run to continue querying the existing server task.  
如果程序中断，已保存的 `jobId` 可能使下次运行能够继续查询已有服务器任务。

This may avoid submitting the same document again.  
这样可能避免重复提交同一文档。

---

## 9. Automatic Large-PDF Splitting  
## 9. 超过 50MB 的 PDF 自动拆分

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

## 10. Progress and Manual Query  
## 10. 进度与手动查询

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

## 11. Queue-Full Retry Behavior  
## 11. 队列已满时的自动重试

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

## 12. Stopping a Conversion  
## 12. 停止转换

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

## 13. Repair JSON to Markdown  
## 13. 将 JSON 修复为 Markdown

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

## 14. Building the Standalone EXE  
## 14. 打包独立 EXE

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

It runs PyInstaller in single-file windowed mode.  
脚本会使用 PyInstaller 的单文件、无控制台窗口模式进行打包。

The EXE is generated at the following location.  
EXE 会生成在以下位置。

```text
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD.exe
```

The packaging script also creates the following file.  
打包脚本还会生成以下文件。

```text
EXE位置.txt
```

The script opens File Explorer with the generated EXE selected.  
脚本会自动打开资源管理器并选中生成的 EXE。

The generated EXE contains the Python runtime and bundled dependencies.  
生成的 EXE 已包含 Python 运行环境和打包依赖。

End users normally do not need to install Python.  
最终用户通常无需另外安装 Python。

Internet access and a valid PaddleOCR API token are still required.  
但仍然需要联网并配置有效的 PaddleOCR API Token。

---

## 15. Troubleshooting  
## 15. 常见问题

### The EXE Cannot Be Found  
### 找不到生成的 EXE

Run the packaging BAT file again.  
重新运行打包 BAT 文件。

```text
build_paddleocr_pdf_to_md_EXE.bat
```

Then check the following path.  
随后检查以下路径。

```text
PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD.exe
```

You can also open the following text file.  
也可以打开以下文本文件。

```text
EXE位置.txt
```

### The Model List Still Shows an Older Version  
### 模型列表仍然显示旧版本

Confirm that the application title shows `26.7.12.02`.  
确认程序标题中显示 `26.7.12.02`。

Click **Show Script Location**.  
点击“显示脚本位置”。

Check which `.py` or `.exe` is actually running.  
检查当前实际运行的是哪个 `.py` 或 `.exe`。

An older BAT file may be launching a different copy.  
旧 BAT 可能正在启动其他目录中的旧副本。

### The API Key Check Fails  
### API Key 检测失败

Confirm that the token was copied completely.  
检查 Token 是否完整复制。

Check the network connection and proxy settings.  
检查网络连接和代理设置。

Confirm that the PaddleOCR API service is available to the account.  
确认当前账户具有 PaddleOCR API 使用权限。

Update the token and test again.  
更新 Token 后重新检测。

### A Job Appears Stuck  
### 任务看起来卡住

Click **Manual Query Current Result**.  
点击“手动查询当前结果”。

Review the page-progress indicator.  
查看页数进度。

Check the runtime log.  
查看运行日志。

Restarting the application may reuse the stored `jobId`.  
重启程序后，程序可能复用已保存的 `jobId`。

### OCR Finishes but No Markdown Appears  
### OCR 完成但没有生成 Markdown

Use **Repair JSON to MD**.  
使用“修复JSON为MD”。

Select the generated `.raw.json`, downloaded `.json`, or `.jsonl` file.  
选择生成的 `.raw.json`、下载的 `.json` 或 `.jsonl` 文件。

### A Large PDF Cannot Be Split  
### 大 PDF 无法拆分

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

### The BAT Window Reports a Dependency-Installation Error  
### BAT 显示依赖安装失败

Check the internet connection.  
检查网络连接。

Check the proxy configuration.  
检查代理设置。

Check the pip mirror or package-source configuration.  
检查 pip 镜像源或包源设置。

Check whether security software blocked Python or pip.  
检查安全软件是否拦截 Python 或 pip。

---

## 16. Privacy and Security  
## 16. 隐私与安全

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

## 17. Known Limitations  
## 17. 已知限制

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

EXE packaging is designed primarily for Windows.  
EXE 打包流程主要面向 Windows。

The application does not bypass PaddleOCR quotas, concurrency limits, or service restrictions.  
本程序无法绕过 PaddleOCR 的额度、并发和服务限制。
