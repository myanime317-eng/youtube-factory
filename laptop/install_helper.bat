@echo off
title Firmenfriedhof helper - one-time setup
echo.
echo  FIRMENFRIEDHOF - laptop helper setup
echo  ------------------------------------
echo.
cd /d "%USERPROFILE%"

where git >nul 2>nul || (echo  Git is not installed. Install it from https://git-scm.com and run this again. & pause & exit /b 1)
where node >nul 2>nul || (echo  Node.js is not installed. Install it from https://nodejs.org and run this again. & pause & exit /b 1)

echo  [1/4] Getting the channel robot from GitHub...
echo        If a GitHub sign-in window opens, sign in and click Authorize.
if exist "%USERPROFILE%\youtube-factory\.git" (
  cd /d "%USERPROFILE%\youtube-factory" && git pull
) else (
  git clone https://github.com/myanime317-eng/youtube-factory.git "%USERPROFILE%\youtube-factory"
)
if not exist "%USERPROFILE%\youtube-factory\laptop\helper.mjs" (echo  Could not download the robot. Send Claude a screenshot. & pause & exit /b 1)
cd /d "%USERPROFILE%\youtube-factory"
git config user.name "firmenfriedhof-laptop"
git config user.email "laptop@users.noreply.github.com"

echo  [2/4] Updating flow-mcp...
if not exist "%USERPROFILE%\flow-mcp\package.json" (echo  flow-mcp folder not found in %USERPROFILE%. Send Claude a screenshot. & pause & exit /b 1)
cd /d "%USERPROFILE%\flow-mcp"
git pull
call npm.cmd install --no-audit --no-fund
call npm.cmd run build
if not exist "%USERPROFILE%\flow-mcp\dist\core.js" (echo  flow-mcp build failed. Send Claude a screenshot. & pause & exit /b 1)

echo  [3/4] Making the helper start by itself when you log in...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS=%STARTUP%\firmenfriedhof-helper.vbs"
> "%VBS%" echo Set sh = CreateObject("WScript.Shell")
>> "%VBS%" echo sh.CurrentDirectory = "%USERPROFILE%\youtube-factory"
>> "%VBS%" echo sh.Run "cmd /c node ""%USERPROFILE%\youtube-factory\laptop\helper.mjs""", 0, False

echo  [4/4] Starting the helper now...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*youtube-factory*helper.mjs*' } | Invoke-CimMethod -Name Terminate | Out-Null"
timeout /t 2 /nobreak >nul
wscript "%VBS%"

echo.
echo  DONE. The helper now runs quietly in the background whenever your laptop is on.
echo  Keep the small Flow Chrome window signed in (Priyanshi). You can close this window.
echo.
pause
