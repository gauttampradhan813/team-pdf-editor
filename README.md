# TeamPDF Studio

A professional PDF editor built with Python 3.11 and FastAPI.

> **Status:** Phase 1 — project foundation. Only the application skeleton and
> the `/health` endpoint are implemented. No PDF editing features yet.

## Requirements

- Python 3.11
- A virtual environment at `.venv/`

## Setup

```powershell
# 1. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Running the application

From the project root:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --reload
```

Without auto-reload:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend
```

Then open:

| URL | Purpose |
|---|---|
| <http://127.0.0.1:8000/health> | Health check |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |

## Running the tests

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Configuration

Settings live in `backend/app/config.py` and are read from environment
variables prefixed with `TEAMPDF_`, or from a `.env` file in the project root.

| Variable | Default | Description |
|---|---|---|
| `TEAMPDF_ENVIRONMENT` | `development` | Deployment environment label |
| `TEAMPDF_DEBUG` | `true` | Enables debug output and the Swagger UI |
| `TEAMPDF_LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TEAMPDF_CORS_ORIGINS` | localhost origins | JSON array of allowed browser origins |
| `TEAMPDF_MAX_UPLOAD_SIZE_MB` | `100` | Maximum accepted upload size (used in Phase 2) |

Example `.env`:

```ini
TEAMPDF_ENVIRONMENT=production
TEAMPDF_DEBUG=false
TEAMPDF_LOG_LEVEL=WARNING
TEAMPDF_CORS_ORIGINS=["https://editor.example.com"]
```

## Project structure

```
TeamPDF-Studio/
├── backend/
│   ├── app/
│   │   ├── main.py              # Application factory and entry point
│   │   ├── config.py            # Settings (env + .env driven)
│   │   ├── logging_config.py    # Logging setup
│   │   ├── errors.py            # Global JSON error handlers
│   │   └── api/
│   │       ├── __init__.py      # API router registry
│   │       └── health.py        # GET /health
│   │   ├── models/              # Data models (reserved)
│   │   ├── services/            # Business logic (reserved)
│   │   ├── utils/               # Shared helpers (reserved)
│   │   └── vision/              # OpenCV pipelines (reserved)
│   └── tests/
│       └── test_health.py       # Health + error contract tests
├── frontend/                    # HTML/Bootstrap/vanilla JS (reserved)
├── docs/                        # Documentation (reserved)
├── test-pdfs/                   # Sample documents (reserved)
├── requirements.txt             # Direct runtime dependencies
├── pytest.ini                   # Test discovery configuration
└── README.md
```

## API

### `GET /health`

```json
{
  "status": "ok",
  "service": "TeamPDF Studio",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-01-01T12:00:00+00:00"
}
```

### Error contract

All failures share one shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "details": null
  }
}
```

| Code | HTTP status | Meaning |
|---|---|---|
| `validation_error` | 422 | Request body/query failed validation |
| `not_found` | 404 | Route does not exist |
| `http_error` | 4xx/5xx | Other HTTP-level error |
| `internal_error` | 500 | Unhandled server error |

## Development rules

- Python 3.11, FastAPI, PyMuPDF, pikepdf, Pillow, OpenCV, fontTools
- Frontend: HTML, Bootstrap, CSS, vanilla JavaScript
- No database at this stage
- PDF editing features start in Phase 2
