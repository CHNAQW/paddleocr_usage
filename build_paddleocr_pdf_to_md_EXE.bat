@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================================
REM PaddleOCR PDF -> Markdown GUI 26.7.18.03 EXE 打包器
REM 强化标题栏图标并加入程序内左上角图标。
REM ============================================================

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%paddleocr_pdf_to_md_gui.py"
set "ICON_ICO=%ROOT%app_icon.ico"
set "ICON_PNG=%ROOT%app_icon.png"
set "VERSION_FILE=%ROOT%version_info_26.7.18.03.txt"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "OUTDIR=%ROOT%PaddleOCR_PDF_to_MD_EXE"
set "WORKDIR=%ROOT%build\pyinstaller"
set "SPECDIR=%ROOT%build\spec"
set "EXE_NAME=PaddleOCR_PDF_to_MD_26.7.18.03"
set "EXE_PATH=%OUTDIR%\%EXE_NAME%.exe"

pushd "%ROOT%" >nul 2>nul

echo ============================================================
echo PaddleOCR PDF -^> Markdown GUI 26.7.18.03 EXE 打包器
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
if not exist "%VERSION_FILE%" (
    echo [错误] 找不到版本信息文件：%VERSION_FILE%
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

echo [安装/更新] requests、pypdf 与 pyinstaller...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :dependency_failed
"%PYTHON%" -m pip install --upgrade requests pypdf pyinstaller
if errorlevel 1 goto :dependency_failed

if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%WORKDIR%" rmdir /s /q "%WORKDIR%"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if not exist "%WORKDIR%" mkdir "%WORKDIR%"
if not exist "%SPECDIR%" mkdir "%SPECDIR%"

echo.
echo [打包] 正在嵌入图标和版本信息...
"%PYTHON%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "%EXE_NAME%" ^
  --icon "%ICON_ICO%" ^
  --add-data "%ICON_ICO%;." ^
  --add-data "%ICON_PNG%;." ^
  --version-file "%VERSION_FILE%" ^
  --distpath "%OUTDIR%" ^
  --workpath "%WORKDIR%" ^
  --specpath "%SPECDIR%" ^
  "%SCRIPT%"

if errorlevel 1 goto :failed

if not exist "%EXE_PATH%" (
    echo [错误] 未生成预期的 EXE：%EXE_PATH%
    goto :failed
)

> "%ROOT%EXE位置.txt" echo %EXE_PATH%

echo.
echo [完成] 已生成：
echo %EXE_PATH%
echo.
echo 本版会强化 Windows 原生标题栏图标，并在程序内容区左上角显示图标。
echo 日常使用时直接运行生成的 EXE 即可。
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
