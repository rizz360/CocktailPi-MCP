from __future__ import annotations

import base64
import binascii
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
    # Keep concurrent requests bounded; CocktailPi usually runs on a Raspberry Pi.
    MAX_CONNECTIONS = 8

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=self.MAX_CONNECTIONS,
                    max_keepalive_connections=self.MAX_CONNECTIONS,
                ),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

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

    async def create_recipe(
        self,
        token: str,
        recipe: dict[str, Any],
        *,
        image_base64: str | None = None,
        image_bytes: bytes | None = None,
        image_filename: str = "recipe.jpg",
        image_content_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        multipart_form = {
            "recipe": (None, json.dumps(recipe), "application/json")
        }
        if image_base64 and image_bytes is not None:
            raise CocktailPiApiError("Provide either image_base64 or image_bytes, not both")
        if image_base64:
            multipart_form["image"] = self._build_image_part(
                image_base64=image_base64,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )
        elif image_bytes is not None:
            multipart_form["image"] = self._build_image_part_from_bytes(
                image_bytes=image_bytes,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )
        return await self._request(
            "POST",
            "/api/recipe/",
            token=token,
            files=multipart_form,
        )

    async def update_recipe(
        self,
        token: str,
        recipe_id: int,
        recipe: dict[str, Any],
        remove_image: bool = False,
        *,
        image_base64: str | None = None,
        image_bytes: bytes | None = None,
        image_filename: str = "recipe.jpg",
        image_content_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        multipart_form = {
            "recipe": (None, json.dumps(recipe), "application/json")
        }
        if image_base64 and image_bytes is not None:
            raise CocktailPiApiError("Provide either image_base64 or image_bytes, not both")
        if image_base64:
            multipart_form["image"] = self._build_image_part(
                image_base64=image_base64,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )
        elif image_bytes is not None:
            multipart_form["image"] = self._build_image_part_from_bytes(
                image_bytes=image_bytes,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )
        return await self._request(
            "PUT",
            f"/api/recipe/{recipe_id}",
            token=token,
            params={"removeImage": str(remove_image).lower()},
            files=multipart_form,
        )

    async def add_or_update_recipe_image(
        self,
        token: str,
        *,
        recipe_id: int,
        recipe: dict[str, Any],
        image_base64: str,
        image_filename: str = "recipe.jpg",
        image_content_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        return await self.update_recipe(
            token,
            recipe_id=recipe_id,
            recipe=recipe,
            remove_image=False,
            image_base64=image_base64,
            image_filename=image_filename,
            image_content_type=image_content_type,
        )

    async def delete_recipe_image(
        self,
        token: str,
        *,
        recipe_id: int,
        recipe: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.update_recipe(
            token,
            recipe_id=recipe_id,
            recipe=recipe,
            remove_image=True,
        )

    async def add_or_update_recipe_image_bytes(
        self,
        token: str,
        *,
        recipe_id: int,
        recipe: dict[str, Any],
        image_bytes: bytes,
        image_filename: str,
        image_content_type: str,
    ) -> dict[str, Any]:
        return await self.update_recipe(
            token,
            recipe_id=recipe_id,
            recipe=recipe,
            remove_image=False,
            image_bytes=image_bytes,
            image_filename=image_filename,
            image_content_type=image_content_type,
        )

    async def delete_recipe(self, token: str, recipe_id: int) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"/api/recipe/{recipe_id}",
            token=token,
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

    async def set_ingredient_in_bar(self, token: str, ingredient_id: int, in_bar: bool) -> dict[str, Any]:
        method = "PUT" if in_bar else "DELETE"
        await self._request(method, f"/api/ingredient/{ingredient_id}/bar", token=token)
        return {
            "ingredientId": ingredient_id,
            "inBar": in_bar,
            "status": "updated",
        }

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
            response = await self._http().request(
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

    def _build_image_part(
        self,
        *,
        image_base64: str,
        image_filename: str,
        image_content_type: str,
    ) -> tuple[str, bytes, str]:
        raw = image_base64.strip()
        if "," in raw and raw.lower().startswith("data:"):
            raw = raw.split(",", 1)[1]

        try:
            decoded = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CocktailPiApiError("image_base64 must be valid base64 data") from exc

        if not decoded:
            raise CocktailPiApiError("image_base64 decoded to empty payload")

        return (image_filename, decoded, image_content_type)

    def _build_image_part_from_bytes(
        self,
        *,
        image_bytes: bytes,
        image_filename: str,
        image_content_type: str,
    ) -> tuple[str, bytes, str]:
        if not image_bytes:
            raise CocktailPiApiError("image payload is empty")
        return (image_filename, image_bytes, image_content_type)


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
