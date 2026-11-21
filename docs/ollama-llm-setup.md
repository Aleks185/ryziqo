# Tutorial: Ollama + local LLM environment for running and testing #InvestWatch

This guide takes you from a clean machine to a measured benchmark of the AI detection layer
(rules vs. local LLM). Everything runs on-premise — no paid APIs, no data leaves the machine.

Time needed: ~20 min setup (+ model download) and ~30–45 min for the full benchmark on a GPU.

---

## 1. Choose the machine and model

Ollama accelerates on **NVIDIA GPUs** (CUDA) and Apple Silicon. Intel integrated graphics
(e.g. UHD 620) are not used — such machines run on the CPU only.

| Hardware | Model | Approx. time per LLM call | Full benchmark (156 calls) |
|---|---|---|---|
| NVIDIA GPU, 6 GB VRAM (e.g. RTX 3050) | `gemma3:4b` | ~10–15 s | ~30–45 min |
| NVIDIA GPU, 6 GB VRAM — comparison run | `qwen2.5:7b` | ~15–25 s | ~45–60 min |
| CPU only (4-core laptop, 16–32 GB RAM) | `gemma3:4b` | ~2 min | ~5 h |

Rules of thumb:
- The model must fit **entirely in VRAM**; a model split between GPU and CPU is several times slower.
  In 6 GB: `gemma3:4b` (~3.3 GB) fits easily, `qwen2.5:7b` (~4.7 GB) fits tightly, `gemma3:12b` (~8 GB) does not.
- `gemma3:4b` is the project default (`OLLAMA_MODEL`) and also supports images (VLM screenshot analysis).
- `nomic-embed-text` (~270 MB) is always needed for embeddings (RAG few-shot, campaign-clone detection).

Times above are estimates; measure your own with step 6.

---

## 2. Install the NVIDIA driver (GPU machines only)

1. Install the current **NVIDIA Game Ready / Studio driver** for your GPU (GeForce Experience or nvidia.com).
   A separate CUDA Toolkit is **not** needed — Ollama bundles its own runtime.
2. Verify:
   ```powershell
   nvidia-smi
   ```
   You should see the GPU name, driver version and free memory (e.g. `6144MiB`).

On laptops: plug in the charger and set Windows power mode to *Best performance* — on battery the GPU/CPU throttles hard.

---

## 3. Install Ollama

**Windows** (either option):
```powershell
winget install Ollama.Ollama
```
or download the installer from https://ollama.com/download. Ollama starts as a tray app and a background
service listening on `http://localhost:11434`.

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**macOS:** download the app from https://ollama.com/download.

Verify (open a **new** terminal so `PATH` is refreshed):
```powershell
ollama --version          # structured outputs (JSON Schema) need >= 0.5; Docker profile pins 0.12.6
curl http://localhost:11434/api/tags
```
`/api/tags` returns `{"models":[]}` until you pull a model.

---

## 4. Download the models

```powershell
ollama pull gemma3:4b
ollama pull nomic-embed-text
# optional second model for comparison (GPU with >= 6 GB VRAM)
ollama pull qwen2.5:7b
```

Smoke test (the first call loads the model, so it is slower):
```powershell
ollama run gemma3:4b "Odpowiedz jednym zdaniem: czym jest kontrakt CFD?"
```

Confirm the model runs on the GPU — in a second terminal while a prompt is being answered:
```powershell
ollama ps
```
The `PROCESSOR` column must say **`100% GPU`**. If you see something like `35%/65% CPU/GPU`, the model
does not fit in VRAM — lower the context window (`OLLAMA_NUM_CTX=4096`, step 5) or use a smaller model.

---

## 5. Set up the backend and configuration

Requires Python 3.12+ and Git.

```powershell
git clone <repo-url> inwestwatch
cd inwestwatch
copy .env.example .env          # Linux/macOS: cp .env.example .env

cd backend
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
```

Edit the root `.env` (the backend reads `.env` from the current directory and `../.env`).
The AI-related settings and recommended values:

```ini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_EMBED_MODEL=nomic-embed-text

# GPU: 120 is plenty. CPU-only: use 300 — a timed-out call silently falls back to rules only
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_NUM_PREDICT=1024
# Lower to 4096 if `ollama ps` shows a CPU/GPU split
OLLAMA_NUM_CTX=4096

# Screenshot analysis needs Playwright (step 8); keep off for the first runs
OLLAMA_VISION_ENABLED=false

AI_PROMPT_CONTENT_CHARS=9000
AI_RAG_FEW_SHOT_ENABLED=true
AI_STRICT_QUOTE_VERIFICATION=true
```

Do **not** increase `OLLAMA_NUM_PARALLEL` above 1 on a 6 GB GPU or a 4-core CPU: every parallel slot needs extra
memory and the calls only get slower.

---

Set the Ollama server environment to `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_MAX_QUEUE=8`. Restart the native server after changing its environment. The Compose AI profile supplies these variables directly. INVESTWATCH requests a one-minute keep-alive.

## 6. Run the tests and the benchmark

### 6.1 Unit tests (no Ollama needed)
```powershell
cd backend
pytest -q
```
All tests mock the LLM, so they pass with or without Ollama. Playwright tests are skipped unless
Playwright is installed.

### 6.2 Benchmark: rules vs. LLM
```powershell
python -m scripts.evaluate_detection --mode both --json-out ../data/eval_report_gemma3-4b.json
```
- `--mode fallback` — rules only (seconds), `--mode ollama` — LLM only, `--mode both` — both, for comparison.
- `--threshold 0.5` — evaluate at a different alert threshold (default: `HIGH_RISK_ALERT_THRESHOLD`, 0.65).
- If Ollama is unreachable, the script prints a notice and skips the `ollama` run.

