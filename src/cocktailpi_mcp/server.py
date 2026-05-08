from __future__ import annotations

import asyncio
import base64
import binascii
import json
from typing import Any

import cairosvg
import httpx
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
        "The token parameter on tools is optional: when omitted, the server falls back "
        "to the configured token or startup auto-login token. "
        "Use login only when you need to fetch/refresh a token explicitly. "
        "For recipe writes, use categoryIds (not categories), include ownerId, and keep "
        "stepIngredients flat with ingredientId + ingredientType fields."
    ),
)

TOKEN_HELP = (
    "token is optional. If omitted, server uses configured "
    "COCKTAILPI_ACCESS_TOKEN or startup auto-login token."
)

RECIPE_MINIMAL_SHAPE_HELP = (
    "recipe_json must include categoryIds (empty list allowed). "
    "ownerId is strongly recommended and will be inferred from token when possible. "
    "For ingredient steps, each entry must be flat fields like ingredientId and "
    "ingredientType (not nested ingredient object)."
)

IMAGE_FETCH_MAX_BYTES = 8 * 1024 * 1024
ALLOWED_REMOTE_IMAGE_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload_part = parts[1].strip()
    if not payload_part:
        return {}

    padding = "=" * ((4 - len(payload_part) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_part + padding)
    except (binascii.Error, ValueError):
        return {}

    try:
        raw_payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}

    if not isinstance(raw_payload, dict):
        return {}
    return raw_payload


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        if parsed > 0:
            return parsed
    return None


def _extract_authenticated_owner_id(auth_token: str) -> int | None:
    payload = _decode_jwt_payload(auth_token)
    for key in ("userId", "ownerId", "id", "uid"):
        owner_id = _as_positive_int(payload.get(key))
        if owner_id is not None:
            return owner_id

    sub = payload.get("sub")
    return _as_positive_int(sub)


def _extract_authenticated_roles(auth_token: str) -> set[str]:
    payload = _decode_jwt_payload(auth_token)
    roles: set[str] = set()

    role_like_fields = [
        payload.get("roles"),
        payload.get("role"),
        payload.get("authorities"),
        payload.get("scope"),
        payload.get("scopes"),
    ]

    for field in role_like_fields:
        if isinstance(field, str):
            for part in field.replace(",", " ").split():
                normalized = part.strip().lower()
                if normalized:
                    roles.add(normalized)
        elif isinstance(field, list):
            for item in field:
                if isinstance(item, str):
                    normalized = item.strip().lower()
                    if normalized:
                        roles.add(normalized)

    return roles


def _can_override_owner(auth_token: str) -> bool:
    roles = _extract_authenticated_roles(auth_token)
    return any("admin" in role for role in roles)


def _extract_owner_id_from_recipe(recipe: dict[str, Any]) -> int | None:
    owner_id = _as_positive_int(recipe.get("ownerId"))
    if owner_id is not None:
        return owner_id

    owner = recipe.get("owner")
    if isinstance(owner, dict):
        return _as_positive_int(owner.get("id"))
    return None


def _normalize_recipe_owner_for_write(auth_token: str, recipe_json: dict[str, Any]) -> dict[str, Any]:
    payload = dict(recipe_json)
    requested_owner_id = _as_positive_int(payload.get("ownerId"))
    authenticated_owner_id = _extract_authenticated_owner_id(auth_token)

    if requested_owner_id is None:
        if authenticated_owner_id is not None:
            payload["ownerId"] = authenticated_owner_id
            return payload
        raise CocktailPiApiError(
            "ownerId is required in recipe_json and could not be inferred from token."
        )

    if authenticated_owner_id is None:
        payload["ownerId"] = requested_owner_id
        return payload

    if requested_owner_id == authenticated_owner_id:
        payload["ownerId"] = requested_owner_id
        return payload

    if _can_override_owner(auth_token):
        payload["ownerId"] = requested_owner_id
        return payload

    raise CocktailPiApiError(
        "ownerId does not match authenticated user and token has no admin role. "
        f"Requested ownerId={requested_owner_id}, authenticated ownerId={authenticated_owner_id}."
    )


