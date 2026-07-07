@echo off
REM ============================================================================
REM 安装 pre-commit hook（Windows）
REM 用法: 双击运行 或 在项目根目录执行 claude-pre-commit\install.bat
REM ============================================================================

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "HOOK_DIR=%REPO_ROOT%\.git\hooks"
set "SOURCE=%SCRIPT_DIR%pre-commit"

if not exist "%HOOK_DIR%" (
    echo 错误: 未找到 .git\hooks 目录，请确认当前在 Git 仓库中运行
    exit /b 1
)

if not exist "%SOURCE%" (
    echo 错误: 未找到 pre-commit 文件: %SOURCE%
    exit /b 1
)

copy /Y "%SOURCE%" "%HOOK_DIR%\pre-commit" >nul

echo √ pre-commit hook 已安装到 %HOOK_DIR%\pre-commit
