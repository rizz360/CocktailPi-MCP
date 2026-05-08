# Advanced Reference

This page contains deeper technical details that are not required for first-time setup.

## Tool reference

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

## CocktailPi API mapping

This MCP server calls these CocktailPi endpoints:
- `POST /api/auth/login`
- `GET /api/recipe/`
- `GET /api/recipe/{id}`
- `POST /api/recipe/` (multipart with `recipe` part)
- `PUT /api/recipe/{id}` (multipart with `recipe` part)
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
