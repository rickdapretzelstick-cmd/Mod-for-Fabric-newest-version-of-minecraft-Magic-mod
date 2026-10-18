# AI Video Factory — local YouTube Shorts production system

A local, no-paid-API pipeline that turns an idea into a 9:16 1080×1920 / 30 fps / H.264 + AAC Short, with
**mandatory human approval before any upload**. n8n orchestrates; a local web dashboard handles approval.

```
ideas → script → storyboard → characters → visuals → voiceover → animation → subtitles → sound
      → assembly → QC → metadata → thumbnail → [HUMAN APPROVAL] → YouTube (private) → analytics
```
(Voiceover runs before animation because scene length is driven by narration length.)

## Honest status — read this first

This was built and tested in a **Linux sandbox with no GPU**, not on your Windows PC. Nothing was run on your RTX 5070.

| Area | Status |
|---|---|
| Full pipeline → valid 1080×1920 MP4 with Piper narration, synthesised music/SFX, burned captions | **Tested** (Linux, CPU, ~3.5 min/video at `draft` quality) |
| Technical QC (resolution, codec, fps, duration, audio, clipping, freeze/black, subtitles, corruption, duplicates) | **Tested**, incl. failing videos being caught |
| Approve / Revise / Reject, persistent in SQLite; rejected/unapproved/modified/duplicate videos cannot publish | **Tested** (pytest + live API) |
| Per-scene revision re-renders only the changed scene | **Tested** |
| Restart recovery (kill -9 server mid-job; job resumes, approvals intact) | **Tested** |
| Job timeouts, retry limits, failure recording | **Tested** (retry limit); timeout path written, not separately exercised |
| Orphaned-subprocess cleanup after a hard crash | Written, **not exercised** |
| n8n workflows A–D import and execute against the live server | **Tested** with n8n 1.68 (A, B, D executed; C imported) |
| React/TypeScript dashboard builds, is served on localhost, and the Reject button works from the real UI (Chromium, no JS errors) | **Tested**. In-browser *video playback* not verified (the sandbox Chromium has no H.264 decoder; Chrome/Edge on Windows do). Approve/Revise buttons were exercised via the API, not clicked |
| Known cosmetic issue | Thumbnail frame can include burned-in caption text; template titles read awkwardly |
| **Ollama LLM** (idea/script quality) | **Untested** — code path written; fallback is a formulaic template writer |
| **ComfyUI / Stable Diffusion 1.5 images** | **Untested** — workflow graph written, never executed |
| Windows scripts (`setup_windows.ps1`, `start_factory.bat`) | **Untested** |
| **YouTube upload** | Tested only with a mock uploader up to the API boundary; **real upload untested** (needs your OAuth) |
| `containsSyntheticMedia` upload flag | Included per YouTube API docs; unverified against the live API |
| Analytics | Views/likes/comments via Data API (written, untested). Retention needs the YouTube Analytics API — not implemented |

### What it is *not*
* **Visual quality is not cinematic when ComfyUI is unavailable.** The fallback painter produces flat, stylised
  silhouette scenes with depth-layer parallax. It keeps the pipeline working; it will not hold viewers. Real quality
  depends on SD 1.5 via ComfyUI (untested) — and even then it is camera moves over stills, not video diffusion.
* **No text-to-video diffusion** (AnimateDiff/SVD) is integrated. On a 12 GB card it is not integrated here yet, so animation = parallax camera moves, vignette, grain, transitions, ducked music, SFX.
* **Character consistency** = fixed seed per character + a fixed prompt prefix + registered colours + saved reference
  images. IP-Adapter/ControlNet reference conditioning is *not* implemented, so faces may drift with diffusion images.
* **Automated QC ≠ creative quality.** Every QC report says creative review is *not assessed*. You judge the video.
* The template idea/script fallback repeats structures. Idea "scores" are a transparent heuristic, not audience prediction.
* Earning ad revenue is not guaranteed; YouTube Partner Program thresholds apply and repetitive/low-effort AI content
  can be demonetised. The system only supports the legitimate parts: originality, disclosure, no fake engagement.

## Cost
No paid APIs, no subscriptions. Ongoing cost is electricity (dashboard shows a per-video estimate from `config` watts × time)
and ~15 GB disk for models. The YouTube Data API is free within its daily quota.

## Setup (Windows, your PC)
1. `powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1` — installs Python, FFmpeg, Node, Git, Ollama via
   winget; creates `.venv`; installs Piper + voice; pulls `qwen2.5:7b-instruct-q4_K_M`; builds the dashboard; installs n8n
   (npm, no Docker); installs ComfyUI with CUDA 12.8 PyTorch wheels (required for RTX 50-series) and runs a GPU kernel check; asks before
   downloading the SD 1.5 checkpoint (OpenRAIL-M licence acceptance).
