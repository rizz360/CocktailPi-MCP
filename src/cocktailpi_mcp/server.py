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


def _extract_step_ingredients(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    production_steps = recipe.get("productionSteps")
    if not isinstance(production_steps, list):
        return []

    result: list[dict[str, Any]] = []
    for step in production_steps:
        if not isinstance(step, dict):
            continue
        step_ingredients = step.get("stepIngredients")
        if not isinstance(step_ingredients, list):
            continue
        for ingredient in step_ingredients:
            if isinstance(ingredient, dict):
                result.append(ingredient)
    return result


def _ingredient_type_label(step_ingredient: dict[str, Any]) -> str:
    candidates = [
        step_ingredient.get("ingredientType"),
        step_ingredient.get("type"),
    ]

    nested_ingredient = step_ingredient.get("ingredient")
    if isinstance(nested_ingredient, dict):
        candidates.append(nested_ingredient.get("ingredientType"))
        candidates.append(nested_ingredient.get("type"))

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _is_manual_ingredient(step_ingredient: dict[str, Any]) -> bool:
    label = _ingredient_type_label(step_ingredient)
    if not label:
        return False
    return "manual" in label


def _extract_ingredient_id(step_ingredient: dict[str, Any]) -> int | None:
    ingredient_id = _as_positive_int(step_ingredient.get("ingredientId"))
    if ingredient_id is not None:
        return ingredient_id

    ingredient_id = _as_positive_int(step_ingredient.get("id"))
    if ingredient_id is not None:
        return ingredient_id

    nested_ingredient = step_ingredient.get("ingredient")
    if isinstance(nested_ingredient, dict):
        ingredient_id = _as_positive_int(nested_ingredient.get("id"))
        if ingredient_id is not None:
            return ingredient_id

    return None


def _extract_ingredient_name(step_ingredient: dict[str, Any], fallback_id: int | None) -> str:
    candidates: list[Any] = [
        step_ingredient.get("ingredientName"),
        step_ingredient.get("name"),
    ]

    nested_ingredient = step_ingredient.get("ingredient")
    if isinstance(nested_ingredient, dict):
        candidates.append(nested_ingredient.get("name"))

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()

    if fallback_id is not None:
        return f"Ingredient #{fallback_id}"
    return "Unknown ingredient"


def _extract_group_chain_from_group_obj(
    group_obj: dict[str, Any],
    group_parent_map: dict[int, int],
) -> set[int]:
    chain: set[int] = set()

    current: dict[str, Any] | None = group_obj
    seen_ids: set[int] = set()
    while isinstance(current, dict):
        current_id = _as_positive_int(current.get("id"))
        if current_id is None:
            current_id = _as_positive_int(current.get("groupId"))
        if current_id is None:
            break
        if current_id in seen_ids:
            break

        seen_ids.add(current_id)
        chain.add(current_id)

        parent_id = _as_positive_int(current.get("parentGroupId"))
        parent_group = current.get("parentGroup")
        if parent_id is None and isinstance(parent_group, dict):
            parent_id = _as_positive_int(parent_group.get("id"))

        if parent_id is not None:
            group_parent_map.setdefault(current_id, parent_id)

        if isinstance(parent_group, dict):
            current = parent_group
            continue

        break

    return chain


def _collect_ingredient_group_ids(
    ingredient: dict[str, Any],
    group_parent_map: dict[int, int],
) -> set[int]:
    group_ids: set[int] = set()
    ingredient_id = _as_positive_int(ingredient.get("id"))

    direct_group_id = _as_positive_int(ingredient.get("groupId"))
    ingredient_group_id = _as_positive_int(ingredient.get("ingredientGroupId"))
    parent_group_id = _as_positive_int(ingredient.get("parentGroupId"))

    if direct_group_id is not None:
        group_ids.add(direct_group_id)
    if ingredient_group_id is not None:
        group_ids.add(ingredient_group_id)
    if parent_group_id is not None:
        group_ids.add(parent_group_id)

    if direct_group_id is not None and parent_group_id is not None:
        group_parent_map.setdefault(direct_group_id, parent_group_id)

    # Catalog rows often model both ingredients and groups via id + parentGroupId
    # without nested group objects. Keep this relation to enable ancestor expansion.
    if ingredient_id is not None and parent_group_id is not None:
        group_parent_map.setdefault(ingredient_id, parent_group_id)

    for key in ("group", "ingredientGroup", "parentGroup"):
        group_obj = ingredient.get(key)
        if isinstance(group_obj, dict):
            group_ids.update(_extract_group_chain_from_group_obj(group_obj, group_parent_map))

    return group_ids


def _expand_group_ids(group_ids: set[int], group_parent_map: dict[int, int]) -> set[int]:
    expanded = set(group_ids)
    for group_id in list(group_ids):
        current = group_id
        visited: set[int] = set()
        while True:
            if current in visited:
                break
            visited.add(current)

            parent = group_parent_map.get(current)
            if parent is None:
                break

            expanded.add(parent)
            current = parent
    return expanded


def _build_ingredient_indexes(
    ingredients: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, int]]:
    by_id: dict[int, dict[str, Any]] = {}
    group_parent_map: dict[int, int] = {}
    ingredient_group_ids: dict[int, set[int]] = {}

    for ingredient in ingredients:
        ingredient_id = _as_positive_int(ingredient.get("id"))
        group_ids = _collect_ingredient_group_ids(ingredient, group_parent_map)

        if ingredient_id is not None:
            by_id[ingredient_id] = ingredient
            ingredient_group_ids[ingredient_id] = group_ids

    for ingredient_id, group_ids in list(ingredient_group_ids.items()):
        ingredient_group_ids[ingredient_id] = _expand_group_ids(group_ids, group_parent_map)

    return by_id, ingredient_group_ids, group_parent_map


