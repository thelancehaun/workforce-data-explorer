# Workforce Data Explorer

One interface for 89 curated US workforce and labor market data sources — 30
with live API access spanning official statistics (BLS, FRED, Census, O*NET,
DOL, SEC EDGAR) and real-time signals (Indeed Hiring Lab job postings, ADP
payrolls, the Anthropic Economic Index).

**Three ways to use it, easiest first:**

| | What | Where |
|---|---|---|
| 🖥️ | **Live dashboard** — browse, chart, download. Zero setup. | [workforce-data-explorer.streamlit.app](https://workforce-data-explorer.streamlit.app) |
| 🤖 | **AI connector (MCP)** — ask your own Claude or ChatGPT questions answered with live labor data | `https://workforce-data-mcp.onrender.com/mcp` |
| ⚙️ | **Run it yourself** — clone this repo, bring free API keys | [Quick start](#run-it-yourself) below |

## What's inside

| Source | What you get |
|---|---|
| **FRED** | 816,000+ time series — unemployment, job openings, quits, wages, participation, claims, CPI, GDP |
| **BLS** | CES payrolls, CPS household survey, JOLTS, Employment Cost Index, productivity, OEWS occupation wages |
| **Census** | ACS demographics/income/commuting by state & county, QWI hires/separations, County Business Patterns |
| **O*NET** | 900+ occupation profiles — skills, tasks, abilities, technology used |
| **DOL** | Weekly UI claims, OSHA inspections, wage & hour enforcement |
| **SEC EDGAR** | Layoff 8-Ks, human capital disclosures from 10-Ks, filings by company |
| **Indeed Hiring Lab** | Daily job postings indexes (national/state/metro/sector) + AI-postings share |
| **ADP** | Weekly and monthly private payrolls (via FRED) |
| **Anthropic Economic Index** | Real-world AI usage by occupation and task |

---

## 🖥️ The dashboard

**[workforce-data-explorer.streamlit.app](https://workforce-data-explorer.streamlit.app)** — nothing to install.

- **Catalog** — search all 89 curated sources by topic
- **Job Postings** — real-time labor demand from Indeed, incl. AI's share of postings
- **State Labor Markets** — the four headline indicators for any state
- **FRED / BLS / Census / O*NET / DOL / SEC pages** — fetch, chart, and download any series as CSV
- **AI Assistant** — ask questions in plain English ("show me quits vs. openings
  since 2022"). The shared assistant allows a few questions per minute; paste
  your own free [Groq key](https://console.groq.com/keys) into the expander on
  that page for unlimited use.

## 🤖 The AI connector (MCP)

The best experience: plug live labor data into the AI you already use. The
connector exposes 15 tools — FRED and BLS series, occupation wages, Census
ACS, O*NET occupations, UI claims, SEC layoff/company filings, Indeed daily
job postings, AI-postings share, state labor market snapshots, and AI-usage
exposure by occupation — and your AI decides which to call.

**Claude (claude.ai)** — requires a paid plan:

1. Settings → **Connectors** → **Add custom connector**
2. Name: `Workforce Data` — URL: `https://workforce-data-mcp.onrender.com/mcp`
3. In a new chat, ask something like *"What's happening with layoffs at public
   companies this month?"* or *"Compare software developer and nurse wages."*

**ChatGPT** — Settings → Connectors (developer mode) → add the same URL.

**Claude Desktop (runs locally)** — after cloning the repo (see below), add to
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "workforce-data": {
      "command": "/path/to/workforce-data/.venv/bin/python",
      "args": ["/path/to/workforce-data/mcp_server.py"]
    }
  }
}
```

> The hosted connector runs on a free tier that sleeps when idle — the first
> question after a quiet spell takes ~30–60 seconds while it wakes up.

## ⚙️ Run it yourself

Requires **Python 3.10+** (tested on 3.13). All dependencies are in
`requirements.txt`.

```bash
git clone https://github.com/thelancehaun/workforce-data-explorer.git
cd workforce-data-explorer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # then add your free API keys (see below)

streamlit run app.py            # the dashboard
python mcp_server.py            # the MCP server (stdio, for Claude Desktop)
python mcp_server.py --http     # the MCP server (HTTP, for remote hosting)
```

The app runs without any keys — SEC, O*NET, and parts of BLS/Census work
keyless — but FRED (which powers most time series) and the AI Assistant chat
need free ones.

### API keys (all free, ~5 minutes total)

| Key | Powers | Get it at |
|---|---|---|
| `FRED_API_KEY` | Most time series | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `BLS_API_KEY` | Higher BLS rate limits | [data.bls.gov](https://data.bls.gov/registrationEngine/) |
| `CENSUS_API_KEY` | ACS / QWI / CBP queries | [api.census.gov](https://api.census.gov/data/key_signup.html) |
| `GROQ_API_KEY` | In-app AI Assistant chat | [console.groq.com](https://console.groq.com) |
| `DOL_API_KEY` | OSHA / WHD enforcement data | [dataportal.dol.gov](https://dataportal.dol.gov) |
| `ONET_API_KEY` | Optional — higher O*NET limits | [services.onetcenter.org](https://services.onetcenter.org/) |

### Deploy your own copies

- **Dashboard** → [Streamlit Community Cloud](https://share.streamlit.io) (free):
  point it at your fork, paste your keys under app **Settings → Secrets**.
- **MCP server** → [Render](https://render.com) (free): the included
  `render.yaml` configures it — connect your fork as a Blueprint and add your
  keys as environment variables. Any Python host (Fly.io, Railway, a VPS) works
  too: `python mcp_server.py --http`.

## Architecture

```
app.py                    Streamlit dashboard (Overview, AI Assistant, data pages)
ui_theme.py               Shared chart styling (validated palette, light/dark)
mcp_server.py             MCP server (stdio + streamable HTTP, TTL-cached tools)
workforce_data/
  catalog.py              Searchable metadata for 89 curated sources
  chat.py                 Tool-calling chat engine (Groq) + shared tool layer
  sources/
    fred.py bls.py census.py onet.py dol.py sec.py indeed.py aei.py
```

Fetched data is cached in memory in both apps (1 hour for time series, up to a
day for searches and metadata), so repeat queries don't burn API quota.

## Bugs, ideas, and working together

- **Bug or wrong-looking data?**
  [Open an issue](https://github.com/thelancehaun/workforce-data-explorer/issues/new/choose)
  — templates make it quick.
- **Want to suggest a data source?** Same place — there's a template for that.
- **Working together / press:** the contact link is on the app's
  [About page](https://workforce-data-explorer.streamlit.app/settings)
  (kept off GitHub so scrapers don't get it).

## License

MIT — see [LICENSE](LICENSE).
