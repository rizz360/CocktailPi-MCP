# Advanced Reference

This page contains deeper technical details that are not required for first-time setup.

## Tool reference

Authentication behavior:
- Every tool's `token` parameter is optional.
- If `token` is omitted, server uses configured `COCKTAILPI_ACCESS_TOKEN` or startup auto-login token.
- `login` is only required when you need to fetch/refresh a token explicitly.

Core operations:
- `list_recipes`: list recipes/cocktails
- `create_recipe`: create a new recipe
- `update_recipe`: update an existing recipe
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

## CocktailPi API mapping

This MCP server calls these CocktailPi endpoints:
- `POST /api/auth/login`
- `GET /api/recipe/`
- `GET /api/recipe/{id}`
- `POST /api/recipe/` (multipart with `recipe` and optional `image` part)
- `PUT /api/recipe/{id}` (multipart with `recipe` and optional `image` part, supports `removeImage=true`)
- `DELETE /api/recipe/{id}`
- `GET /api/pump/`
- `GET /api/ingredient/`
- `GET /api/category/`
- `GET /api/glass/`

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

Common gotchas when creating/updating recipes:
- Use `categoryIds` (not `categories`) and include it even if empty (`[]`).
- Include `ownerId` explicitly.
- Ingredient entries must be flat fields like `ingredientId` and `ingredientType` (not nested ingredient object).

## Image operations

For image add/update/remove, CocktailPi currently uses recipe create/update multipart endpoints.

- `create_recipe` accepts optional:
  - `image_base64`: base64 payload (raw base64 or data URL)
  - `image_filename`: defaults to `recipe.jpg`
  - `image_content_type`: defaults to `image/jpeg`
- `update_recipe` accepts the same image fields plus `remove_image=true`.
- `add_or_update_recipe_image` wraps update behavior for explicit image updates.
- `add_or_update_recipe_image_from_url` fetches image server-side from URL and uploads bytes.
- `add_or_update_recipe_image_from_svg` renders SVG text to PNG server-side and uploads bytes.
- `delete_recipe_image` wraps update behavior with `remove_image=true`.

Image tool payload behavior:
- `recipe_json` is optional for `add_or_update_recipe_image`, `add_or_update_recipe_image_from_url`, and `delete_recipe_image`.
- When omitted, MCP fetches the current recipe and reuses it as update payload.
- If auto-derived payload cannot determine required fields like `ownerId`, pass `recipe_json` explicitly.
