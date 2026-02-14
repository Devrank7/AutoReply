@echo off
REM AutoReply AI — Windows Installation
echo Installing AutoReply AI for Windows...

pip install -r requirements.txt
pip install uiautomation psutil mss

echo.
echo Done! To run:
echo   python app.py
echo.
echo Hotkeys: Ctrl+Shift+R (quick) / Ctrl+Shift+E (deep scan)
