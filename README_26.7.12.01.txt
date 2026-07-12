PaddleOCR PDF 批量转 Markdown 26.7.12.02

直接运行：
1. 将本压缩包完整解压。
2. 双击 start_paddleocr_pdf_to_md_SAFE.bat。

打包 EXE：
1. 双击 build_paddleocr_pdf_to_md_EXE.bat。
2. 生成文件固定在：
   PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD.exe
3. 打包完成后会自动打开资源管理器并选中 EXE。

本版新增：
- 超过 50MB 的 PDF 自动拆分为约 45MB 的分段。
- 分段依次 OCR，最终合并为一个同名 .md 和一个同名 .json。
- “开始批量转换”位于操作区最右侧。
- “停止转换”为红底白字，点击后需要再次确认。
- 保留手动查询当前结果、API Key 检测、JSON 修复、队列满自动重试等功能。
