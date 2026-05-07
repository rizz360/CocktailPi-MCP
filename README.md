# CocktailPi MCP Server

Model Context Protocol (MCP) server that exposes CocktailPi backend operations as MCP tools.

## Why this implementation

- Uses Python, which is typically already available on hosts running CocktailPi.
- Keeps dependencies low (official MCP SDK + HTTP client).
- Proxies existing CocktailPi backend REST APIs, so no direct database coupling.

## Implemented tools

Required tools:
- `list_recipes`: list defined cocktails/recipes, with optional full details.
- `create_recipe`: add a new recipe.
- `list_pumps`: list attached pumps including currently configured ingredient/drink.

Additional helper tools:
- `login`: get JWT token from CocktailPi backend.
- `get_recipe`: fetch one recipe by id.
- `list_ingredients`: resolve ingredient ids for recipe authoring.
- `list_categories`: resolve category ids.
- `list_glasses`: resolve glass ids.

## CocktailPi API mapping

This MCP server calls these CocktailPi endpoints:
- `POST /api/auth/login`
- `GET /api/recipe/`
- `GET /api/recipe/{id}`
- `POST /api/recipe/` (multipart with `recipe` part)
- `GET /api/pump/`
- `GET /api/ingredient/`
- `GET /api/category/`
- `GET /api/glass/`

## Prerequisites

- Python 3.10+
- Network access to CocktailPi backend (default `http://localhost:8080`)
- CocktailPi user with permissions:
  - read recipes/pumps/ingredients (for list tools)
  - `RECIPE_CREATOR` role for creating recipes

## Local setup

1. Create virtual environment and install dependencies:

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
```

2. Configure environment variables:

```bash
copy .env.example .env
```

Set at least:
- `COCKTAILPI_BASE_URL` (example: `http://localhost:8080`)
- Optional: `COCKTAILPI_ACCESS_TOKEN`

3. Run server:

```bash
set PYTHONPATH=src
python -m cocktailpi_mcp.main
```

## Docker usage

Build image:

```bash
docker build -t cocktailpi-mcp .
```

Run with env vars:

```bash
docker run --rm -i \
  -e COCKTAILPI_BASE_URL=http://host.docker.internal:8080 \
  -e COCKTAILPI_ACCESS_TOKEN=YOUR_TOKEN \
  cocktailpi-mcp
```

## MCP client config example

Example command-based MCP entry:

```json
{
  "mcpServers": {
    "cocktailpi": {
      "command": "python",
      "args": ["-m", "cocktailpi_mcp.main"],
      "env": {
        "PYTHONPATH": "src",
        "COCKTAILPI_BASE_URL": "http://localhost:8080"
      }
    }
  }
}
```

## Recipe payload shape for create_recipe

`create_recipe` accepts `recipe_json` matching CocktailPi `RecipeDto.Request.Create`:

```json
{
  "name": "Gin Tonic",
  "ownerId": 1,
  "description": "Classic long drink",
  "categoryIds": [1],
  "defaultGlassId": 1,
  "productionSteps": [
    {
      "type": "addIngredients",
      "stepIngredients": [
        { "ingredientId": 10, "amount": 50, "scale": true, "boostable": false },
        { "ingredientId": 11, "amount": 150, "scale": true, "boostable": false }
      ]
    },
    {
      "type": "writtenInstruction",
      "message": "Add ice and garnish with lime"
    }
  ]
}
```

Use `list_ingredients`, `list_categories`, and `list_glasses` to discover valid ids.

## Notes

- The server runs over stdio transport (best for MCP command integrations).
- If no token is provided in a tool call, the server falls back to `COCKTAILPI_ACCESS_TOKEN`.
- `create_recipe` currently supports recipe JSON only (no image upload yet).
