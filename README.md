# Tome

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

A self-hosted ebook library server — stripped down for personal use.

Built with FastAPI, React, and SQLite.

## Features

- **Built-in reader** -- EPUBs, manga (CBZ/CBR), and PDFs render directly in the browser. Two-page spread, RTL mode, webtoon scroll, pinch-to-zoom on mobile.
- **Metadata from 3 sources** -- fetch and compare metadata from Hardcover, Google Books, and OpenLibrary with a side-by-side diff UI.
- **Bindery** -- an inbox for incoming books. Drop files in a folder, review pre-filled metadata, accept into your library. Optional auto-import on a schedule.
- **Scribe** -- a Claude Code Skill for conversational batch ingest, metadata refresh, and series audits. Uses API tokens for auth and talks to Tome over HTTP.
- **OPDS feed** -- browse and download from KOReader, Panels, Chunky, or any OPDS client.
- **SSO (OIDC)** -- optional single sign-on against any OpenID Connect provider with group-to-role mapping and account linking. Local login always stays.
- **Themes** -- 3 built-in (light, dark, amber) plus fully custom themes via 10-value hex palette.
- **Role-based access control** -- admin, member, and guest roles with per-user book visibility.
- **Series browsing** with publication status, bulk operations, libraries with icons, shelves (saved filters), user-level API tokens, and audit logging.

## Quick Start

Clone the repo and run:

```bash
docker compose up -d
```

Open `http://localhost:8080` and follow the setup wizard to create your admin account.

### Volumes

| Mount | Purpose |
|-------|---------|
| `/data` | SQLite database and cover cache |
| `/books` | Ebook library (read-only is fine) |
| `/bindery` | Incoming folder for new books |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOME_SECRET_KEY` | Yes | -- | JWT signing secret |
| `TOME_DATA_DIR` | No | `/data` | DB and cover cache |
| `TOME_LIBRARY_DIR` | No | `/books` | Library root |
| `TOME_INCOMING_DIR` | No | `/bindery` | Bindery folder |
| `TOME_PORT` | No | `8080` | HTTP port |
| `TOME_PUBLIC_URL` | No | -- | Canonical public origin |
| `TOME_AUTO_IMPORT` | No | `false` | Auto-import files from the bindery on a schedule |
| `TOME_AUTO_IMPORT_INTERVAL` | No | `300` | Seconds between auto-import scans |
| `TOME_SCAN_WORKERS` | No | `1` | Parallel scan workers (>1 = multi-process; ~60–80 MB each) |

### Supported Formats

| Format | Reader | Notes |
|--------|--------|-------|
| EPUB | Text reader | CFI position tracking |
| CBZ | Comic reader | Streaming page delivery |
| CBR | Comic reader | Auto-repacked to ZIP |
| PDF | Browser viewer | Served directly |

## Development

Requirements: Python 3.12+, Node.js 18+

```bash
./dev.sh   # starts backend :8080 + frontend :5173
```

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12+ / FastAPI |
| Database | SQLite (WAL) / SQLAlchemy 2.0 |
| Frontend | React 19 / Vite / TypeScript |
| Styling | Tailwind CSS 4 |
| Auth | JWT (python-jose) |

## Acknowledgments

- Forked from [bndct-devops/tome](https://github.com/bndct-devops/tome) — the original project with full features (KOReader sync, reading stats, Hardcover sync, and more). Go check it out if you want the complete experience.
- [KOReader](https://koreader.rocks) — the open source e-reader app
- [foliate-js](https://github.com/johnfactotum/foliate-js) — the EPUB rendering engine

## License

AGPL-3.0 — see [LICENSE](LICENSE)
