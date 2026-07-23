@echo off
chcp 65001
cd /d "%USERPROFILE%\Desktop\biance-screen"

:: 1. 先同步雲端
git pull origin main

:: 2. 執行 Python 掃描
python update_data.py

:: 3. 宣告身分並打包推送
git config user.email "bot@windows.local"
git config user.name "Windows Auto Bot"
git add .
git commit -m "Scheduled Update: %date% %time%" || echo "No changes"
git push origin main

:: 移除 pause，讓視窗跑完自動關閉

exit