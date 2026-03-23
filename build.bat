@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "voice.ico" (
    echo [ERROR] voice.ico not found in this folder.
    echo Place voice.ico next to app.py then run this script again.
    pause
    exit /b 1
)

python -m pip install "pyinstaller>=6.0" --quiet
if errorlevel 1 (
    echo Failed to install PyInstaller. Check that Python is on PATH.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --onefile --windowed --name "VoiceToText" --icon "voice.ico" ^
  --add-data "voice.ico;." ^
  --hidden-import speech_recognition ^
  --hidden-import pydub ^
  --hidden-import pydub.utils ^
  --collect-all static_ffmpeg ^
  app.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Done: dist\VoiceToText.exe
echo.
pause
