@echo off
rem 小飞网络助手 · 一键启动（开发运行）
cd /d "%~dp0"
py -3 run.py 2>nul || python run.py