2. `python scripts\preflight.py` — shows what is/isn't working.
3. `start_factory.bat` — starts ComfyUI, the factory (http://127.0.0.1:8765) and n8n (http://127.0.0.1:5678).
4. In n8n, open workflows **A–D**, set them Active when you want automation (they import inactive).

Linux/macOS: `pip install -r requirements.txt piper-tts`, `cd dashboard && npm i && npm run build`, `./start_factory.sh`.

### GPU notes (RTX 5070, 12 GB — untested, written from specs)
Blackwell (sm_120) needs PyTorch built for CUDA 12.8+; the setup script uses the cu128 wheels and runs a kernel check — if it
fails, update the NVIDIA driver and PyTorch. FP16/BF16 are fast on this card, so SDXL (set `image.checkpoint` to an SDXL
checkpoint and `gen_w/gen_h` to 768/1344) should fit in 12 GB, and small video models (e.g. LTX-Video, Wan 2.1 1.3B in ComfyUI)
may be feasible — **not integrated or tested**. The default stays SD 1.5 at 512x768 because it is the safest first run.
Only one heavy model is resident at a time: Ollama uses `keep_alive: 0`, ComfyUI is told to `/free` after the visuals stage,
and each stage runs in its own subprocess.

### YouTube authorisation (one-time, never your password)
1. Google Cloud Console → create project → enable **YouTube Data API v3** → OAuth consent screen (External, add yourself as test user)
   → Credentials → **OAuth client ID → Desktop app** → download JSON to `secrets/client_secret.json`.
2. `python scripts/youtube_auth.py` — Google's own consent page opens; token is saved to `secrets/youtube_token.json` (git-ignored).
3. Note: uploads from unverified API projects are locked to **private** by YouTube until the project passes audit.
   The system uploads private by default and refuses "public" approvals unless `publish.allow_public` is enabled.

## Operation
* **Dashboard tabs:** Queue (live stage progress, retry), Review (preview, thumbnail, title/description, runtime, generation time,
  errors, est. cost, QC checks, scene list, Approve/Revise/Reject), Library, Ideas, Characters, Settings (quality, retries,
  timeouts, disk guard), System (CPU/RAM/disk/GPU, error log), Publishing history, Analytics. Header: worker Start/Stop.
  Everything shown comes from the API/database; a failed API call shows "API unreachable" rather than stale data.
* **Quality presets:** `draft` renders 540×960 and **upscales** to 1080×1920 (the review page says so); `final` renders natively.
* **Approval model:** `approval_status` defaults to `pending`; publishing requires a latest `approved` row whose SHA-256 equals the
  file being uploaded. Revising or changing the file voids approval. The n8n token is refused by approve/reject/revise endpoints.
* **Revisions:** scenes (re-rolls seed / new prompt), narration, captions, or metadata. Only affected stages re-run; cached scenes are reused.
* **Retry:** a failed stage retries up to `jobs.max_attempts`; use Queue → "Retry failed stage" to resume without regenerating finished stages.
* **CLI:** `python -m factory ideas -n 5`, `new`, `run <pid>`, `stage <pid> <stage>`.
* **n8n:** A plans (generate → score → dedupe → pick top → create project → script → storyboard). B produces (12 stage nodes
  with retry-on-fail, then finalise to the approval queue). C posts approval reminders. D publishes only approved, not-yet-uploaded
  projects (server re-verifies everything). The shared secret is `secrets/automation_token` (exported as `FACTORY_TOKEN`).

## Layout
`factory/` code · `config/` settings (`settings.default.json`; your overrides in `settings.json`) · `secrets/` (git-ignored) ·
`data/` (git-ignored: `factory.db`, `projects/<id>/`, `characters/`, logs) · `dashboard/` · `n8n/` (`build_workflows.py` regenerates the JSON) ·
`models/` · `scripts/` · `tests/` (`python -m pytest tests` — takes ~4 min because it renders dummy videos).

## Maintenance
* Back up `data/` (database + all projects) and `secrets/`. Cleanup only removes stale files in `data/tmp`; it never touches projects or finals.
* Disk guard refuses new stages below `jobs.min_free_disk_gb`.
* Logs: `data/logs/job_<id>.log`; errors also in the DB and the System tab.
* Switching quality or models: Settings tab or `config/settings.json`.
