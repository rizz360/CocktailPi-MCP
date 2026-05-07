from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx


class CocktailPiApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class CocktailPiLoginResult:
    access_token: str
    token_type: str
    token_expiration: str | None
    user: dict[str, Any] | None


class CocktailPiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def login(self, username: str, password: str, remember: bool = True) -> CocktailPiLoginResult:
        payload = {
            "username": username,
            "password": password,
            "remember": remember,
        }
        data = await self._request("POST", "/api/auth/login", json=payload, token=None)
        token = data.get("accessToken")
        if not token:
            raise CocktailPiApiError("Backend login succeeded but did not return accessToken")

        return CocktailPiLoginResult(
            access_token=token,
            token_type=data.get("tokenType", "Bearer"),
            token_expiration=data.get("tokenExpiration"),
            user=data.get("user"),
        )

    async def list_recipes(
        self,
        token: str,
        *,
        page: int = 0,
        owner_id: int | None = None,
        in_collection: int | None = None,
        in_category: int | None = None,
        search_name: str | None = None,
        fabricable: str = "all",
        order_by: str = "name",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "fabricable": fabricable,
            "orderBy": order_by,
        }
        if owner_id is not None:
            params["ownerId"] = owner_id
        if in_collection is not None:
            params["inCollection"] = in_collection
        if in_category is not None:
            params["inCategory"] = in_category
        if search_name:
            params["searchName"] = search_name

        return await self._request("GET", "/api/recipe/", token=token, params=params)

    async def get_recipe(self, token: str, recipe_id: int, is_ingredient: bool = False) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/recipe/{recipe_id}",
            token=token,
            params={"isIngredient": str(is_ingredient).lower()},
        )

    async def create_recipe(self, token: str, recipe: dict[str, Any]) -> dict[str, Any]:
        multipart_form = {
            "recipe": (None, json.dumps(recipe), "application/json")
        }
        return await self._request(
            "POST",
            "/api/recipe/",
            token=token,
            files=multipart_form,
        )

    async def list_pumps(self, token: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/pump/", token=token)
        if not isinstance(data, list):
            raise CocktailPiApiError("Unexpected pump response format")
        return data

    async def list_ingredients(
        self,
        token: str,
        *,
        autocomplete: str | None = None,
        in_bar_or_on_pump: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"inBarOrOnPump": str(in_bar_or_on_pump).lower()}
        if autocomplete:
            params["autocomplete"] = autocomplete
        data = await self._request("GET", "/api/ingredient/", token=token, params=params)
        if not isinstance(data, list):
            raise CocktailPiApiError("Unexpected ingredient response format")
        return data

    async def list_categories(self, token: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/category/", token=token)
        if not isinstance(data, list):
            raise CocktailPiApiError("Unexpected category response format")
        return data

    async def list_glasses(self, token: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/glass/", token=token)
        if not isinstance(data, list):
            raise CocktailPiApiError("Unexpected glass response format")
        return data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self._base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    files=files,
                )
        except httpx.HTTPError as exc:
            raise CocktailPiApiError(f"Request to CocktailPi failed: {exc}") from exc

        if response.status_code >= 400:
            detail = _extract_error_detail(response)
            raise CocktailPiApiError(
                f"CocktailPi API error {response.status_code} on {path}: {detail}"
            )

        if not response.content:
            return {"ok": True}

        try:
            return response.json()
        except ValueError as exc:
            raise CocktailPiApiError("CocktailPi returned non-JSON response") from exc


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text or "No error payload"

    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(body)
