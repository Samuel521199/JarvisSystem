@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Jarvis

set "JARVIS_BOOT_PYTHON=%JARVIS_PYTHON%"
if not defined JARVIS_BOOT_PYTHON set "JARVIS_BOOT_PYTHON=%~dp0..\JarvisData\envs\dev\Scripts\python.exe"
if not exist "%JARVIS_BOOT_PYTHON%" goto missing_python

"%JARVIS_BOOT_PYTHON%" -X utf8 -B "%~dp0tools\start_jarvis.py" %*
if errorlevel 1 goto failed
exit /b 0

:missing_python
echo 未找到 Jarvis 的 Python 环境：
echo "%JARVIS_BOOT_PYTHON%"
echo 请准备原开发环境，或设置 JARVIS_PYTHON 指向已有的 python.exe。

:failed
echo.
echo 启动未完成。请保留上方错误信息；现有数据不会被重置。
if not defined JARVIS_NO_PAUSE pause
exit /b 1
