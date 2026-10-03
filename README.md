# 🛡️ SentrySAP

> **The SAP assistant that knows your custom landscape - and acts before you ask.**

SentrySAP has two modes sharing one brain:

| Mode | What it does |
|------|--------------|
| 🧠 **Ask** | Learns your Z/Y transactions, ABAP, SOPs and wiki (RAG) and answers *"how do I do X **here**?"* - or says *"I don't have this in your documents."* |
| ⚡ **Watch** | Monitors (simulated) SAP events, detects problems with YAML rules, drafts actions, and waits for a **human approval** before anything is executed. |

## ⭐ The USP: alerts that carry your company's playbook

When a rule fires, SentrySAP does not just notify. In the same step it **queries the Ask-mode knowledge base**
for the company's own documented procedure and attaches it to the alert card:

```
 🟧 HIGH · Low stock + late delivery: Steel Rod 10mm
 Stock 40 (reorder point 100). PO 4500001 from Bharat Steel is 6 days late.
 ┌ Suggested action ────────────┐  ┌ 📘 Your company's playbook ──────────────────┐
 │ Get Procurement Manager      │  │ Supplier_Delay_Escalation_SOP.pdf · 58%       │
 │ approval, then run ZESCAL01  │  │ "Escalation through ZESCAL01 requires prior   │
 └──────────────────────────────┘  │  approval from the Procurement Manager..."    │
 ✉️ Draft escalation email to supplier ...      └───────────────────────────────────────────────┘
 [✅ Approve & Execute]  [❌ Reject]
```

`python seed.py` generates a *Supplier Delay Escalation SOP* (mentioning custom transaction **ZESCAL01**), two more SOPs,
a Z-transaction wiki and an ABAP snippet, ingests them, and runs a watch cycle - so the proof is on screen on first run.

> 💸 **100% free to run.** Default setup = free Groq chat model (no credit card) + local embeddings on your PC. See [FREE_SETUP.md](FREE_SETUP.md). OpenAI is optional.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then paste your FREE Groq key (see FREE_SETUP.md)
python seed.py
streamlit run app.py
```

Seed options: `--no-docs` (DB only), `--reset-kb` (clear vector store first), `--no-watch` (skip initial cycle).
Optional HTTP API: `uvicorn api:app --reload` (docs at `/docs`).

### 2-minute demo script
1. **Action Queue** → the Steel Rod alert shows the **ZESCAL01 / manager-approval playbook** next to the draft email.
2. Click **Approve & Execute** → PO becomes `ESCALATED`, event resolved → see it in **Audit Log**.
3. **Ask** → *"How do I block a vendor?"* → answers **ZVENDBLK** (not standard XK05), with sources. Then ask *"What is the CEO's salary?"* → *"I don't have this in your documents."*
4. Sidebar → **Inject random SAP event** → **Run watch cycle now** → new alerts appear (the scheduler also runs every 60 s).
5. Edit `rules.yaml` (e.g. change `po.delay_days > 3` to `> 1`) - picked up on the next cycle, no restart.

## Architecture

```
            ┌──────────────────────── Streamlit UI (app.py) ────────────────────────┐
            │  💬 Ask   │  📤 Upload   │  🔔 Action Queue (approve/reject)  │ 📋 Audit │
            └─────┬────────────┬─────────────────────┬────────────────────────┬─────┘
                  │            │                     │                        │
        ┌─────────▼────────────▼──┐        ┌─────────▼────────────────────────▼─────┐
        │ KnowledgeBase           │◀───────│ AlertService (alerts.py)               │
        │ parse→chunk 800/150→    │ playbook│  AlertBuilder: facts + playbook → LLM │
        │ embed→ChromaDB          │  lookup │  approval gate · audit log            │
        │ answer() / find_playbook│         └───────▲──────────────────────┬────────┘
        └──────────▲──────────────┘                 │ findings             │ execute (after approval)
                   │                      ┌─────────┴────────┐     ┌───────▼────────┐
        ┌──────────┴────────┐             │ RuleEngine       │     │                │
        │ llm.py abstraction│             │ rules.yaml (safe │────▶│  FakeSAP       │
        │ (gpt-4o-mini,     │             │ AST evaluation)  │read │  SQLite:       │
        │  embeddings-3-sm) │             └─────────▲────────┘     │  materials,POs,│
        └───────────────────┘                       │              │  suppliers,    │
                                  APScheduler every 60 s           │  events        │
                                  (watcher.py)  ◀── event injector ┘                │
