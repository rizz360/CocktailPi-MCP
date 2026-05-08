from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from cocktailpi_mcp.cocktailpi_client import CocktailPiApiError, CocktailPiClient
from cocktailpi_mcp.config import load_settings

settings = load_settings()
client = CocktailPiClient(settings.base_url, settings.timeout_seconds)

# Resolved at startup: either the static token or one obtained via auto-login.
_resolved_token: str | None = settings.access_token


async def _auto_login() -> None:
    """If no static token is configured but credentials are, perform login once."""
    global _resolved_token
    if _resolved_token:
        return
    if settings.username and settings.password:
        result = await client.login(username=settings.username, password=settings.password)
        _resolved_token = result.access_token


mcp = FastMCP(
    "CocktailPi MCP",
    instructions=(
        "MCP tools for CocktailPi recipe and pump operations. "
        "Use login first to get an access token, or configure COCKTAILPI_ACCESS_TOKEN "
        "or COCKTAILPI_USERNAME + COCKTAILPI_PASSWORD for auto-login."
    ),
)


def _resolve_token(explicit_token: str | None) -> str:
    token = (explicit_token or _resolved_token or "").strip()
    if not token:
        raise CocktailPiApiError(
            "No access token available. Call login, set COCKTAILPI_ACCESS_TOKEN, "
            "or set COCKTAILPI_USERNAME + COCKTAILPI_PASSWORD."
        )
    return token


@mcp.tool(description="Authenticate against CocktailPi and return JWT token details.")
async def login(username: str, password: str, remember: bool = True) -> dict[str, Any]:
    result = await client.login(username=username, password=password, remember=remember)
    return {
        "access_token": result.access_token,
        "token_type": result.token_type,
        "token_expiration": result.token_expiration,
        "user": result.user,
        "note": "Pass access_token into other tools as token, or set COCKTAILPI_ACCESS_TOKEN.",
    }


@mcp.tool(
    description=(
        "List CocktailPi recipes (search results). "
        "Set include_details=true to fetch full details for each returned recipe."
    )
)
async def list_recipes(
    token: str | None = None,
    page: int = 0,
    owner_id: int | None = None,
    in_collection: int | None = None,
    in_category: int | None = None,
    search_name: str | None = None,
    fabricable: str = "all",
    order_by: str = "name",
    include_details: bool = False,
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    recipes_page = await client.list_recipes(
        auth_token,
        page=page,
        owner_id=owner_id,
        in_collection=in_collection,
        in_category=in_category,
        search_name=search_name,
        fabricable=fabricable,
        order_by=order_by,
    )

    if not include_details:
        return recipes_page

    content = recipes_page.get("content")
    if not isinstance(content, list):
        return recipes_page

    details: list[dict[str, Any]] = []
    for recipe in content:
        recipe_id = recipe.get("id")
        if isinstance(recipe_id, int):
            details.append(await client.get_recipe(auth_token, recipe_id, is_ingredient=False))

    recipes_page["detailedContent"] = details
    return recipes_page


@mcp.tool(description="Get a single CocktailPi recipe by id.")
async def get_recipe(
    recipe_id: int,
    token: str | None = None,
    is_ingredient_recipe: bool = False,
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.get_recipe(auth_token, recipe_id, is_ingredient=is_ingredient_recipe)


@mcp.tool(
    description=(
        "Create a new CocktailPi recipe. "
        "The recipe_json argument must match CocktailPi recipe create DTO structure. "
        "Optional image_base64 can be provided to set the recipe image during creation."
    )
)
async def create_recipe(
    recipe_json: dict[str, Any],
    token: str | None = None,
    image_base64: str | None = None,
    image_filename: str = "recipe.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.create_recipe(
        auth_token,
        recipe_json,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )


@mcp.tool(
    description=(
        "Update an existing CocktailPi recipe by id. "
        "The recipe_json argument must match CocktailPi recipe create DTO structure. "
        "Use image_base64 to add/replace image and remove_image=true to delete image."
    )
)
async def update_recipe(
    recipe_id: int,
    recipe_json: dict[str, Any],
    token: str | None = None,
    remove_image: bool = False,
    image_base64: str | None = None,
    image_filename: str = "recipe.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.update_recipe(
        auth_token,
        recipe_id=recipe_id,
        recipe=recipe_json,
        remove_image=remove_image,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )


@mcp.tool(
    description=(
        "Add or replace the image of an existing CocktailPi recipe. "
        "The recipe_json argument must match CocktailPi recipe create DTO structure."
    )
)
async def add_or_update_recipe_image(
    recipe_id: int,
    recipe_json: dict[str, Any],
    image_base64: str,
    token: str | None = None,
    image_filename: str = "recipe.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.add_or_update_recipe_image(
        auth_token,
        recipe_id=recipe_id,
        recipe=recipe_json,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )


@mcp.tool(
    description=(
        "Delete the image of an existing CocktailPi recipe. "
        "The recipe_json argument must match CocktailPi recipe create DTO structure."
    )
)
async def delete_recipe_image(
    recipe_id: int,
    recipe_json: dict[str, Any],
    token: str | None = None,
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.delete_recipe_image(
        auth_token,
        recipe_id=recipe_id,
        recipe=recipe_json,
    )


@mcp.tool(description="Delete a CocktailPi recipe by id.")
async def delete_recipe(recipe_id: int, token: str | None = None) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.delete_recipe(auth_token, recipe_id)


@mcp.tool(description="List pumps and their currently configured ingredients.")
async def list_pumps(token: str | None = None) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    pumps = await client.list_pumps(auth_token)

    normalized: list[dict[str, Any]] = []
    for p in pumps:
        current = p.get("currentIngredient") if isinstance(p, dict) else None
        normalized.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "type": p.get("type"),
                "state": p.get("state"),
                "isPumpedUp": p.get("pumpedUp"),
                "fillingLevelInMl": p.get("fillingLevelInMl"),
                "currentIngredient": current,
            }
        )
    return normalized


@mcp.tool(description="List ingredients to help build recipe payloads.")
async def list_ingredients(
    token: str | None = None,
    autocomplete: str | None = None,
    in_bar_or_on_pump: bool = True,
) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    return await client.list_ingredients(
        auth_token,
        autocomplete=autocomplete,
        in_bar_or_on_pump=in_bar_or_on_pump,
    )


@mcp.tool(description="List recipe categories.")
async def list_categories(token: str | None = None) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    return await client.list_categories(auth_token)


@mcp.tool(description="List glasses.")
async def list_glasses(token: str | None = None) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    return await client.list_glasses(auth_token)


def run() -> None:
    asyncio.run(_auto_login())
    mcp.run(transport="stdio")
