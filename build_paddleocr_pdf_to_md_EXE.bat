@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM 一键打包 EXE：PaddleOCR PDF -> Markdown GUI
REM 版本：26.7.12.02
REM 生成位置固定为：PaddleOCR_PDF_to_MD_EXE\PaddleOCR_PDF_to_MD.exe
REM ============================================================

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%paddleocr_pdf_to_md_gui.py"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "OUTDIR=%ROOT%PaddleOCR_PDF_to_MD_EXE"
set "WORKDIR=%ROOT%build_paddleocr_pdf_to_md"
set "EXE=%OUTDIR%\PaddleOCR_PDF_to_MD.exe"
set "LOCATION_FILE=%ROOT%EXE位置.txt"

pushd "%ROOT%" >nul 2>nul

echo ============================================================
echo PaddleOCR PDF -^> Markdown GUI EXE 打包器 26.7.12.02
echo 当前目录：%ROOT%
echo ============================================================
echo.

if not exist "%SCRIPT%" (
    echo [错误] 找不到主程序：%SCRIPT%
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

echo [安装/更新] requests、pypdf 与 pyinstaller...
"%PYTHON%" -m pip install --upgrade pip
"%PYTHON%" -m pip install --upgrade requests pypdf pyinstaller
if errorlevel 1 (
    echo [错误] 依赖安装失败。请检查网络、代理或 pip 源。
    pause
    exit /b 1
)

if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%WORKDIR%" rmdir /s /q "%WORKDIR%"
mkdir "%OUTDIR%" >nul 2>nul
mkdir "%WORKDIR%" >nul 2>nul

echo.
echo [打包] 正在生成单文件 EXE...
"%PYTHON%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "PaddleOCR_PDF_to_MD" ^
  --distpath "%OUTDIR%" ^
  --workpath "%WORKDIR%\work" ^
  --specpath "%WORKDIR%" ^
  --collect-submodules pypdf ^
  "%SCRIPT%"
if errorlevel 1 (
    echo.
    echo [错误] EXE 打包失败。请把本窗口上方报错复制给我。
    pause
    exit /b 1
)

if not exist "%EXE%" (
    echo [错误] PyInstaller 未生成预期文件：%EXE%
    pause
    exit /b 1
)

> "%LOCATION_FILE%" echo %EXE%

echo.
echo [完成] EXE 已生成：
echo %EXE%
echo.
echo 路径也已写入：%LOCATION_FILE%
echo 正在打开 EXE 所在文件夹...
explorer /select,"%EXE%"
echo.
pause
popd >nul 2>nul
endlocal
