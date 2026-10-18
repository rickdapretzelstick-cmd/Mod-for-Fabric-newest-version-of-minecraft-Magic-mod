<#  One-time setup for Windows 10/11. UNTESTED on Windows (written on Linux): run it in a normal PowerShell and read the output.
    Installs only free software via winget. Does not purchase or subscribe to anything.
    Run:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1                                         #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Need($id, $cmd) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Host "Installing $id"; winget install -e --id $id --accept-package-agreements --accept-source-agreements } else { Write-Host "$cmd already installed" } }
Need "Python.Python.3.12" "python"; Need "Gyan.FFmpeg" "ffmpeg"; Need "OpenJS.NodeJS.LTS" "node"; Need "Ollama.Ollama" "ollama"; Need "Git.Git" "git"
Write-Host "`nOpen a NEW PowerShell if any of the above were just installed (PATH refresh), then re-run this script to continue.`n"

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt piper-tts

# Piper voice (MIT-licensed voice model from rhasspy/piper-voices)
New-Item -ItemType Directory -Force models\piper | Out-Null
$b = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
foreach ($f in "en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json") { if (-not (Test-Path "models\piper\$f")) { Invoke-WebRequest "$b/$f" -OutFile "models\piper\$f" } }

# Local LLM (about 4.7 GB). Fits the 1080 Ti's 11 GB comfortably.
ollama pull qwen2.5:7b-instruct-q4_K_M

# Dashboard
Push-Location dashboard; npm install; npm run build; Pop-Location

# n8n (npm install; no Docker needed)
npm install -g n8n

# ComfyUI (images). Pascal GPUs need a PyTorch build that still ships sm_61 kernels: use the cu126 wheels, then verify.
if (-not (Test-Path ComfyUI)) { git clone https://github.com/comfyanonymous/ComfyUI.git ComfyUI }
if (-not (Test-Path ComfyUI\venv)) { python -m venv ComfyUI\venv }
ComfyUI\venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
ComfyUI\venv\Scripts\python -m pip install -r ComfyUI\requirements.txt
ComfyUI\venv\Scripts\python -c "import torch; print('CUDA available:', torch.cuda.is_available()); torch.zeros(1).cuda(); print('Pascal kernel check passed')"

$ckpt = "ComfyUI\models\checkpoints\v1-5-pruned-emaonly.safetensors"
if (-not (Test-Path $ckpt)) {
  Write-Host "`nStable Diffusion 1.5 is released under the CreativeML OpenRAIL-M licence (https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5)."
  if ((Read-Host "Download the ~4 GB checkpoint and accept that licence? (y/n)") -eq "y") {
    Invoke-WebRequest "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors" -OutFile $ckpt
  } else { Write-Host "Skipped. Put any SD1.5 checkpoint in ComfyUI\models\checkpoints and set image.checkpoint in config\settings.json." }
}
.\.venv\Scripts\python scripts\preflight.py
Write-Host "`nSetup finished. Start everything with start_factory.bat"
