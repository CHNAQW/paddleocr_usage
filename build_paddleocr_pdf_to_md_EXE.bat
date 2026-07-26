@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================================
REM PaddleOCR PDF -> Markdown GUI 26.7.26.01 EXE 打包器
REM 使用 Nuitka 原生编译为单个、无压缩 EXE，不要求代码签名证书。
REM ============================================================

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%paddleocr_pdf_to_md_gui.py"
set "ICON_ICO=%ROOT%app_icon.ico"
set "ICON_PNG=%ROOT%app_icon.png"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "OUTDIR=%ROOT%PaddleOCR_PDF_to_MD_EXE"
set "WORKDIR=%ROOT%build\nuitka"
set "EXE_NAME=PaddleOCR_PDF_to_MD_26.7.26.01.exe"
set "EXE_PATH=%OUTDIR%\%EXE_NAME%"
set "HASH_PATH=%OUTDIR%\%EXE_NAME%.sha256.txt"

pushd "%ROOT%" >nul 2>nul

echo ============================================================
echo PaddleOCR PDF -^> Markdown GUI 26.7.26.01 EXE 打包器
echo 输出形式：可直接对外发布的单个 EXE
echo 当前目录：%ROOT%
echo ============================================================
echo.

if not exist "%SCRIPT%" (
    echo [错误] 找不到主程序：%SCRIPT%
    goto :failed
)
if not exist "%ICON_ICO%" (
    echo [错误] 找不到 Windows 图标：%ICON_ICO%
    goto :failed
)
if not exist "%ICON_PNG%" (
    echo [错误] 找不到程序窗口图标：%ICON_PNG%
    goto :failed
)

set "BASEPY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "BASEPY=py -3"
if "%BASEPY%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 set "BASEPY=python"
)
if "%BASEPY%"=="" (
    echo [错误] 没找到 Python 3.9 或更高版本。
    echo 安装 Python 时请勾选 Add python.exe to PATH。
    goto :failed
)

if not exist "%PYTHON%" (
    echo [首次运行] 正在创建虚拟环境：%VENV%
    %BASEPY% -m venv "%VENV%"
    if errorlevel 1 goto :failed
)

set "PYTHONUTF8=1"

echo [安装/更新] 运行依赖与 Nuitka 编译器...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :dependency_failed
"%PYTHON%" -m pip install --upgrade -r "%ROOT%requirements.txt"
if errorlevel 1 goto :dependency_failed
"%PYTHON%" -m pip install --upgrade "Nuitka==2.7.12" "ordered-set>=4.1"
if errorlevel 1 goto :dependency_failed

if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%WORKDIR%" rmdir /s /q "%WORKDIR%"
mkdir "%OUTDIR%"
mkdir "%WORKDIR%"

echo.
echo [编译] 正在使用 Microsoft MSVC 原生编译无压缩单文件 EXE...
"%PYTHON%" -m nuitka ^
  --mode=onefile ^
  --onefile-no-compression ^
  --msvc=latest ^
  --lto=yes ^
  --enable-plugin=tk-inter ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico="%ICON_ICO%" ^
  --include-data-files="%ICON_ICO%=app_icon.ico" ^
  --include-data-files="%ICON_PNG%=app_icon.png" ^
  --company-name="PaddleOCR PDF to Markdown GUI" ^
  --product-name="PaddleOCR PDF to Markdown GUI" ^
  --file-description="PaddleOCR PDF Batch to Markdown GUI" ^
  --file-version=26.7.26.1 ^
  --product-version=26.7.26.1 ^
  --output-dir="%WORKDIR%" ^
  --output-filename="%EXE_NAME%" ^
  --remove-output ^
  "%SCRIPT%"

if errorlevel 1 goto :failed

if not exist "%WORKDIR%\%EXE_NAME%" (
    echo [错误] 未生成预期的 EXE：%WORKDIR%\%EXE_NAME%
    goto :failed
)
move /y "%WORKDIR%\%EXE_NAME%" "%EXE_PATH%" >nul
if errorlevel 1 goto :failed

REM 不在打包流程中调用 Defender：构建目标是避免产生高风险打包特征，
REM 而不是在告警发生后删除产物。发布者仍可在上传前自行扫描。

echo [校验] 正在生成 EXE 的 SHA-256...
powershell.exe -NoLogo -NoProfile -NonInteractive -Command ^
  "$h = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:EXE_PATH).Hash.ToLowerInvariant(); Set-Content -LiteralPath $env:HASH_PATH -Value ($h + '  ' + $env:EXE_NAME) -Encoding ASCII"
if errorlevel 1 goto :failed

> "%ROOT%EXE位置.txt" echo %EXE_PATH%

echo.
echo [完成] 可直接对外发布：
echo %EXE_PATH%
echo [校验文件] %HASH_PATH%
echo.
echo 本构建不需要代码签名证书；请将 EXE 和 SHA-256 文件一起发布。
echo 本脚本使用 MSVC、Nuitka 原生编译、无 UPX、无压缩载荷，避免常见打包器启发式特征。
echo.

start "" explorer.exe /select,"%EXE_PATH%"
pause
popd >nul 2>nul
endlocal
exit /b 0

:dependency_failed
echo.
echo [错误] 依赖安装失败。请检查网络、代理或 pip 源。
goto :failed

:failed
echo.
pause
popd >nul 2>nul
endlocal
exit /b 1
