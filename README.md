# Workforce Data Explorer

One interface for 200+ US workforce and labor market data sources — BLS, FRED,
Census, O*NET, DOL, and SEC EDGAR — with two front doors:

- **A Streamlit dashboard** for browsing, charting, and downloading the data
- **An MCP server** that plugs the same data into Claude, ChatGPT, or any other
  MCP-capable AI assistant, so you can just *ask* — "how have quits rates
  changed since 2022?" — and get answers backed by live government data

## What's inside

| Source | What you get |
|---|---|
| **FRED** | 816,000+ time series — unemployment, job openings, quits, wages, participation, claims, CPI, GDP |
| **BLS** | CES payrolls, CPS household survey, JOLTS, Employment Cost Index, productivity, OEWS occupation wages |
| **Census** | ACS demographics/income/commuting by state & county, QWI hires/separations, County Business Patterns |
| **O*NET** | 900+ occupation profiles — skills, tasks, abilities, technology used |
| **DOL** | Weekly UI claims, OSHA inspections, wage & hour enforcement (free API key required for enforcement data) |
| **SEC EDGAR** | Layoff 8-Ks, human capital disclosures from 10-Ks, filings by company |

Fetched data is cached locally (DuckDB) with sensible TTLs per release frequency,
so repeat queries don't burn API calls.

## Quick start — dashboard

```bash
git clone <this-repo>
cd workforce-data
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your free API keys (see below)
streamlit run app.py
```

The app runs without any keys — SEC, O*NET, and parts of BLS/Census work
keyless — but FRED (which powers most time series) and the AI Assistant
chat need free keys.

### API keys (all free, ~5 minutes total)

| Key | Powers | Get it at |
|---|---|---|
| `FRED_API_KEY` | Most time series | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `BLS_API_KEY` | Higher BLS rate limits | [data.bls.gov](https://data.bls.gov/registrationEngine/) |
| `CENSUS_API_KEY` | ACS / QWI / CBP queries | [api.census.gov](https://api.census.gov/data/key_signup.html) |
| `GROQ_API_KEY` | In-app AI Assistant chat | [console.groq.com](https://console.groq.com) |
| `DOL_API_KEY` | OSHA / WHD enforcement data | [dataportal.dol.gov](https://dataportal.dol.gov) |
| `ONET_API_KEY` | Optional — higher O*NET limits | [services.onetcenter.org](https://services.onetcenter.org/) |

## Quick start — MCP server (use it from Claude)

The MCP server exposes 11 tools over the same connectors: FRED series,
BLS series, occupation wages, Census ACS, O*NET occupations, UI claims,
and SEC layoff/company filings.

**Claude Desktop** — add to `claude_desktop_config.json`:

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

**Remote (claude.ai custom connectors, ChatGPT, etc.)** — serve over
streamable HTTP and point clients at `https://your-host/mcp`:

```bash
python mcp_server.py --http   # binds 0.0.0.0:$PORT (default 8080)
```

A `render.yaml` is included for one-click deployment on
[Render](https://render.com); any host that runs a Python process works
(Fly.io, Railway, a VPS). Set your API keys as environment variables on
the host.

## Architecture

```
app.py                    Streamlit dashboard (8 pages)
mcp_server.py             MCP server (stdio + streamable HTTP)
workforce_data/
  catalog.py              Searchable metadata for 200+ sources
  client.py               Unified get(source_id) dispatcher
  cache.py                DuckDB response cache with per-frequency TTLs
  chat.py                 Tool-calling chat engine (Groq) + shared tool layer
  sources/
    fred.py bls.py census.py onet.py dol.py sec.py
```

## License

MIT — see [LICENSE](LICENSE).