To compare models, change `OLLAMA_MODEL` in `.env` and run again with a different report name:
```powershell
# .env: OLLAMA_MODEL=qwen2.5:7b
python -m scripts.evaluate_detection --mode ollama --json-out ../data/eval_report_qwen2.5-7b.json
```

### 6.3 Reading the results
The script prints Precision / Recall / F1 overall, per module and per category, then the list of errors:

```
=== ollama (gemma3:4b) (threshold 0.65, 52 cases, avg 12.4s/case) ===
subset             n   TP   FP   TN   FN       P       R      F1
overall           52  ...
adversarial       14  ...
hard_negative     18  ...
Błędy:
  FN adv-m1-slang   score=0.410 [adversarial] rules=[]
```

What to look at:
| Signal | Meaning |
|---|---|
| **Recall on `adversarial`** (rules-only baseline: 8/14) | Does the LLM catch paraphrases, slang and indirect claims? |
| **FP on `hard_negative`** (baseline: 1/18) | Does the LLM correctly *lower* educational / warning content? It must not add false alarms. |
| `[AI-Guard]` entries in the JSON report (`evidence_quotes`) | The model invented quotes that are not in the text; many of them = model too weak. |
| `avg …s/case` | Real latency for your hardware (×3 modules per page). |

Rules-only baseline on this dataset: **F1 0.793** (P 0.958, R 0.676) at threshold 0.65.

---

## 7. Run the application against the live model

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

Check that the backend sees the model:
```powershell
curl http://localhost:8000/api/v1/health
```
Expect `"ollama_available": true` and `"mode": "live"`. (`"demo_fallback"` = Ollama not reachable.)

Analyze a sample text:
```powershell
curl -X POST http://localhost:8000/api/v1/analyze/text `
  -H "Content-Type: application/json" `
  -d '{\"content\": \"Ziomki, w miesiąc z tysiaka zrobiłem trzy, kasa sama wpada. Podeślę swój numerek do rejestracji, extra hajs na start.\", \"module_ids\": [1]}'
```
(Linux/macOS: replace the backticks with `\` and use plain `"` inside single quotes.)

In the response, `model_used` should read `gemma3:4b + uknf-m1-rules`, `is_demo_fallback` should be `false`,
and `evidence_quotes` should contain verbatim quotes plus an `[AI] …` summary.

The frontend (`cd frontend && yarn install && yarn start`) works unchanged — see the README.

---

## 8. Optional: screenshot (VLM) analysis

Needs Playwright with Chromium and a vision model (`gemma3:4b` qualifies):
```powershell
cd backend
pip install -r requirements-playwright.txt
playwright install chromium
```
Then in `.env`:
```ini
OLLAMA_VISION_ENABLED=true
CRAWLER_USE_PLAYWRIGHT_FALLBACK=true
```
Analyze a public URL with `"use_playwright": true` (`POST /api/v1/analyze/url`). Screenshots are stored in
`data/object_store/<hash>_desktop.jpg` / `_mobile.jpg`; VLM findings appear as `[VLM]` quotes and
`AI_VLM_*` rules. Expect an extra ~10–30 s per page on a GPU.

---

## 9. Optional: Ollama on another machine in the LAN

To keep coding on one laptop and run the model on the GPU laptop:

1. On the GPU laptop, make Ollama listen on all interfaces and restart it (quit from the tray, start again):
   ```powershell
   setx OLLAMA_HOST 0.0.0.0
   ```
   Allow inbound TCP 11434 in Windows Defender Firewall for the **Private** network profile only.
2. On the development laptop set `OLLAMA_BASE_URL=http://<gpu-laptop-ip>:11434` in `.env`.

⚠️ The Ollama API has **no authentication** — anyone on the network can use it. Do this only on a trusted
home network, never on public Wi-Fi, and revert with `setx OLLAMA_HOST 127.0.0.1` afterwards.

Docker users: the backend container already points at the host via `http://host.docker.internal:11434`
(`docker-compose.yml`); the `ai` profile can run Ollama in a container instead (`docker compose --profile ai up`).

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/api/v1/health` → `"mode": "demo_fallback"` | Ollama not running or wrong `OLLAMA_BASE_URL`. Check `curl http://localhost:11434/api/tags`. |
| Benchmark `ollama` results equal to `fallback` | Calls time out (fallback is silent). Raise `OLLAMA_TIMEOUT_SECONDS`, check the backend log for `Błąd inferencji Ollama`. |
| `ollama ps` shows CPU/GPU split | Model + context do not fit in VRAM: `OLLAMA_NUM_CTX=4096`, close other GPU apps, or use a smaller model. |
| `nvidia-smi` works but Ollama uses the CPU | Update the NVIDIA driver, restart Ollama; on hybrid laptops set *High-performance NVIDIA processor* for `ollama.exe` in NVIDIA Control Panel. |
| Log: `Ollama odrzuciła JSON Schema w polu 'format'` | Ollama older than 0.5 — upgrade (`winget upgrade Ollama.Ollama`); the backend falls back to plain JSON mode meanwhile. |
| `model "gemma3:4b" not found` | Run `ollama pull gemma3:4b`; the backend auto-picks another installed model family if the exact tag is missing. |
| Very slow first call | Model loading; Ollama unloads idle models after 5 min. Set `OLLAMA_KEEP_ALIVE=30m` (environment variable for Ollama) during benchmarks. |
| Many `[AI-Guard]` rejections | The model paraphrases instead of quoting. Try `qwen2.5:7b`, or keep `AI_STRICT_QUOTE_VERIFICATION=true` (recommended) so invented quotes never add risk. |
