# Isogram

The data truth layer for Arc — USDC gas/flow analytics, TVL tracking, and an
Arc Native Score with an embeddable badge, all served from one public API.
Built for the Arc Mainnet Microgrants program.

Full context: `docs/PRD.md`. Read `docs/architecture_essentials.md` before
touching any code — it has the one correctness rule (USDC decimal handling)
that matters most in this codebase.

## Quick Start

```bash
# 1. Clone and set up environment
cp .env.example .env   # fill in Supabase connection string, bot token, etc.

# 2. Ingestion worker
cd ingestion && pip install -r requirements.txt --break-system-packages
python worker.py

# 3. API
cd api && pip install -r requirements.txt --break-system-packages
uvicorn main:app --reload

# 4. Dashboard
cd dashboard && npm install && npm run dev

# 5. Bot
cd bot && pip install -r requirements.txt --break-system-packages
python bot.py
```

## Commands

| Command | Description |
|---|---|
| `python ingestion/worker.py` | Run one ingestion pass against Arc mainnet |
| `python scoring/compute_scores.py` | Recompute `project_scores` |
| `uvicorn main:app --reload` (in `api/`) | Run the API locally |
| `python -m pytest tests/ -v` (in `ingestion/`, `scoring/`, `api/`) | Run tests |

## Architecture

Arc mainnet RPC → ingestion worker → Postgres (Supabase) → FastAPI →
{dashboard, Telegram bot, badge endpoint}. Full detail in
`docs/ARCHITECTURE.md`; condensed version in `docs/architecture_essentials.md`.

## Docs index

| Doc | Purpose |
|---|---|
| `docs/PRD.md` | What we're building, for whom, and why |
| `docs/ARCHITECTURE.md` | Full system design |
| `docs/architecture_essentials.md` | Condensed reference, read first |
| `docs/SCHEMA.md` | Database schema + scoring formula |
| `docs/IMPLEMENTATION_PLAN.md` | Week-by-week build plan |
| `docs/TESTING.md` | Test strategy |
| `docs/AUDIT.md` | Pre-submission audit checklist |
| `docs/BUGS.md` | Known gotchas + bug log |
| `docs/SCAFFOLD.md` | Repo layout reference |
| `docs/decisions/` | ADRs |
| `AGENTS.md` | Rules for AI agents working in this repo |

## Contributing

Solo hackathon build. See `AGENTS.md` for conventions if you're an agent
picking this up mid-build.
