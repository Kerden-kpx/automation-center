@echo off
REM 启动 Chrome 调试模式脚本
REM 用于 GPT 自动化功能

echo ========================================
echo 启动 Chrome 调试模式
echo ========================================
echo.

REM 尝试不同的 Chrome 安装路径
set CHROME_PATH=

REM 方法1: 标准安装路径
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
    goto :start
)

REM 方法2: 64位系统路径
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
    goto :start
)

REM 方法3: 用户目录下的 Chrome
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
    goto :start
)

REM 如果都找不到，尝试使用 chrome 命令（如果 Chrome 在 PATH 中）
where chrome.exe >nul 2>&1
if %errorlevel% == 0 (
    echo 使用系统 PATH 中的 Chrome...
    start chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\tmp\chrome-debug"
    goto :success
)

echo 错误: 找不到 Chrome 浏览器！
echo.
echo 请手动指定 Chrome 路径，或确保 Chrome 在系统 PATH 中
echo.
pause
exit /b 1

:start
echo 找到 Chrome: %CHROME_PATH%
echo.
echo 正在启动 Chrome 调试模式（端口 9222）...
echo 使用用户数据目录: C:\tmp\chrome-debug
echo.
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="C:\tmp\chrome-debug"

:success
echo.
echo ========================================
echo Chrome 调试模式已启动！
echo ========================================
echo.
echo 下一步:
echo 1. 在打开的 Chrome 窗口中访问 https://chat.openai.com
echo 2. 登录你的 GPT 账号
echo 3. 保持页面打开
echo 4. 然后运行测试脚本或启动钉钉机器人
echo.
echo 提示: 不要关闭这个 Chrome 窗口！
echo.
pause

