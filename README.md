# Confam

**Squad Hackathon 3.0 · Challenge #1 — “Proof of Life”**  
*Smart Systems: The Intelligent Economy*

---

## Executive summary

**Confam** is a **WhatsApp-first** market intelligence and payments companion built for **Gen Z and digital merchants in Nigeria**. It turns the chat surface people already live in into a **verifiable economic layer**: crowdsourced stall prices, multimodal AI (text, voice, images), and **Squad-backed** card flows—so buyers can move from *“how much is garri in Mile 12?”* to *“send ₦5k to this account”* without leaving the thread.

This README is structured so judges can **map every section to the hackathon rubric** (Technical Build, AI Layer, Squad API Integration) and **reproduce the stack locally** in under an hour.

---

## 1. Project titles & hackathon alignment

| Field | Detail |
|--------|--------|
| **Product name** | **Confam** |
| **Competition** | Squad Hackathon 3.0 |
| **Challenge** | **Challenge #1 — “Proof of Life”** (AI verification / trust-scoring in high-fraud contexts) |
| **Domain fit** | **Supply chain & open markets** — counterfeit pricing opacity, informal vendor information asymmetry, and unverified payment contexts where buyers lack ground truth. |
| **Core mission** | Reduce **open-market vendor fraud**, **counterfeit / phantom pricing**, and **transaction opacity** by giving young consumers and everyday buyers **crowdsourced, AI-assisted market intelligence** and **payment-grade verification**—delivered primarily through **WhatsApp**, the interface they already use daily. |
| **Why this is “Proof of Life”** | The system continuously **grounds claims in evidence**: structured **price reports** (`price_reports`), **payment-slip OCR**, **bank-account resolution**, and **ML-backed parsing** produce **interpretable outputs** (saved prices, risk-aware payment UI, clarifying prompts)—not a generic chat toy. |

> **Note:** Hackathon materials stress that solutions must show **real AI depth** and **meaningful Squad usage**. Confam implements both in **production-style services** (FastAPI + PostgreSQL + decoupled ML + Squad card lifecycle).

---

## 2. The “four pillars” engagement architecture

Judges score solutions against **AI Automation**, **Use of Data**, **Squad APIs**, and **Financial Innovation**. Here is how **Confam** maps to each pillar.

### AI automation

- **Inbound multimodal WhatsApp traffic** (text, images, voice notes) is **normalized without manual ops**: transcription (Whisper-class APIs), **vision** for product vs payment routing, and **NLU** via a dedicated **ML microservice** (`POST /parse` for queries; optional `POST /process` where enabled).
- **Pre-ML conversational capture** (`submit_price_detector`): rule-based **SUBMIT_PRICE** detection runs **before** the ML layer so **price submissions are not lost** when intent classification is wrong—aligned with **robust verification under messy real-world input** (an edge-case requirement in the challenge brief).

### Use of data

- **Crowdsourced market submissions** persist to PostgreSQL (`price_reports`, with `extracted_by`: `ml` | `submit_price_rules` | `hybrid` | `image_context`) enabling **aggregation** (averages, min/max, recency) for **QUERY** replies.
- **Behavioral & session signals**: chat history informs **follow-up price reports** (“got it for 1k” after “how much is yam in Wuse”).
- **WhatsApp identity bridge**: optional `users.phone_e164` links **E.164** identities from Meta to authenticated Confam accounts after **email + password** onboarding (`whatsapp_sessions`, `add_whatsapp_auth.sql`).

### Squad APIs

