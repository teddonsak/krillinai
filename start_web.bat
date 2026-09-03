@echo off
chcp 65001 > nul
title KrillinAI + OpenShorts Studio (Thai Edition)
echo ======================================================================
echo    KrillinAI + OpenShorts Studio - ระบบผลิตคลิปสั้นแนวตั้งภาษาไทย
echo ======================================================================
echo.
echo กำลังเริ่มต้นเซิร์ฟเวอร์ระบบเว็บ...
echo เปิดใช้งานผ่านเว็บเบราว์เซอร์ได้ที่: http://127.0.0.1:8888
echo.

start http://127.0.0.1:8888
python server.py

pause
