# CocktailPi MCP Server

[![CI](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/ci.yml)
[![Release Please](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/release-please.yml/badge.svg)](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/release-please.yml)
[![GHCR](https://img.shields.io/badge/ghcr-cocktailpi--mcp-blue?logo=docker)](https://ghcr.io/rizz360/cocktailpi-mcp)

Model Context Protocol (MCP) server that exposes CocktailPi backend operations as MCP tools.

This README focuses on getting it running fast for end users.

## Quick start

This MCP server is started on demand by your AI client (stdio). It is not a background web service you keep running with `docker compose up -d`.

### 1) Have CocktailPi running

Before connecting AI, make sure your CocktailPi backend is reachable from Docker.

You need:
- A working CocktailPi installation
- A backend URL (for example `http://cocktailpi/`, `http://localhost:8080`, or your Tailscale/LAN URL)
- Credentials or a JWT token

### 2) Set connection values

Use [docker-compose.yml](docker-compose.yml) as a config template and edit the environment section:

```yaml
services:
  cocktailpi-mcp:
    image: ghcr.io/rizz360/cocktailpi-mcp:latest
    stdin_open: true
    tty: true
    environment:
      COCKTAILPI_BASE_URL: http://cocktailpi/

      # Option A: username/password auto-login
      COCKTAILPI_USERNAME: your-username
      COCKTAILPI_PASSWORD: your-password

      # Option B: static JWT token (use instead of username/password)
      # COCKTAILPI_ACCESS_TOKEN: your-jwt-token

      COCKTAILPI_TIMEOUT_SECONDS: 20
```

Do not run `docker compose up` for normal MCP usage.

### 3) Connect your AI client

Most MCP clients accept an `mcpServers` command-based config.

Important: this server uses stdio transport, so your AI client launches the command below and communicates over that process's stdin/stdout.

#### Claude Desktop (macOS)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cocktailpi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "COCKTAILPI_BASE_URL=http://cocktailpi/",
        "-e", "COCKTAILPI_USERNAME=your-username",
        "-e", "COCKTAILPI_PASSWORD=your-password",
        "ghcr.io/rizz360/cocktailpi-mcp:latest"
      ]
    }
  }
}
```

Put your credentials in the `-e` values above, or replace username/password with:

```json
"-e", "COCKTAILPI_ACCESS_TOKEN=your-jwt-token"
```

#### Cursor

Create or edit `.cursor/mcp.json` in your project (works when Cursor is opened in this repository):

```json
{
  "mcpServers": {
    "cocktailpi": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "-T", "cocktailpi-mcp"]
    }
  }
}
```

#### Other MCP clients

If your client cannot run `docker compose`, use a direct image command:

```json
{
  "mcpServers": {
    "cocktailpi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "COCKTAILPI_BASE_URL=http://cocktailpi/",
        "-e", "COCKTAILPI_USERNAME=your-username",
        "-e", "COCKTAILPI_PASSWORD=your-password",
        "ghcr.io/rizz360/cocktailpi-mcp:latest"
      ]
    }
  }
}
```

### 4) What AI can do once connected

Core operations:
- `list_recipes`: list recipes/cocktails
- `create_recipe`: create a new recipe
- `update_recipe`: update an existing recipe
- `delete_recipe`: delete a recipe
- `list_pumps`: list pumps and configured ingredients

Helper operations:
- `login`: obtain token from CocktailPi backend
- `get_recipe`: fetch one recipe by id
- `list_ingredients`: list ingredient ids/names
- `list_categories`: list category ids/names
- `list_glasses`: list glass ids/names

## Troubleshooting

- Connection errors usually mean `COCKTAILPI_BASE_URL` is not reachable from Docker.
- Auth errors usually mean wrong credentials/token or missing permissions.
- If your AI client cannot run `docker compose`, use the direct `docker run` config shown above.
- If you started this with `docker compose up`, stop it and use the MCP client config instead.
- `no matching manifest for linux/arm64/v8` means the published tag does not include Apple Silicon yet. Use `--platform linux/amd64` in docker args as a temporary workaround, then remove it after a multi-arch release is published.

## Advanced reference

Detailed endpoint mapping and recipe payload examples are in [docs/REFERENCE.md](docs/REFERENCE.md).

## Development

Contributor and local source setup instructions are in [CONTRIBUTING.md](CONTRIBUTING.md).
