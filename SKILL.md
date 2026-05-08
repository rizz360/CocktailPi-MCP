# CocktailPi MCP Skill Guide

This quick guide helps AI clients call CocktailPi MCP tools correctly on first try.

## Authentication

- Every tool's token parameter is optional.
- If token is omitted, server falls back to configured COCKTAILPI_ACCESS_TOKEN or startup auto-login token.
- Use login only when you explicitly need a fresh token.

## Recipe write rules

- For recipe_json, include ownerId.
- Use categoryIds (not categories) and include it even if empty ([]).
- In ingredient steps, use flat fields ingredientId and ingredientType (not nested ingredient object).
- ingredientType values are backend-defined; copy one from an existing recipe via get_recipe.

## Minimal working create_recipe payload

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

## Image operations

- create_recipe and update_recipe support optional image_base64.
- image_base64 can be raw base64 bytes or a data URL (for example data:image/png;base64,...).
- add_or_update_recipe_image: explicit image add/replace helper.
- delete_recipe_image: explicit image removal helper.
- Image changes still require valid recipe_json because backend uses recipe update DTO validation.
