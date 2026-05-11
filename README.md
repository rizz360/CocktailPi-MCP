# CocktailPi MCP Server

[![CI](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/ci.yml)
[![Release Please](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/release-please.yml/badge.svg)](https://github.com/rizz360/cocktailpi-mcp/actions/workflows/release-please.yml)
[![GHCR](https://img.shields.io/badge/ghcr-cocktailpi--mcp-blue?logo=docker)](https://ghcr.io/rizz360/cocktailpi-mcp)

Model Context Protocol (MCP) server that exposes CocktailPi backend operations as MCP tools.

This README focuses on getting it running fast for end users.

## Quick start

This MCP server is started on demand by your AI client (stdio).

You do **not** run this as a long-lived container with `docker compose up -d`.

### 1) Have CocktailPi running

Before connecting AI, make sure your CocktailPi backend is reachable from Docker.

You need:
- A working CocktailPi installation
- A backend URL (for example `http://cocktailpi/`, `http://localhost:8080`, or your Tailscale/LAN URL)
- Credentials or a JWT token

### 2) Add it to your AI client

Most MCP clients accept an `mcpServers` command-based config.

Important: this server uses stdio transport, so your AI client launches the command and communicates over that process's stdin/stdout.

Use these values in the command args:
- `COCKTAILPI_BASE_URL`: your CocktailPi backend URL
- Option A: `COCKTAILPI_USERNAME` + `COCKTAILPI_PASSWORD`
- Option B: `COCKTAILPI_ACCESS_TOKEN` (instead of username/password)
- Optional: `COCKTAILPI_TIMEOUT_SECONDS=20`

### 3) Add the same server config in your client

The server command is the same across MCP clients. Only the config file path changes.

Config file locations:
- Claude Desktop (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
- Cursor: `.cursor/mcp.json`
- Other MCP clients: use the client's `mcpServers` config file

Use this config block:

```json
{
  "mcpServers": {
    "cocktailpi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--pull", "always",
        "-e", "COCKTAILPI_BASE_URL=http://cocktailpi/",
        "-e", "COCKTAILPI_USERNAME=your-username",
        "-e", "COCKTAILPI_PASSWORD=your-password",
        "ghcr.io/rizz360/cocktailpi-mcp:latest"
      ]
    }
  }
}
```

Use either username/password or a token in the `-e` values:
- Username/password: `COCKTAILPI_USERNAME` + `COCKTAILPI_PASSWORD`
- Token: `COCKTAILPI_ACCESS_TOKEN=your-jwt-token` (replace the username/password env vars)

`"--pull", "always"` makes Docker check for a newer image at each launch.

### 4) What AI can do once connected

Core operations:
- `list_recipes`: list recipes/cocktails
- `create_recipe`: create a new recipe
- `update_recipe`: update an existing recipe
- `analyze_pump_ingredient_optimization`: strict full-automation and replacement analysis across all recipes
- `analyze_current_pump_contributions`: identify least-contributing current pump ingredients and suggest stronger replacements from bar
- `set_ingredient_in_bar`: mark one ingredient as present or absent in the bar inventory
- `set_ingredients_in_bar`: bulk mark ingredients as present or absent in the bar inventory
- `add_or_update_recipe_image`: add or replace a recipe image
- `add_or_update_recipe_image_from_url`: add/replace recipe image by URL
- `add_or_update_recipe_image_from_svg`: add/replace recipe image from SVG text
- `delete_recipe_image`: remove a recipe image
- `delete_recipe`: delete a recipe
- `list_pumps`: list pumps and configured ingredients

Helper operations:
- `login`: obtain token from CocktailPi backend
- `get_recipe`: fetch one recipe by id
- `list_ingredients`: list ingredient ids/names
- `list_categories`: list category ids/names
- `list_glasses`: list glass ids/names

Image notes:
- `create_recipe` and `update_recipe` now accept optional `image_base64` (plus optional `image_filename` and `image_content_type`).
- `image_base64` can be raw base64 bytes or a data URL (for example `data:image/png;base64,...`).
- `add_or_update_recipe_image_from_url` downloads image content server-side, so AI only sends a short URL argument.
- `add_or_update_recipe_image_from_svg` renders SVG text to PNG server-side, avoiding large base64 arguments.
- For `add_or_update_recipe_image`, `add_or_update_recipe_image_from_url`, and `delete_recipe_image`, `recipe_json` is optional.
- If `recipe_json` is omitted, the MCP server fetches the existing recipe and reuses current values for update.

Auth behavior notes:
- Every tool's `token` parameter is optional.
- If `token` is omitted, the MCP server automatically falls back to configured `COCKTAILPI_ACCESS_TOKEN` or startup auto-login token.
- Call `login` only if you need to fetch/refresh a token explicitly.

Minimal `create_recipe` payload pattern:

```json
{
  "name": "New Drink",
  "ownerId": 1,
  "categoryIds": [],
  "productionSteps": [
    {
      "type": "addIngredients",
      "stepIngredients": [
        {
          "ingredientId": 10,
          "ingredientType": "<valid-type-from-backend>",
          "amount": 50,
          "scale": true,
          "boostable": false
        }
      ]
    }
  ]
}
```

Payload gotchas:
- Use `categoryIds` (not `categories`) and include it even if empty.
- Keep ingredient entries flat using `ingredientId` and `ingredientType` (not nested ingredient object).
- `ingredientType` values are backend-defined; use `get_recipe` on an existing recipe to copy a valid value.
- Include `ownerId` explicitly when possible; MCP can infer it from JWT claims if omitted.
- Non-matching `ownerId` values require an admin-like token, otherwise MCP rejects the write.
- If backend ignores admin owner override, MCP returns an explicit owner mismatch error.

## Troubleshooting

- Connection errors usually mean `COCKTAILPI_BASE_URL` is not reachable from Docker.
- Auth errors usually mean wrong credentials/token or missing permissions.
- If you started this with `docker compose up`, stop it and use MCP client config that runs `docker run` on demand.
- `no matching manifest for linux/arm64/v8` means the published tag does not include Apple Silicon yet. Use `--platform linux/amd64` in docker args as a temporary workaround, then remove it after a multi-arch release is published.

## Optional: use docker-compose.yml as a value template

Most users can skip this section.

The [docker-compose.yml](docker-compose.yml) file is mainly a convenient place to keep environment values together while testing. For normal MCP usage, your AI client still launches the server process directly.

If you prefer, copy env values from `docker-compose.yml` into your MCP client args (`-e KEY=value`).

## Advanced reference

Detailed endpoint mapping and recipe payload examples are in [docs/REFERENCE.md](docs/REFERENCE.md).

## Development

Contributor and local source setup instructions are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the European Union Public Licence v1.2 (EUPL-1.2).
See [LICENSE](LICENSE) for details.
