@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM PaddleOCR PDF -> Markdown GUI 稳定启动脚本
REM 版本：26.7.12.02
REM 请把本 bat 与 paddleocr_pdf_to_md_gui.py 放在同一个文件夹后再双击。
REM 在线异步 API 版：需要 requests；自动拆分大 PDF 需要 pypdf。
REM ============================================================

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%paddleocr_pdf_to_md_gui.py"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

pushd "%ROOT%" >nul 2>nul

echo ============================================================
echo PaddleOCR PDF -^> Markdown GUI 启动器 26.7.12.02
echo 当前目录：%ROOT%
echo ============================================================
echo.

if not exist "%SCRIPT%" (
    echo [错误] 找不到主程序：
    echo %SCRIPT%
    echo.
    echo 请确认 bat 与 paddleocr_pdf_to_md_gui.py 在同一个文件夹。
    pause
    exit /b 1
)

set "BASEPY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "BASEPY=py -3"
if "%BASEPY%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 set "BASEPY=python"
)
if "%BASEPY%"=="" (
    echo [错误] 没找到 Python。
    echo 请安装 Python 3.9 或更新版本，并勾选 Add python.exe to PATH。
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [首次运行] 正在创建虚拟环境：%VENV%
    %BASEPY% -m venv "%VENV%"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
)

set "PYTHONUTF8=1"

echo [检查] requests 与 pypdf...
"%PYTHON%" -c "import requests, pypdf; print('dependencies ok')" >nul 2>nul
if errorlevel 1 (
    echo [安装/更新] 正在安装 requests 与 pypdf...
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install --upgrade requests pypdf
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。请检查网络、代理或 pip 源。
        echo 可手动运行：
        echo "%PYTHON%" -m pip install --upgrade requests pypdf
        pause
        exit /b 1
    )
) else (
    echo [OK] requests 与 pypdf 已安装。
)

echo.
echo [启动] 正在打开图形化界面...
"%PYTHON%" "%SCRIPT%"
set "APP_EXIT=%ERRORLEVEL%"

echo.
if not "%APP_EXIT%"=="0" (
    echo [程序异常退出] 退出码：%APP_EXIT%
    echo 请把本窗口上方的报错截图或复制给我。
) else (
    echo [完成] 程序已退出。
)
echo.
pause
popd >nul 2>nul
endlocal