```

| File | Role |
|------|------|
| `sentrysap/llm.py` | `BaseLLM` interface, OpenAI implementation, lazy embeddings, friendly error translation |
| `sentrysap/knowledge.py` | Module 1: ingestion, Chroma, thresholded RAG, `find_playbook()` |
| `sentrysap/fake_sap.py` | Module 2: simulated SAP, event injector, approved-action executors |
| `sentrysap/rules.py` + `rules.yaml` | Module 3: configurable rules |
| `sentrysap/alerts.py` | Alert card builder (**USP**), approval gate, audit log (Module 4) |
| `sentrysap/watcher.py` | APScheduler loop |
| `app.py` / `api.py` | Streamlit UI / optional FastAPI |
| `seed.py`, `sentrysap/sample_docs.py` | Demo data and auto-generated SOP PDFs |

## Design decisions (where the spec was ambiguous)

- **Streamlit calls the service layer directly**, so `streamlit run app.py` is the only process needed. FastAPI (`api.py`) is a thin optional layer over the same services.
- **Relevance threshold** = cosine similarity (Chroma cosine space, `score = 1 − distance`), default `0.25` for Ask and `0.22` for playbooks. These suit `text-embedding-3-small`; **tune in `.env`** if you change models or corpus. A second guard: the prompt tells the model to answer with the exact refusal sentence when context lacks the answer.
- **PO delay** = current `delivery_date` − `original_delivery_date` (extra column on `purchase_orders`). `suppliers` also got a `status` column (ACTIVE/BLOCKED).
- **Rule `when` strings** are parsed with Python's `ast` against a whitelist - YAML cannot run arbitrary code. Three rules ship: delayed supplier, low stock without PO, duplicate supplier.
- **One alert per situation** (`dedupe_key`, unique). A rejected alert is not re-raised for the same PO/material/supplier.
- **ESCALATED POs count as open supply**, so escalating doesn't trigger a bogus "no open PO" alert.
- **Approve & Execute** runs a FakeSAP action (escalate PO / create replenishment PO / block duplicate supplier), resolves the related events, and writes the audit row. In production these become OData/RFC calls.
- **Resilience**: OpenAI auth/rate-limit/network errors become friendly messages (SDK also retries 429/5xx). If the LLM fails while writing a card, a deterministic fallback card is used. If the *playbook lookup* fails, or the knowledge base is empty, alert creation is retried/paused rather than storing an alert permanently without its playbook.
- **Ask mode is stateless** (each question is answered from retrieved documents only, no chat-history leakage into answers).
- Alerts are created one per Finding sequentially: with many simultaneous matches, a cycle makes one LLM call each.

## Screenshots

`![Ask tab](docs/screenshot-ask.png)` · `![Action Queue with playbook](docs/screenshot-queue.png)` ·
`![Upload tab](docs/screenshot-upload.png)` · `![Audit log](docs/screenshot-audit.png)` *(placeholders - add yours)*

## Moving to a real SAP system
Replace `FakeSAP` reads with OData/RFC/IDoc events (e.g. SAP BTP Event Mesh) and the executors with approved BAPI/OData calls; the rule engine, playbook linker, approval gate and audit log stay unchanged.

## Troubleshooting
- *"OPENAI_API_KEY is not set"* → create `.env` (see `.env.example`) and restart Streamlit.
- *Alerts show "No documented procedure"* → lower `PLAYBOOK_THRESHOLD`, or ingest the SOP.
- *Changed embedding model/provider* → `python seed.py --reset-kb` (old vectors are incompatible).
- *"rate limit" on a free tier* → wait a minute, or set `LLM_MODEL=llama-3.1-8b-instant`.
