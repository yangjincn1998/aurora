@echo off
SET ENV_NAME=whisper

REM 检查conda是否可用
where conda >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到conda命令，请先安装Anaconda或Miniconda并配置环境变量。
    pause
    exit /b 1
)

REM 激活conda环境
CALL conda activate %ENV_NAME%
if errorlevel 1 (
    echo [错误] 激活conda环境失败，请检查环境名称是否正确：%ENV_NAME%
    pause
    exit /b 1
)

REM 运行organizer
python av_organizer_pro.py 