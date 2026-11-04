@echo off
rem Запуск игры без правки PATH — использует Python, установленный в профиль.
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0boss_dungeon_3d.py"
