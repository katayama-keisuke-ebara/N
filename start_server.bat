@echo off
REM 手動でWebサーバーを起動するバッチ。バッチ自体は通常環境で実行するが、
REM サーバー本体は .venv のPythonを直接指定して仮想環境で起動する。
setlocal
cd /d "%~dp0"

set VENV_PYTHON=.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo [ERROR] .venv が見つかりません。以下のコマンドで仮想環境を作成してください。
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

if not exist logs mkdir logs

REM ログファイル名にタイムスタンプを付与するためPowerShellでフォーマットする
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
set LOGFILE=logs\server_%TS%.log

echo Starting NetsingTool server (host=0.0.0.0 port=8090)
echo Log file: %LOGFILE%
echo Press Ctrl+C to stop.
echo.

REM cmdにはtee相当が無いため、コンソール表示とファイル出力の両立にPowerShellのTee-Objectを使う
"%VENV_PYTHON%" -m uvicorn webapp.main:app --host 0.0.0.0 --port 8090 2>&1 | powershell -NoProfile -Command "$input | ForEach-Object { $_.ToString() } | Tee-Object -FilePath '%LOGFILE%'"

echo.
echo Server stopped.
pause
endlocal
