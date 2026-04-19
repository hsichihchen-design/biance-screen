@echo off
chcp 65001
echo =========================================
echo 啟動幣安合約 180K 掃描與 GitHub 同步程序
echo 時間: %date% %time%
echo =========================================

:: 1. 切換到桌面專案資料夾
cd /d "%USERPROFILE%\Desktop\biance-screen"

:: 2. 【核心修正】：先將雲端最新的狀態同步下來，避免任何衝突
echo.
echo [1/3] 正在同步雲端最新代碼...
git pull origin main

:: 3. 執行 Python 爬蟲 (這會產生最新 JSON，並直接覆蓋掉剛下載的舊檔案)
echo.
echo [2/3] 正在執行 180K 市場掃描...
python update_data.py

:: 4. 執行 Git 同步指令
echo.
echo [3/3] 正在推送到 GitHub...

:: 宣告機器人身分
git config user.email "bot@windows.local"
git config user.name "Windows Auto Bot"

:: 一次打包所有變更並上傳
git add .
git commit -m "Auto-update from Local Windows: %date% %time%" || echo (無新變更)
git push origin main

echo.
echo =========================================
echo 執行完畢！
echo =========================================
pause