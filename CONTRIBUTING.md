# Contributing

Thanks for contributing to CocktailPi MCP.

## Local development setup

Prerequisites:
- Python 3.10+
- Docker (optional, for container checks)

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip build
python -m pip install -r requirements.txt
```

Run the server from source:

```bash
PYTHONPATH=src python -m cocktailpi_mcp.main
```

## Environment variables

Use `.env.example` as reference. Common variables:
- `COCKTAILPI_BASE_URL` (example: `http://localhost:8080`)
- `COCKTAILPI_ACCESS_TOKEN` (optional)
- `COCKTAILPI_USERNAME` and `COCKTAILPI_PASSWORD` (optional alternative to access token)
- `COCKTAILPI_TIMEOUT_SECONDS` (optional, default request timeout override)

## Validation checks

Before opening a PR, run:

```bash
python -m compileall src
python -m build
PYTHONPATH=src python -c "from cocktailpi_mcp.server import mcp; print(mcp.name)"
```

## Docker checks (optional)

Build image locally:

```bash
docker build -t cocktailpi-mcp:dev .
```

Run with compose:

```bash
docker compose up --build
```

## Releases

Releases are managed through Release Please and GitHub Actions workflows.
