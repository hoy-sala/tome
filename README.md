# Tome

[![Build](https://github.com/bndct-devops/tome/actions/workflows/docker.yml/badge.svg)](https://github.com/bndct-devops/tome/actions/workflows/docker.yml)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Container](https://img.shields.io/badge/ghcr.io-bndct--devops%2Ftome-blue?logo=docker)](https://github.com/bndct-devops/tome/pkgs/container/tome)

A self-hosted ebook library server for schools.

Built with FastAPI, React, and SQLite. Ships as a single Docker image.

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

```bash
docker run -d \
  --name tome \
  --restart unless-stopped \
  -p 8080:8080 \
  -v ./data:/data \
  -v ./books:/books \
  ghcr.io/bndct-devops/tome:latest
```

Open `http://localhost:8080` and follow the setup wizard to create your admin account.

Or with Docker Compose -- clone and `docker compose up -d`.

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

## License

AGPL-3.0 — see [LICENSE](LICENSE)
