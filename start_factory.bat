@echo off
REM Starts ComfyUI, the factory server (dashboard + worker) and n8n. UNTESTED on Windows.
cd /d %~dp0
if not exist secrets\automation_token (.venv\Scripts\python -c "import secrets;open('secrets/automation_token','w').write(secrets.token_urlsafe(32))")
set /p FACTORY_TOKEN=<secrets\automation_token
if exist ComfyUI\main.py start "ComfyUI" /min cmd /c "cd ComfyUI && venv\Scripts\python main.py --listen 127.0.0.1 --force-fp32 --disable-smart-memory"
REM Ollama runs as a background service after install.
start "Factory" cmd /k ".venv\Scripts\python -m factory serve"
set N8N_BLOCK_ENV_ACCESS_IN_NODE=false
set N8N_USER_FOLDER=%~dp0data\n8n
if not exist data\n8n\.imported (
  mkdir data\n8n
  n8n import:workflow --separate --input=n8n\workflows && echo done> data\n8n\.imported
)
start "n8n" cmd /k "n8n start"
timeout /t 8 >nul
start http://127.0.0.1:8765
echo Dashboard: http://127.0.0.1:8765   n8n: http://127.0.0.1:5678  (activate workflows A-D inside n8n when ready)