def _validate_owner_assignment(
    result: dict[str, Any],
    *,
    requested_owner_id: int | None,
    auth_token: str,
    operation: str,
) -> None:
    if requested_owner_id is None:
        return

    authenticated_owner_id = _extract_authenticated_owner_id(auth_token)
    if authenticated_owner_id is None or requested_owner_id == authenticated_owner_id:
        return

    actual_owner_id = _extract_owner_id_from_recipe(result)
    if actual_owner_id is None:
        return

    if actual_owner_id != requested_owner_id:
        raise CocktailPiApiError(
            f"{operation} completed but ownerId override was not applied. "
            f"Requested ownerId={requested_owner_id}, actual ownerId={actual_owner_id}. "
            "CocktailPi may not allow owner override for this token/backend."
        )


def _resolve_token(explicit_token: str | None) -> str:
    token = (explicit_token or _resolved_token or "").strip()
    if not token:
        raise CocktailPiApiError(
            "No access token available. Call login, set COCKTAILPI_ACCESS_TOKEN, "
            "or set COCKTAILPI_USERNAME + COCKTAILPI_PASSWORD."
        )
    return token


def _coerce_recipe_to_write_payload(recipe_detail: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    name = recipe_detail.get("name")
    if isinstance(name, str) and name.strip():
        payload["name"] = name

    owner_id = _as_positive_int(recipe_detail.get("ownerId"))
    if owner_id is None:
        owner = recipe_detail.get("owner")
        if isinstance(owner, dict):
            owner_id = _as_positive_int(owner.get("id"))
    if owner_id is not None:
        payload["ownerId"] = owner_id

    category_ids = recipe_detail.get("categoryIds")
    if isinstance(category_ids, list) and all(isinstance(x, int) for x in category_ids):
        payload["categoryIds"] = category_ids
    else:
        categories = recipe_detail.get("categories")
        if isinstance(categories, list):
            derived_ids = [c.get("id") for c in categories if isinstance(c, dict) and isinstance(c.get("id"), int)]
            payload["categoryIds"] = derived_ids
        else:
            payload["categoryIds"] = []

    production_steps = recipe_detail.get("productionSteps")
    if isinstance(production_steps, list):
        payload["productionSteps"] = production_steps

    description = recipe_detail.get("description")
    if isinstance(description, str):
        payload["description"] = description

    default_glass_id = recipe_detail.get("defaultGlassId")
    if not isinstance(default_glass_id, int):
        default_glass = recipe_detail.get("defaultGlass")
        if isinstance(default_glass, dict) and isinstance(default_glass.get("id"), int):
            default_glass_id = default_glass["id"]
    if isinstance(default_glass_id, int):
        payload["defaultGlassId"] = default_glass_id

    return payload


async def _resolve_recipe_payload_for_image_update(
    auth_token: str,
    recipe_id: int,
    recipe_json: dict[str, Any] | None,
) -> dict[str, Any]:
    if recipe_json is not None:
        return _normalize_recipe_owner_for_write(auth_token, recipe_json)

    existing = await client.get_recipe(auth_token, recipe_id, is_ingredient=False)
    payload = _coerce_recipe_to_write_payload(existing)
    payload = _normalize_recipe_owner_for_write(auth_token, payload)

    if "categoryIds" not in payload:
        payload["categoryIds"] = []
    if not isinstance(payload.get("productionSteps"), list):
        payload["productionSteps"] = []

    return payload


async def _download_image_bytes(image_url: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=True) as http:
            response = await http.get(image_url)
    except httpx.HTTPError as exc:
        raise CocktailPiApiError(f"Failed to download image_url: {exc}") from exc

    if response.status_code >= 400:
        raise CocktailPiApiError(f"Failed to download image_url: HTTP {response.status_code}")

    content_type_header = response.headers.get("content-type", "").lower()
    content_type = content_type_header.split(";", 1)[0].strip()
    if content_type not in ALLOWED_REMOTE_IMAGE_CONTENT_TYPES:
        raise CocktailPiApiError(
            "image_url content-type must be one of: "
            + ", ".join(sorted(ALLOWED_REMOTE_IMAGE_CONTENT_TYPES))
        )

    raw = response.content
    if not raw:
        raise CocktailPiApiError("Downloaded image is empty")
    if len(raw) > IMAGE_FETCH_MAX_BYTES:
        raise CocktailPiApiError(f"Downloaded image exceeds max size of {IMAGE_FETCH_MAX_BYTES} bytes")

    return raw, content_type


@mcp.tool(
    description=(
        "Authenticate against CocktailPi and return JWT token details. "
        "Most tools do not require this call if server token fallback is configured."
    )
)
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
        "Set include_details=true to fetch full details for each returned recipe. "
        f"{TOKEN_HELP}"
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


@mcp.tool(description=f"Get a single CocktailPi recipe by id. {TOKEN_HELP}")
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
        f"{RECIPE_MINIMAL_SHAPE_HELP} "
        "Minimal recipe_json example: "
        "{\"name\":\"New Drink\",\"ownerId\":1,\"categoryIds\":[],"
        "\"productionSteps\":[{\"type\":\"addIngredients\","
        "\"stepIngredients\":[{\"ingredientId\":10,"
        "\"ingredientType\":\"<valid-type-from-backend>\"," 
        "\"amount\":50,\"scale\":true,\"boostable\":false}]}]}. "
        "Tip: obtain a valid ingredientType by inspecting an existing recipe via get_recipe. "
        "Optional image_base64 can be provided to set the recipe image during creation. "
        f"{TOKEN_HELP}"
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
    normalized_recipe = _normalize_recipe_owner_for_write(auth_token, recipe_json)
    result = await client.create_recipe(
        auth_token,
        normalized_recipe,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )
    _validate_owner_assignment(
        result,
        requested_owner_id=_as_positive_int(normalized_recipe.get("ownerId")),
        auth_token=auth_token,
        operation="create_recipe",
    )
    return result


@mcp.tool(
    description=(
        "Update an existing CocktailPi recipe by id. "
        f"{RECIPE_MINIMAL_SHAPE_HELP} "
        "Use image_base64 to add/replace image and remove_image=true to delete image. "
        f"{TOKEN_HELP}"
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
    normalized_recipe = _normalize_recipe_owner_for_write(auth_token, recipe_json)
    result = await client.update_recipe(
        auth_token,
        recipe_id=recipe_id,
        recipe=normalized_recipe,
        remove_image=remove_image,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )
    _validate_owner_assignment(
        result,
        requested_owner_id=_as_positive_int(normalized_recipe.get("ownerId")),
        auth_token=auth_token,
        operation="update_recipe",
    )
    return result


@mcp.tool(
    description=(
        "Add or replace the image of an existing CocktailPi recipe. "
        f"{RECIPE_MINIMAL_SHAPE_HELP} "
        f"{TOKEN_HELP}"
    )
)
async def add_or_update_recipe_image(
    recipe_id: int,
    image_base64: str | None = None,
    recipe_json: dict[str, Any] | None = None,
    token: str | None = None,
    image_filename: str = "recipe.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    if not image_base64:
        raise CocktailPiApiError("image_base64 is required")
    payload = await _resolve_recipe_payload_for_image_update(auth_token, recipe_id, recipe_json)
    result = await client.add_or_update_recipe_image(
        auth_token,
        recipe_id=recipe_id,
        recipe=payload,
        image_base64=image_base64,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )
    _validate_owner_assignment(
        result,
        requested_owner_id=_as_positive_int(payload.get("ownerId")),
        auth_token=auth_token,
        operation="add_or_update_recipe_image",
    )
    return result


@mcp.tool(
    description=(
        "Delete the image of an existing CocktailPi recipe. "
        f"{RECIPE_MINIMAL_SHAPE_HELP} "
        f"{TOKEN_HELP}"
    )
)
async def delete_recipe_image(
    recipe_id: int,
    recipe_json: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    payload = await _resolve_recipe_payload_for_image_update(auth_token, recipe_id, recipe_json)
    return await client.delete_recipe_image(
        auth_token,
        recipe_id=recipe_id,
        recipe=payload,
    )


@mcp.tool(
    description=(
        "Add or replace recipe image by downloading from a URL. "
        "image_url must resolve to an allowed image content-type. "
        "If recipe_json is omitted, server fetches recipe and reuses current values for update. "
        f"{TOKEN_HELP}"
    )
)
async def add_or_update_recipe_image_from_url(
    recipe_id: int,
    image_url: str,
    recipe_json: dict[str, Any] | None = None,
    token: str | None = None,
    image_filename: str = "recipe-from-url",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    payload = await _resolve_recipe_payload_for_image_update(auth_token, recipe_id, recipe_json)
    image_bytes, image_content_type = await _download_image_bytes(image_url)
    result = await client.add_or_update_recipe_image_bytes(
        auth_token,
        recipe_id=recipe_id,
        recipe=payload,
        image_bytes=image_bytes,
        image_filename=image_filename,
        image_content_type=image_content_type,
    )
    _validate_owner_assignment(
        result,
        requested_owner_id=_as_positive_int(payload.get("ownerId")),
        auth_token=auth_token,
        operation="add_or_update_recipe_image_from_url",
    )
    return result


@mcp.tool(
    description=(
        "Add or replace recipe image from raw SVG text. "
        "SVG is rendered to PNG before upload. "
        "If recipe_json is omitted, server fetches recipe and reuses current values for update. "
        f"{TOKEN_HELP}"
    )
)
async def add_or_update_recipe_image_from_svg(
    recipe_id: int,
    svg_text: str,
    recipe_json: dict[str, Any] | None = None,
    token: str | None = None,
    output_width: int | None = 680,
    output_height: int | None = 680,
    image_filename: str = "recipe-from-svg.png",
) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    payload = await _resolve_recipe_payload_for_image_update(auth_token, recipe_id, recipe_json)

    if not svg_text.strip():
        raise CocktailPiApiError("svg_text must not be empty")

    try:
        png_bytes = cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            output_width=output_width,
            output_height=output_height,
        )
    except Exception as exc:
        raise CocktailPiApiError(f"Failed to render svg_text: {exc}") from exc

    result = await client.add_or_update_recipe_image_bytes(
        auth_token,
        recipe_id=recipe_id,
        recipe=payload,
        image_bytes=png_bytes,
        image_filename=image_filename,
        image_content_type="image/png",
    )
    _validate_owner_assignment(
        result,
        requested_owner_id=_as_positive_int(payload.get("ownerId")),
        auth_token=auth_token,
        operation="add_or_update_recipe_image_from_svg",
    )
    return result


@mcp.tool(description=f"Delete a CocktailPi recipe by id. {TOKEN_HELP}")
async def delete_recipe(recipe_id: int, token: str | None = None) -> dict[str, Any]:
    auth_token = _resolve_token(token)
    return await client.delete_recipe(auth_token, recipe_id)


@mcp.tool(description=f"List pumps and their currently configured ingredients. {TOKEN_HELP}")
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


@mcp.tool(
    description=(
        "List ingredients to help build recipe payloads, including valid ids and types. "
        f"{TOKEN_HELP}"
    )
)
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


@mcp.tool(description=f"List recipe categories. {TOKEN_HELP}")
async def list_categories(token: str | None = None) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    return await client.list_categories(auth_token)


@mcp.tool(description=f"List glasses. {TOKEN_HELP}")
async def list_glasses(token: str | None = None) -> list[dict[str, Any]]:
    auth_token = _resolve_token(token)
    return await client.list_glasses(auth_token)


def run() -> None:
    asyncio.run(_auto_login())
    mcp.run(transport="stdio")