- **Card tokenization & verification**: Squad **inline checkout** for a **minimum ₦100 authorization** (10,000 kobo—Squad’s floor), then **full refund** via `POST /transaction/refund`, with **`authorization_token`** stored on `connected_cards` for **later charges**—see [§3 Squad API integration](#3-squad-api-integration-deep-dive-crucial-for-judges).
- **Customer-initiated sends**: **saved-card charges** through Squad’s **`/transaction/charge_card`** path orchestrated from chat confirmations (`payment_execution_service` + `squad_card_service`).

### Financial innovation

- **Micro-verification billing**: **₦100 verify-and-refund** pattern satisfies minimums while keeping **user friction low** and **PCI scope** sane (no raw PAN on Confam servers—Squad hosted checkout).
- **In-chat monetization path**: premium / high-trust flows can extend the same **token + micro-charge** pattern for **recurring or one-tap** intelligence unlocks **inside WhatsApp** (checkout URL surfaced in-app today; WhatsApp deep-link or in-chat card UX is a thin product layer on the same backend).

---

## 3. Squad API integration (deep dive — crucial for judges)

**Disqualification guardrail (from the hackathon guide):** solutions without **meaningful Squad integration** are not eligible for top placement. Confam’s Squad usage is **functional**, **documented**, and **wired into core user journeys**.

### Feature: card tokenization & seamless verification

| Step | What happens | Squad touchpoints |
|------|----------------|-------------------|
| 1 | User starts **“connect card”** from the Confam client. | Backend builds an **initiate transaction** payload (card channel only) via `squad_service.transaction_initiate_card_link_body`. |
| 2 | Confam receives a **checkout URL** from Squad. | `POST` to Squad **transaction initiate** (`squad_card_service.initiate_card_verification_checkout`). |
| 3 | User completes payment on **Squad-hosted** checkout. | Squad captures **₦100** (minimum allowed); Confam never handles raw card numbers. |
| 4 | Confam **verifies** the transaction. | `GET /transaction/verify/{transaction_ref}` (with fallback query form) — `squad_card_service._verify_transaction_get`. |
| 5 | **Refund** the verification hold. | `POST /transaction/refund` with `gateway_transaction_ref` + `transaction_ref` (`refund_full_transaction`). |
| 6 | **Persist token** for future charges. | Authorization material extracted from verify payload shards → stored on **`ConnectedCard.authorization_token`** (see `verify_transaction_dict_shards` / finalize paths in `squad_card_service.py`). |
| 7 | **One-tap style sends** (chat / WhatsApp). | `charge_saved_card` → Squad **`/transaction/charge_card`** with saved token + kobo amount (`payment_execution_service.execute_confirmed_send`). |

### Purpose (judge narrative)

- **Compliance-first**: verification uses **Squad’s** hosted card capture and **server-to-server** verify/refund/charge APIs (`Bearer` **secret key** only on the backend—**never** in the Next.js bundle).
- **WhatsApp-native UX goal**: the **same token** powers **micro-billing** and **send-money** without forcing users through a separate banking app for every stall interaction—**checkout once**, **chat many times**.

> **⚠️ Secrets warning**  
> Store **`SQUAD_SECRET_KEY`**, **`SQUAD_PUBLIC_KEY`**, **`SQUAD_MERCHANT_ID`**, and **`SQUAD_API_BASE`** only in **`Backend/.env`**. This repository **`.gitignore`** excludes `.env` and sensitive paths—**never commit keys** or Supabase service roles.

---

## 4. Ecosystem architecture & ML interface

```text
┌─────────────────┐     HTTPS       ┌──────────────────────┐
│  Next.js PWA    │ ◄──────────────►│  FastAPI (Confam)    │
│  `Frontend/`    │   JWT + REST    │  `Backend/`          │
└─────────────────┘                 └──────────┬───────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
           ┌────────────────┐          ┌────────────────┐         ┌───────────────┐
           │ Supabase       │          │ OpenAI / Groq  │         │ Meta WhatsApp │
           │ Postgres +     │          │ + OpenRouter   │         │ Cloud API     │
           │ Object Storage │          │ (vision / NLP)│         │ (webhook)     │
           └────────────────┘          └────────────────┘         └───────────────┘
                                               │
                                               │  HTTP JSON
                                               ▼
                                    ┌──────────────────────┐
                                    │ ML microservice      │
                                    │ (NEUROPAY-GTCO)      │
                                    │ `/parse`, `/process`│
                                    └──────────────────────┘
```

### Backend (`Backend/`)

- **FastAPI** application entry: `Backend/main.py` (CORS, routers, lifespan hooks including **WhatsApp `subscribed_apps`** where configured).
- **Persistence**: **SQLAlchemy** + **PostgreSQL** (production-oriented; Supabase-compatible URL with **`sslmode=require`** auto-append for Supabase hosts in `config.py`).
- **Identity for WhatsApp**: `users.phone_e164` (nullable, unique when set) links WhatsApp E.164 to the authenticated user after login—see migration `Backend/database/migrations/add_whatsapp_cloud.sql`.

### Intelligence layer (decoupled)

- Market NLU / pricing logic lives in a **separate repository**: **[NEUROPAY-GTCO](https://github.com/keneijeh760-ship-it/NEUROPAY-GTCO)** (`median/api.py` — FastAPI with **`POST /parse`**, **`POST /process`**, **`GET /health`**).
- Confam reaches it via **`ML_API_URL`** (default `http://127.0.0.1:8001` in `Backend/config.py`) so the **core API and ML service scale and deploy independently**.

### Frontend (`Frontend/`)

- **Next.js** PWA: auth, **`/chat`** multimodal assistant, card connect flows calling Confam’s integrations API.

---

## 5. Judges’ quick reproduction & setup guide

Follow these steps **in order**. Total time depends mostly on **model download** for the ML repo (optional for a thin demo if mock parser is enabled upstream).

### Step 1 — Clone and pull

```bash
git clone <YOUR_CONFAM_REPO_URL> confam
cd confam
git pull
```

If you evaluate the **ML layer** from GitHub:

```bash
git clone https://github.com/keneijeh760-ship-it/NEUROPAY-GTCO.git
cd NEUROPAY-GTCO
# Follow that repo's README for model env vars when not using mocks
```

> This monorepo may list `NEUROPAY-GTCO/` in `.gitignore` when vendored locally—clone the ML repo **adjacent** to Confam if needed.

### Step 2 — Configure environment variables

```bash
cd Backend
cp .env.example .env
```

Edit **`Backend/.env`**. Minimum **shape** (names mirror `.env.example`):

| Group | Variables (examples) |
|--------|----------------------|
| **Core** | `DATABASE_URL`, `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `FRONTEND_ORIGINS`, `BACKEND_PUBLIC_URL` |
| **AI / speech** | `OPENROUTER_API_KEY`, `OPENROUTER_TEXT_MODEL`, `OPENROUTER_VISION_MODEL`, `OPENAI_API_KEY` or `GROQ_API_KEY` (transcription) |
| **Storage** | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET` |
| **Squad** | `SQUAD_SECRET_KEY`, `SQUAD_PUBLIC_KEY`, `SQUAD_API_BASE`, `SQUAD_MERCHANT_ID` |
| **WhatsApp** | `META_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN` (or `META_ACCESS_TOKEN`), `WHATSAPP_PHONE_NUMBER_ID` (or `META_PHONE_NUMBER_ID`), **`WHATSAPP_BUSINESS_ID`**, `META_APP_SECRET`, `WHATSAPP_GRAPH_API_VERSION` |
| **ML** | `ML_API_URL` (e.g. `http://127.0.0.1:8001`), optional `ML_CONFIDENCE_MIN` |

```bash
# Frontend
cd ../Frontend
cp .env.local.example .env.local
# Set NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 (or your deployed API)
```

> **⚠️ Never commit `.env` / `.env.local`** — they are ignored by design. Use **sandbox** Squad keys with `SQUAD_API_BASE=https://sandbox-api-d.squadco.com` for judging.

### Step 3 — Database setup & SQL migrations

1. Ensure **PostgreSQL** is reachable from `DATABASE_URL`.
2. Apply SQL migrations (from repo root or `Backend/`), e.g. with `psql`:

```bash
psql "$DATABASE_URL" -f Backend/database/migrations/add_whatsapp_cloud.sql
psql "$DATABASE_URL" -f Backend/database/migrations/add_whatsapp_auth.sql
psql "$DATABASE_URL" -f Backend/database/migrations/add_price_reports.sql
psql "$DATABASE_URL" -f Backend/database/migrations/add_price_reports_extracted_by.sql
# Plus any other migrations your branch requires under Backend/database/migrations/
```

These include **WhatsApp tables**, **`users.phone_e164`**, and **market `price_reports`** (+ **`extracted_by`** for auditability).

3. Start the API (creates ORM tables where applicable for dev):

```bash
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- Docs: `http://127.0.0.1:8000/docs`  
- Health: `GET /health`

### Step 4 — Spool up the ML layer (parallel process)

Run **on a different port** than Confam (8000 vs 8001):

```powershell
cd NEUROPAY-GTCO
$env:PYTHONPATH="."
# Optional real models (see NEUROPAY-GTCO docs):
# $env:USE_MOCK_PARSER="false"
# $env:INTENT_MODEL_DIR="..."
# $env:NER_MODEL_DIR="..."
uvicorn median.api:app --host 0.0.0.0 --port 8001 --reload
```

Set in **`Backend/.env`**:

```env
ML_API_URL=http://127.0.0.1:8001
```

### Step 5 — Frontend

```bash
cd Frontend
npm install
npm run dev
```

Open the printed localhost URL; **signup → `/chat`**.

### WhatsApp webhook (optional demo lane)

Meta requires **HTTPS**. For local judging, use **ngrok** (or similar) and set the callback to:

```text
https://<your-ngrok-host>/webhook
```

Keep **`META_APP_SECRET`** aligned with Meta **App Secret** for signature verification.

---

## Repository layout

| Path | Role |
|------|------|
| **`Backend/`** | FastAPI, SQLAlchemy models, Squad + WhatsApp + chat services |
| **`Frontend/`** | Next.js PWA (landing, auth, `/chat`) |
| **`NEUROPAY-GTCO/`** | *(Optional sibling clone)* ML FastAPI service |

---

## API surface (high level)

- **`/auth/*`** — JWT signup/login  
- **`/chat/*`** — sessions, text / image / voice / payment messages, uploads  
- **`/webhook`** — WhatsApp Cloud API (GET verify + POST events)  
- **Integrations** — Squad card connect + callback finalize routes (see `Backend/routers/integrations.py`)

---

## Responsible AI & safety

- **False positives** in payment OCR and market parsing are mitigated with **confidence gates**, **clarification prompts**, and **rule-based fallbacks**—documented in code paths (`market_pipeline_service`, `submit_price_detector`).
- **Bias & locality**: models are tuned for **Nigerian markets and language variety**; production deployments should monitor **per-market calibration**.

---

## License & attribution

Built for **Squad Hackathon 3.0 — Challenge #1 (“Proof of Life”)**.  
Squad APIs and trademarks belong to their respective owners. **Confam** is the team’s product name for this submission.

---

*Last updated for hackathon judging: reproducible setup, explicit Squad + ML boundaries, and WhatsApp-first mission alignment.*
