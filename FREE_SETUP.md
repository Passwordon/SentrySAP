# Free setup (no money, no credit card)

SentrySAP needs two AI parts. Both can be free:

| Part | Free choice | Needs |
|------|-------------|-------|
| Chat model (answers, alert cards) | **Groq** free tier (recommended), or Ollama (offline), or Gemini free tier | Free account / key |
| Embeddings (search over your documents) | **Local** model (all-MiniLM-L6-v2), runs on your PC | Nothing (~90 MB download once) |

## Steps (Groq)
1. Go to https://console.groq.com/keys, sign up (email or Google), click **Create API Key**, copy the key (starts with `gsk_`).
2. In the project folder: `cp .env.example .env` (Windows: `copy .env.example .env`).
3. Open `.env`, replace `gsk_paste_your_groq_key_here` with your key. Keep the other lines as they are.
4. Install and run:
   ```
   pip install -r requirements.txt
   python seed.py --reset-kb
   streamlit run app.py
   ```
   The first `seed.py` downloads the local embedding model (~90 MB, needs internet once).

## If something goes wrong
- **Rate limit message**: free tiers allow only a few requests per minute. Wait 60 seconds and retry, or set `LLM_MODEL=llama-3.1-8b-instant`.
- **Model not found**: Groq occasionally renames models. Open https://console.groq.com/docs/models, copy a current model id into `LLM_MODEL`.
- **Fully offline option**: install Ollama (ollama.com), run `ollama pull llama3.2`, then use the Ollama lines in `.env.example`. Needs about 8 GB RAM.
- **Ask says "I don't have this in your documents" too often**: lower `RELEVANCE_THRESHOLD` (e.g. 0.20) in `.env`. Local embeddings score a little differently from OpenAI's.