def _extract_step_ingredient_group_ids(
    step_ingredient: dict[str, Any],
    ingredient_group_ids: dict[int, set[int]],
    group_parent_map: dict[int, int],
    ingredient_id: int | None,
    ingredient_type: str,
) -> set[int]:
    group_ids: set[int] = set()

    for key in ("groupId", "ingredientGroupId", "parentGroupId"):
        group_id = _as_positive_int(step_ingredient.get(key))
        if group_id is not None:
            group_ids.add(group_id)

    nested_ingredient = step_ingredient.get("ingredient")
    if isinstance(nested_ingredient, dict):
        for key in ("groupId", "ingredientGroupId", "parentGroupId"):
            group_id = _as_positive_int(nested_ingredient.get(key))
            if group_id is not None:
                group_ids.add(group_id)

        nested_type = nested_ingredient.get("type")
        nested_type_label = nested_type.strip().lower() if isinstance(nested_type, str) else ""
        nested_id = _as_positive_int(nested_ingredient.get("id"))
        if "group" in nested_type_label and nested_id is not None:
            group_ids.add(nested_id)

        for key in ("group", "ingredientGroup", "parentGroup"):
            group_obj = nested_ingredient.get(key)
            if isinstance(group_obj, dict):
                group_ids.update(_extract_group_chain_from_group_obj(group_obj, group_parent_map))

    if ingredient_id is not None and ingredient_id in ingredient_group_ids:
        group_ids.update(ingredient_group_ids[ingredient_id])

    if "group" in ingredient_type and ingredient_id is not None:
        group_ids.add(ingredient_id)

    return _expand_group_ids(group_ids, group_parent_map)


def _describe_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        "ingredientId": requirement.get("ingredientId"),
        "ingredientName": requirement.get("ingredientName"),
        "ingredientType": requirement.get("ingredientType"),
        "groupIds": sorted(requirement.get("groupIds") or []),
    }


