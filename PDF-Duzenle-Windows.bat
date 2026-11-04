@echo off
REM Windows: cift tikla. Ilk acilista gerekli parcalari indirir (1-2 dk).
cd /d "%~dp0"
chcp 65001 >nul
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >/dev/null 2>/dev/null && goto run
echo Bu uygulama "uv" adli kucuk bir aracla calisir ve bu bilgisayarda yok.
set /p c=Simdi kurulsun mu? (e/h) 
if /i not "%c%"=="e" goto end
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
:run
uv run --no-dev server.py %*
:end
pause
