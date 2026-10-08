---
title: L'Écho de Montolieu
emoji: 📰
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: true
license: agpl-3.0
---

# L'Écho de Montolieu 📰

**The Montolieu Echo** — A trilingual, accessible, open-source community dashboard and civic monitoring platform for the village of Montolieu, France (Aude, Occitanie).

[![WCAG 2.2 AA](https://img.shields.io/badge/WCAG-2.2%20AA-green)](https://www.w3.org/TR/WCAG22/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Languages: FR EN NL](https://img.shields.io/badge/Languages-FR%20%7C%20EN%20%7C%20NL-informational)]()

## What Is This?

L'Écho de Montolieu aggregates municipal council decisions, local zoning/property impacts, business hours, and cultural events into an interactive web map and feed for the village of **Montolieu** (population ~800), known as the *Village du Livre et des Arts* (Village of Books and Arts).

### Features

- 🗺️ **Interactive Map** — Leaflet.js map with geocoded council decisions, businesses, and cultural sites
- ♿ **Accessible List View** — Full WCAG 2.2 AA compliant alternative to the map
- 🇫🇷🇬🇧🇳🇱 **Trilingual** — French, English, and Dutch with dynamic `<html lang>` switching
- 📋 **Council Minutes Feed** — Automated extraction and translation of municipal decisions
- 🏪 **Business Directory** — Live SIRENE/INSEE data for local shops and artisans
- 📐 **Parcel Lookup** — BAN + Cadastre integration for property/zoning queries
- 🤖 **MCP Tools** — Model Context Protocol endpoints for AI agent integration

## Quick Start

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/montolieu-echo.git
cd montolieu-echo

# Install dependencies
pip install -r requirements.txt

# Run the development server
python app.py
# → Open http://localhost:8000
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│            AUTOMATED PIPELINE                   │
│                                                 │
│  [Mairie PDF Archive]                           │
│       ↓  GitHub Actions (Daily @ 06:00 UTC)     │
│  [Gemini LLM: Extract + Translate]              │
│       ↓                                         │
│  [BAN API + SIRENE API: Geocode + Enrich]       │
│       ↓                                         │
│  [data/*.json committed to repo]                │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│            FRONTEND / API                       │
│                                                 │
│  FastAPI Backend (app.py)                       │
│  ├── /api/council    → Council minutes feed     │
│  ├── /api/directory  → Business directory       │
│  ├── /api/geocode    → BAN address lookup       │
│  ├── /api/sirene     → Business search          │
│  └── /mcp/*          → MCP tool endpoints       │
│                                                 │
│  Static Frontend (static/)                      │
│  ├── Leaflet.js interactive map                 │
│  ├── Accessible list view                       │
│  └── Trilingual language switcher               │
└─────────────────────────────────────────────────┘
```

## Data Sources

| Source | API | Purpose |
|--------|-----|---------|
| [BAN](https://api-adresse.data.gouv.fr/) | Free, no key | Geocoding addresses → GPS coordinates |
| [SIRENE/INSEE](https://recherche-entreprises.api.gouv.fr/) | Free, no key | Business registration & status |
| [Cadastre](https://cadastre.data.gouv.fr/) | Free, no key | Land parcel boundaries |
| [Géoportail Urbanisme](https://www.geoportail-urbanisme.gouv.fr/) | Free, no key | Zoning & planning rules |
| [Mairie de Montolieu](https://www.montolieu.fr/) | Web scrape | Council minutes PDFs |

## Accessibility (WCAG 2.2 AA)

- All interactive elements have minimum 44×44px touch targets
- Text contrast ratio ≥ 7:1 (enhanced)
- Map view has a persistent "Switch to List View" toggle
- Language switching updates `<html lang>` for screen readers
- All focusable elements show 3px high-contrast focus outlines
- Map markers use distinct geometric shapes alongside color coding

## Contributing

Contributions welcome! Please read our contributing guidelines and ensure all PRs maintain WCAG 2.2 AA compliance.

## License

[AGPL-3.0](LICENSE) — Free and open source. Community data should remain community-accessible.
