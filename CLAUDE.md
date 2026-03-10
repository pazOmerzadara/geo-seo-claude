# GEO-SEO Claude Code Skill

## Project Overview
GEO-first SEO analysis toolkit that optimizes websites for AI-powered search engines (ChatGPT, Claude, Perplexity, Gemini, Google AI Overviews) while maintaining traditional SEO foundations.

## Git & PRs

When creating PRs, always ask whether to target `dev`, `main`, or both. Default to `main` unless told otherwise. Use descriptive branch names prefixed with `pazOmerzadara/`.

## Environments

- **Production**: Deployed on Vercel, serves `geo-report-zadara.html` at root via `vercel.json` rewrite
- **Local**: Python scripts run locally, HTML reports open in browser
- Always confirm which environment before deploying changes. Ask if unsure.

## Architecture

```
geo/SKILL.md          — Main skill orchestrator (entry point)
skills/               — 11 specialized sub-skills (geo-audit, geo-citability, etc.)
agents/               — 5 parallel subagents for full audit
scripts/              — Python utilities (fetching, scoring, scanning, PDF generation)
schema/               — JSON-LD templates for structured data
geo-report-zadara.html — Existing interactive HTML report
vercel.json           — Vercel config (rewrites root to report)
```

## Key Conventions

- **GEO-first philosophy**: AI search optimization takes priority over traditional SEO
- **Parallel subagents**: Full audits launch 5 agents simultaneously — do not make them sequential
- **Output files**: Each command generates a specific markdown file (e.g., `GEO-AUDIT-REPORT.md`)
- **Python 3.8+** required; dependencies in `requirements.txt`
- **Quality gates**: Max 50 pages per audit, 30s timeout per fetch, respect robots.txt

## When Making Changes - DO vs DON'T

DO:
1. Stick to the spec scope — if it says "report only", don't refactor the scoring engine
2. Try simple fixes first — check existing patterns before building new abstractions
3. Read the relevant `SKILL.md` before modifying any skill or agent
4. Keep HTML reports self-contained — all CSS/JS inline, no external dependencies
5. Test Python scripts with `python3` directly before integrating

DON'T:
1. Don't modify `geo/SKILL.md` orchestration without understanding the full audit flow
2. Don't make agents sequential when they should run in parallel
3. Don't add external CDN dependencies to HTML reports — they must work offline
4. Don't feature-creep from "fix report styling" to "rewrite the scoring engine"
5. Don't break Python 3.8 compatibility by using newer syntax

## Commands

All commands start with `/geo` followed by a subcommand and URL:
- `/geo audit <url>` — Full audit with parallel subagents
- `/geo quick <url>` — 60-second snapshot
- `/geo report <url>` — Client-ready markdown report
- `/geo report-pdf <url>` — Professional PDF with charts

## Scoring Weights

| Category | Weight |
|----------|--------|
| AI Citability & Visibility | 25% |
| Brand Authority Signals | 20% |
| Content Quality & E-E-A-T | 20% |
| Technical Foundations | 15% |
| Structured Data | 10% |
| Platform Optimization | 10% |

## HTML Report Guidelines

- Reports must be **self-contained single HTML files** with inline CSS and JS
- Must be **responsive** and work on mobile and desktop
- Use modern CSS (flexbox/grid) — no frameworks
- Charts and visualizations should use inline SVG or canvas, not external libraries
- Color scheme should be professional and print-friendly

## Development Rules

- Sub-skills in `skills/` each have their own `SKILL.md` — read before editing
- Python scripts should maintain compatibility with Python 3.8+
- JSON-LD templates in `schema/` follow Schema.org specifications
- Respect rate limiting: 1s delay between requests, max 5 concurrent