def _build_recipe_requirements(
    recipe: dict[str, Any],
    ingredient_group_ids: dict[int, set[int]],
    group_parent_map: dict[int, int],
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for step_ingredient in _extract_step_ingredients(recipe):
        if _is_manual_ingredient(step_ingredient):
            continue

        ingredient_id = _extract_ingredient_id(step_ingredient)
        ingredient_type = _ingredient_type_label(step_ingredient)
        ingredient_name = _extract_ingredient_name(step_ingredient, ingredient_id)
        group_ids = _extract_step_ingredient_group_ids(
            step_ingredient,
            ingredient_group_ids=ingredient_group_ids,
            group_parent_map=group_parent_map,
            ingredient_id=ingredient_id,
            ingredient_type=ingredient_type,
        )

        requirements.append(
            {
                "ingredientId": ingredient_id,
                "ingredientName": ingredient_name,
                "ingredientType": ingredient_type,
                "groupIds": group_ids,
            }
        )
    return requirements


def _build_pump_entries(
    pumps: list[dict[str, Any]],
    ingredient_group_ids: dict[int, set[int]],
    ingredient_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for pump in pumps:
        current = pump.get("currentIngredient")
        if not isinstance(current, dict):
            continue

        ingredient_id = _as_positive_int(current.get("id"))
        if ingredient_id is None:
            continue

        ingredient_name = current.get("name")
        if not isinstance(ingredient_name, str) or not ingredient_name.strip():
            known = ingredient_by_id.get(ingredient_id)
            candidate_name = known.get("name") if isinstance(known, dict) else None
            if isinstance(candidate_name, str) and candidate_name.strip():
                ingredient_name = candidate_name
            else:
                ingredient_name = f"Ingredient #{ingredient_id}"

        entries.append(
            {
                "pumpId": pump.get("id"),
                "pumpName": pump.get("name"),
                "ingredientId": ingredient_id,
                "ingredientName": ingredient_name,
                "coveredIngredientIds": {ingredient_id},
                "coveredGroupIds": set(ingredient_group_ids.get(ingredient_id, set())),
            }
        )

    return entries


def _matching_pumps_for_requirement(
    requirement: dict[str, Any],
    pump_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirement_ingredient_id = requirement.get("ingredientId")
    requirement_group_ids = requirement.get("groupIds") or set()

    matches: list[dict[str, Any]] = []
    for pump in pump_entries:
        covered_ingredient_ids = pump.get("coveredIngredientIds") or set()
        covered_group_ids = pump.get("coveredGroupIds") or set()

        ingredient_match = (
            isinstance(requirement_ingredient_id, int)
            and requirement_ingredient_id in covered_ingredient_ids
        )
        group_match = bool(set(requirement_group_ids) & set(covered_group_ids))

        if ingredient_match or group_match:
            matches.append(pump)

    return matches


def _evaluate_recipes_against_pumps(
    recipes: list[dict[str, Any]],
    requirements_by_recipe_id: dict[int, list[dict[str, Any]]],
    pump_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    fully_automatable: set[int] = set()
    missing_by_recipe_id: dict[int, list[dict[str, Any]]] = {}
    recipe_to_pump_usage: dict[int, set[int]] = {}

    for recipe in recipes:
        recipe_id = _as_positive_int(recipe.get("id"))
        if recipe_id is None:
            continue

        requirements = requirements_by_recipe_id.get(recipe_id, [])
        missing: list[dict[str, Any]] = []
        used_pump_ids: set[int] = set()

        for requirement in requirements:
            matching_pumps = _matching_pumps_for_requirement(requirement, pump_entries)

            if not matching_pumps:
                missing.append(_describe_requirement(requirement))
                continue

            for pump in matching_pumps:
                pump_id = _as_positive_int(pump.get("pumpId"))
                if pump_id is not None:
                    used_pump_ids.add(pump_id)

        if missing:
            missing_by_recipe_id[recipe_id] = missing
            continue

        fully_automatable.add(recipe_id)
        recipe_to_pump_usage[recipe_id] = used_pump_ids

    return {
        "fullyAutomatableRecipeIds": fully_automatable,
        "missingByRecipeId": missing_by_recipe_id,
        "recipeToPumpUsage": recipe_to_pump_usage,
    }


async def _fetch_all_recipe_details(
    auth_token: str,
    *,
    owner_id: int | None,
    in_collection: int | None,
    in_category: int | None,
    search_name: str | None,
    fabricable: str,
    order_by: str,
) -> tuple[list[dict[str, Any]], int, int]:
    first_page = await client.list_recipes(
        auth_token,
        page=0,
        owner_id=owner_id,
        in_collection=in_collection,
        in_category=in_category,
        search_name=search_name,
        fabricable=fabricable,
        order_by=order_by,
    )

    total_pages = first_page.get("totalPages")
    total_elements = first_page.get("totalElements")

    if not isinstance(total_pages, int) or total_pages < 1:
        total_pages = 1
    if not isinstance(total_elements, int) or total_elements < 0:
        total_elements = 0

    content0 = first_page.get("content")
    recipe_ids: list[int] = []
    if isinstance(content0, list):
        for recipe in content0:
            if isinstance(recipe, dict):
                recipe_id = _as_positive_int(recipe.get("id"))
                if recipe_id is not None:
                    recipe_ids.append(recipe_id)

    for page in range(1, total_pages):
        page_payload = await client.list_recipes(
            auth_token,
            page=page,
            owner_id=owner_id,
            in_collection=in_collection,
            in_category=in_category,
            search_name=search_name,
            fabricable=fabricable,
            order_by=order_by,
        )
        content = page_payload.get("content")
        if not isinstance(content, list):
            continue

        for recipe in content:
            if isinstance(recipe, dict):
                recipe_id = _as_positive_int(recipe.get("id"))
                if recipe_id is not None:
                    recipe_ids.append(recipe_id)

    unique_recipe_ids = sorted(set(recipe_ids))
    details_tasks = [
        client.get_recipe(auth_token, recipe_id, is_ingredient=False)
        for recipe_id in unique_recipe_ids
    ]
    details = await asyncio.gather(*details_tasks)

    return details, total_pages, total_elements


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


@mcp.tool(
    description=(
        "Analyze pump ingredient optimization across all recipes. "
        "A recipe is fully automatable only when every non-manual step ingredient is "
        "covered by configured pumps via direct ingredient id match or ingredient group/ancestor match. "
        "Also simulates one-pump replacement options and returns the best replacement ingredient "
        "(not currently on a pump) that unlocks the most new fully automatable recipes. "
        f"{TOKEN_HELP}"
    )
)
async def analyze_pump_ingredient_optimization(
    token: str | None = None,
    owner_id: int | None = None,
    in_collection: int | None = None,
    in_category: int | None = None,
    search_name: str | None = None,
    fabricable: str = "all",
    order_by: str = "name",
    expected_total_pages: int | None = None,
    expected_total_recipes: int | None = None,
) -> dict[str, Any]:
    auth_token = _resolve_token(token)

    pumps_task = client.list_pumps(auth_token)
    ingredients_task = client.list_ingredients(auth_token, in_bar_or_on_pump=False)
    recipes_task = _fetch_all_recipe_details(
        auth_token,
        owner_id=owner_id,
        in_collection=in_collection,
        in_category=in_category,
        search_name=search_name,
        fabricable=fabricable,
        order_by=order_by,
    )

    pumps, ingredients, recipe_details_result = await asyncio.gather(
        pumps_task,
        ingredients_task,
        recipes_task,
    )
    recipes, total_pages, total_elements = recipe_details_result

    if expected_total_pages is not None and expected_total_pages != total_pages:
        raise CocktailPiApiError(
            f"Expected total pages={expected_total_pages}, but API returned total pages={total_pages}."
        )

    if expected_total_recipes is not None and expected_total_recipes != total_elements:
        raise CocktailPiApiError(
            "Expected total recipes="
            f"{expected_total_recipes}, but API returned total recipes={total_elements}."
        )

    ingredient_by_id, ingredient_group_ids, group_parent_map = _build_ingredient_indexes(ingredients)
    pump_entries = _build_pump_entries(pumps, ingredient_group_ids, ingredient_by_id)

    recipes_by_id: dict[int, dict[str, Any]] = {}
    requirements_by_recipe_id: dict[int, list[dict[str, Any]]] = {}
    for recipe in recipes:
        recipe_id = _as_positive_int(recipe.get("id"))
        if recipe_id is None:
            continue

        recipes_by_id[recipe_id] = recipe
        requirements_by_recipe_id[recipe_id] = _build_recipe_requirements(
            recipe,
            ingredient_group_ids=ingredient_group_ids,
            group_parent_map=group_parent_map,
        )

    filtered_recipes = [recipes_by_id[recipe_id] for recipe_id in sorted(recipes_by_id)]
    current_eval = _evaluate_recipes_against_pumps(
        filtered_recipes,
        requirements_by_recipe_id=requirements_by_recipe_id,
        pump_entries=pump_entries,
    )

    fully_automatable_recipe_ids = set(current_eval["fullyAutomatableRecipeIds"])
    missing_by_recipe_id = current_eval["missingByRecipeId"]
    recipe_to_pump_usage = current_eval["recipeToPumpUsage"]

    pump_usage_rows: list[dict[str, Any]] = []
    for pump in pump_entries:
        pump_id = _as_positive_int(pump.get("pumpId"))
        if pump_id is None:
            continue

        matching_recipe_ids = sorted(
            recipe_id
            for recipe_id in fully_automatable_recipe_ids
            if pump_id in recipe_to_pump_usage.get(recipe_id, set())
        )

        recipes_using_pump_ids: list[int] = []
        for recipe in filtered_recipes:
            recipe_id = _as_positive_int(recipe.get("id"))
            if recipe_id is None:
                continue

            requirements = requirements_by_recipe_id.get(recipe_id, [])
            uses_pump = False
            for requirement in requirements:
                matching_pumps = _matching_pumps_for_requirement(requirement, pump_entries)
                if any(_as_positive_int(p.get("pumpId")) == pump_id for p in matching_pumps):
                    uses_pump = True
                    break

            if uses_pump:
                recipes_using_pump_ids.append(recipe_id)

        pump_usage_rows.append(
            {
                "pumpId": pump_id,
                "pumpName": pump.get("pumpName"),
                "ingredientId": pump.get("ingredientId"),
                "ingredientName": pump.get("ingredientName"),
                "fullyAutomatableRecipeCount": len(matching_recipe_ids),
                "recipeIds": matching_recipe_ids,
                "recipesUsingPumpIngredientCount": len(recipes_using_pump_ids),
                "recipesUsingPumpIngredientIds": sorted(recipes_using_pump_ids),
            }
        )

    pump_usage_rows.sort(
        key=lambda row: (
            int(row.get("fullyAutomatableRecipeCount") or 0),
            str(row.get("pumpName") or ""),
        )
    )

    least_used = pump_usage_rows[0] if pump_usage_rows else None

    current_pump_ingredient_ids = {
        _as_positive_int(pump.get("ingredientId"))
        for pump in pump_entries
        if _as_positive_int(pump.get("ingredientId")) is not None
    }

    candidate_ingredients: list[dict[str, Any]] = []
    for ingredient in ingredients:
        ingredient_id = _as_positive_int(ingredient.get("id"))
        if ingredient_id is None:
            continue
        if ingredient_id in current_pump_ingredient_ids:
            continue
        candidate_ingredients.append(ingredient)

    baseline_ids = set(fully_automatable_recipe_ids)
    best_replacement: dict[str, Any] | None = None
    best_new_unlock_count = -1

    for pump_index, existing_pump in enumerate(pump_entries):
        simulated_base = [dict(pump) for pump in pump_entries]

        for candidate in candidate_ingredients:
            candidate_id = _as_positive_int(candidate.get("id"))
            if candidate_id is None:
                continue

            candidate_name = candidate.get("name")
            if not isinstance(candidate_name, str) or not candidate_name.strip():
                candidate_name = f"Ingredient #{candidate_id}"

            simulated_pumps = [dict(pump) for pump in simulated_base]
            simulated_pumps[pump_index] = {
                "pumpId": existing_pump.get("pumpId"),
                "pumpName": existing_pump.get("pumpName"),
                "ingredientId": candidate_id,
                "ingredientName": candidate_name,
                "coveredIngredientIds": {candidate_id},
                "coveredGroupIds": set(ingredient_group_ids.get(candidate_id, set())),
            }

            simulated_eval = _evaluate_recipes_against_pumps(
                filtered_recipes,
                requirements_by_recipe_id=requirements_by_recipe_id,
                pump_entries=simulated_pumps,
            )
            simulated_full_ids = set(simulated_eval["fullyAutomatableRecipeIds"])
            newly_unlocked_ids = sorted(simulated_full_ids - baseline_ids)

            new_unlock_count = len(newly_unlocked_ids)
            if new_unlock_count < best_new_unlock_count:
                continue

            newly_unlocked_rows: list[dict[str, Any]] = []
            for recipe_id in newly_unlocked_ids:
                recipe_obj = recipes_by_id.get(recipe_id, {})
                newly_unlocked_rows.append(
                    {
                        "id": recipe_id,
                        "name": recipe_obj.get("name"),
                        "missingBefore": missing_by_recipe_id.get(recipe_id, []),
                        "missingAfter": simulated_eval["missingByRecipeId"].get(recipe_id, []),
                    }
                )

            still_blocked_rows: list[dict[str, Any]] = []
            affected_recipe_ids = sorted(
                recipe_id
                for recipe_id in missing_by_recipe_id
                if recipe_id not in newly_unlocked_ids
            )
            for recipe_id in affected_recipe_ids:
                remaining = simulated_eval["missingByRecipeId"].get(recipe_id)
                if not remaining:
                    continue

                before_missing = missing_by_recipe_id.get(recipe_id, [])
                if len(remaining) >= len(before_missing):
                    continue

                recipe_obj = recipes_by_id.get(recipe_id, {})
                still_blocked_rows.append(
                    {
                        "id": recipe_id,
                        "name": recipe_obj.get("name"),
                        "missingBefore": before_missing,
                        "missingAfter": remaining,
                    }
                )

            replacement_result = {
                "replacePump": {
                    "pumpId": existing_pump.get("pumpId"),
                    "pumpName": existing_pump.get("pumpName"),
                    "ingredientId": existing_pump.get("ingredientId"),
                    "ingredientName": existing_pump.get("ingredientName"),
                },
                "replacementIngredient": {
                    "id": candidate_id,
                    "name": candidate_name,
                },
                "newFullyAutomatableRecipeCount": new_unlock_count,
                "newlyUnlockedRecipes": newly_unlocked_rows,
                "affectedButStillBlocked": still_blocked_rows,
            }

            is_better = new_unlock_count > best_new_unlock_count
            is_tie_with_better_name = (
                new_unlock_count == best_new_unlock_count
                and best_replacement is not None
                and str(candidate_name).lower()
                < str(best_replacement["replacementIngredient"]["name"]).lower()
            )

            if best_replacement is None or is_better or is_tie_with_better_name:
                best_replacement = replacement_result
                best_new_unlock_count = new_unlock_count

    blocked_recipe_rows = [
        {
            "id": recipe_id,
            "name": recipes_by_id.get(recipe_id, {}).get("name"),
            "missingIngredients": missing_items,
        }
        for recipe_id, missing_items in sorted(missing_by_recipe_id.items())
    ]

    return {
        "summary": {
            "recipesFetched": len(filtered_recipes),
            "totalPages": total_pages,
            "totalRecipesFromApi": total_elements,
            "configuredPumpCount": len(pump_entries),
            "fullyAutomatableRecipeCount": len(fully_automatable_recipe_ids),
            "blockedRecipeCount": len(missing_by_recipe_id),
        },
        "pumpUsage": pump_usage_rows,
        "leastUsedPumpIngredient": least_used,
        "bestReplacement": best_replacement,
        "fullyAutomatableRecipeIds": sorted(fully_automatable_recipe_ids),
        "blockedRecipes": blocked_recipe_rows,
    }


def run() -> None:
    asyncio.run(_auto_login())
    mcp.run(transport="stdio")
