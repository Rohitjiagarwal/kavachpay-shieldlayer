# Deploying the live demo (free, on Hugging Face Spaces)

One Docker container serves the API **and** the dashboard on port 7860. Because
ShieldLayer runs a 3-layer zero-judge pipeline (no heavy local classifier weights
required), the free "CPU basic" Space (2 vCPU, 16 GB RAM) fits the app and
FastEmbed RAG index easily.

## How the cost stays at zero

| Guard | Where | What happens when it trips |
|---|---|---|
| **Gemini key from a project with billing disabled** | Google AI Studio | Google returns 429. You can never be charged. |
| 4 requests per visitor (`DEMO_REQUEST_LIMIT`) | `app/quota.py` | Chat becomes read-only. The visitor is offered the recorded demos or their own key. |
| 12 per network address (`DEMO_IP_LIMIT`) | `app/quota.py` | Stops cookie-clearing loops. Kept above 4 so a shared office still works. |
| 250 per day, whole site (`DEMO_DAILY_LIMIT`) | `app/quota.py` | The hard ceiling on your free quota. Resets at midnight UTC. |
| Uploads ≤ 2 MB | Dockerfile env | Prevents oversized document scans in public demo mode. |
| Attack lab without a key | `app/main.py` | Rate-limited (20/min) instead of consuming chat quota. |

What counts as a request: each chat message and each upload. Confirm taps,
page loads, recorded demos and the console don't count. Visitors who add their
own key aren't counted. Their key is used for that request only, and is never
stored or logged.

## Steps

### 1. A Gemini key that can't be billed (optional)
1. Go to <https://aistudio.google.com/apikey> → **Create API key** → *in a new project*.
2. Don't attach a billing account to that project.
3. Keep the key for step 3. Never commit it.

### 2. Push the repo to GitHub (public)
The Space builds from it, so it must be public.

### 3. Create the Space
1. <https://huggingface.co/new-space>: name `kavachpay`, SDK **Docker**, template *Blank*, hardware *CPU basic (free)*.
2. Upload the two files from [`deploy/huggingface/`](../deploy/huggingface/): `Dockerfile` and `README.md`.
3. In **Settings → Variables and secrets**, add:

   | Type | Name | Value |
   |---|---|---|
   | Secret | `GEMINI_API_KEY` | the key from step 1 (optional) |
   | Secret | `SESSION_SECRET` | a long random string |
   | Secret | `ADMIN_TOKEN` | a long random string |
   | Variable | `GITHUB_REPO` | `<you>/kavachpay` |

4. The build starts by itself. Once the status shows *Running*, the app is at
   `https://<you>-kavachpay.hf.space`.

To ship a new commit, use **Settings → Factory rebuild**. The Dockerfile clones
the newest commit on `main`.

## Tuning

Set these as Space **variables**. They override the Dockerfile defaults.

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_REQUEST_LIMIT` | 4 | free requests per visitor |
| `DEMO_IP_LIMIT` | 12 | per network address |
| `DEMO_DAILY_LIMIT` | 250 | whole site per UTC day |
| `GEMINI_CHAT_MODEL` | `gemini-flash-lite-latest` | chat model (also used for visitor keys) |
| `LAYER2_PROVIDER` | `auto` | Layer 2 intent extractor (`auto` \| `gemini` \| `ollama` \| `heuristic`) |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Layer 2 primary Gemini extractor |
| `DEMO_RESET_MINUTES` | 20 | reseed the shared demo account after this much idle time |

Counters live in memory, so a Space restart resets them, along with the demo
data.

## Updating the recorded demos

```bash
python scripts/record_demos.py          # local Ollama chat + heuristic Layer 2; never calls Gemini
```
This rewrites `dashboard/lib/demo-recordings.json`. Commit it and rebuild the Space.
