@echo off
REM �蓮��Web�T�[�o�[���N������o�b�`�B�o�b�`���̂͒ʏ���Ŏ��s���邪�A
REM �T�[�o�[�{�̂� .venv ��Python�𒼐ڎw�肵�ĉ��z���ŋN������B
setlocal
cd /d "%~dp0"

set VENV_PYTHON=.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo [ERROR] .venv ��������܂���B�ȉ��̃R�}���h�ŉ��z�����쐬���Ă��������B
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

if not exist logs mkdir logs

REM Default NESTING_ROOT_PATH to /nesting for the IIS reverse-proxy path rewrite
REM (https://xxx.com/nesting/ -> http://127.0.0.1:8090/), unless already set by the caller.
REM For direct local/no-proxy access, run "set NESTING_ROOT_PATH=" before this script.
if not defined NESTING_ROOT_PATH set NESTING_ROOT_PATH=/nesting

REM ���O�t�@�C�����Ƀ^�C���X�^���v��t�^���邽��PowerShell�Ńt�H�[�}�b�g����
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
set LOGFILE=logs\server_%TS%.log

echo Starting NetsingTool server (host=0.0.0.0 port=8090)
echo NESTING_ROOT_PATH=%NESTING_ROOT_PATH%
echo Log file: %LOGFILE%
echo Press Ctrl+C to stop.
echo.

REM cmd�ɂ�tee�������������߁A�R���\�[���\���ƃt�@�C���o�̗͂�����PowerShell��Tee-Object���g��
"%VENV_PYTHON%" -m uvicorn webapp.main:app --host 0.0.0.0 --port 8090 2>&1 | powershell -NoProfile -Command "$input | ForEach-Object { $_.ToString() } | Tee-Object -FilePath '%LOGFILE%'"

echo.
echo Server stopped.
pause
endlocal
