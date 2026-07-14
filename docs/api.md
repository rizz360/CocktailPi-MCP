# CocktailPi API Reference

This document describes the CocktailPi backend's HTTP REST API and STOMP-over-WebSocket
push API, reverse-engineered from the Spring Boot backend source
(`backend/src/main/java/net/alex9849/cocktailpi/`). It is intended as a stable reference
for building clients — e.g. a Home Assistant custom integration — against a running
CocktailPi instance.

Reference points into the source are given as `file:line` so this doc can be re-verified
against a newer version of the backend if endpoints change.

## Contents

- [Basics](#basics)
- [Authentication](#authentication)
- [REST Endpoints](#rest-endpoints)
  - [Auth](#auth---apiauth)
  - [Recipe](#recipe---apirecipe)
  - [Cocktail (ordering / production)](#cocktail---apicocktail)
  - [Pump](#pump---apipump)
  - [Pump settings](#pump-settings---apipumpsettings)
  - [Ingredient](#ingredient---apiingredient)
  - [Category](#category---apicategory)
  - [Glass](#glass---apiglass)
  - [Collection](#collection---apicollection)
  - [GPIO](#gpio---apigpio)
  - [Event action](#event-action---apieventaction)
  - [User](#user---apiuser)
  - [System](#system---apisystem)
  - [Transfer (import/export)](#transfer---apitransfer)
- [WebSocket (real-time push) API](#websocket-real-time-push-api)
- [Roles / permission model](#roles--permission-model)
- [Key domain model notes](#key-domain-model-notes)

## Basics

- Base path prefix: **`/api/`** for all REST endpoints (trailing slash on controller base paths, but works without it too).
- Default port: `80` in the production profile (`application-prod.properties:2`); `8080` in dev. Check the actual deployment — the official Docker image / HA add-on typically exposes port `80` (or whatever host port it's mapped to).
- Content type: JSON for almost everything. A few endpoints (recipe/ingredient/collection/event-action create & update, and image uploads) use `multipart/form-data` with a `recipe`/`ingredient`/`collection`/`eventAction` JSON part plus an optional `image`/`file` part.
- Images are served as raw `image/jpeg` bytes directly from `GET .../{id}/image` endpoints (no JSON wrapper).
- No API versioning scheme (no `/v1/` etc.) — the API evolves in place.
- **Trailing-slash gotcha**: the backend runs Spring Boot `3.5.13` (`pom.xml:9`), whose Spring Framework 6
  default is *strict* trailing-slash matching (no automatic `/x` ↔ `/x/` equivalence, unlike older Spring
  Boot 2 defaults) and this project doesn't override that. Several controllers declare their class-level
  `@RequestMapping` **with** a trailing slash and map their list/create method to `""`, meaning the
  effective path **requires** the trailing slash or the request 404s. Confirmed affected endpoints — always
  call these with a trailing `/`:
  `GET/POST /api/pump/`, `GET/POST /api/recipe/`, `GET/POST /api/category/`, `GET/POST /api/glass/`,
  `GET/POST /api/ingredient/`, `GET/POST /api/collection/`, `GET/POST /api/user/`, `GET/POST /api/gpio/`,
  `GET/POST /api/eventaction/`, `DELETE /api/cocktail/` (cancel). Endpoints with a path variable or a
  non-empty subpath (`/api/pump/{id}`, `/api/pump/start`, `/api/auth/login`, etc.) are unaffected either way.
- No CORS restrictions on origin (`WebConfig.java:11-14` — `allowedMethods` for `GET,POST,OPTIONS,PUT,DELETE,PATCH` on `/**`, no domain restriction), but CSRF/session are irrelevant since auth is JWT-bearer and stateless.
- No OpenAPI/Swagger is set up in this codebase; this document is the closest thing to a spec.

## Authentication

CocktailPi uses **stateless JWT bearer authentication** (`WebSecurityConfig.java`:
`SessionCreationPolicy.STATELESS`, CSRF disabled).

1. **Login** — `POST /api/auth/login`
   ```json
   { "username": "admin", "password": "hunter2", "remember": true }
   ```
   Response (`JwtResponse`, `payload/response/JwtResponse.java`):
   ```json
   {
     "accessToken": "<jwt>",
     "tokenExpiration": "2026-07-06T12:00:00.000+00:00",
     "tokenType": "Bearer",
     "user": { "...": "UserDto.Response.Detailed" }
   }
   ```
   `remember: true` extends the token's expiration (see `JwtUtils.isRemember`/`generateJwtToken`).

2. **Use the token** — send it on every subsequent request as:
   ```
   Authorization: Bearer <jwt>
   ```
   (`AuthTokenFilter.java:32` calls `jwtUtils.parseJwt(request.getHeader("Authorization"))`, which strips
   the `Bearer ` prefix — sending just the raw token also works but `Bearer <jwt>` is the documented form.)

3. **Refresh** — `GET /api/auth/refreshToken` with the current (still-valid) token in the `Authorization`
   header returns a new `JwtResponse` with a renewed expiration, preserving the original `remember` flag.

4. **Change "password only" mode** — `PUT /api/auth/passwordOnly` (ADMIN only) — body `{"passwordOnly": true}`;
   toggles a mode where login only requires a password (no username), useful for kiosk-style setups.

Unauthenticated endpoints (`WebSecurityConfig.java:55-65`):
- `OPTIONS *` (CORS preflight)
- `/websocket/**` (the WS handshake itself; STOMP frames are separately authorized, see below)
- `/api/auth/**` except `/api/auth/refreshToken` (which requires auth)
- `GET /api/recipe/*/image`, `GET /api/collection/*/image`, `GET /api/ingredient/*/image`
- `GET /api/system/settings/appearance`
- `GET /api/system/version`
- Everything else under `/api/**` requires a valid bearer token.
- Non-`/api/**` paths are permitted (serves the Angular frontend).

## REST Endpoints

Unless noted "(no auth)", every endpoint below requires `Authorization: Bearer <jwt>`.
Method-level authority requirements are noted per-endpoint; see [Roles](#roles--permission-model).

### Auth — `/api/auth`
(`endpoints/AuthEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/api/auth/login` | none | `LoginRequest {username, password, remember}` | `JwtResponse` (200) or 401 `"Invalid login data"` |
| GET | `/api/auth/refreshToken` | authenticated | — (uses `Authorization` header) | `JwtResponse` |
| PUT | `/api/auth/passwordOnly` | ADMIN | `{"passwordOnly": bool}` | `boolean` (new state) |

### Recipe — `/api/recipe`
(`endpoints/RecipeEndpoint.java`)

| Method | Path | Auth | Params / Body | Response |
|---|---|---|---|---|
| GET | `/api/recipe` | authenticated | Query: `ownerId`, `inCollection`, `fabricable` (`all`\|`manual`\|`auto`, default `all`), `containsIngredients` (Long[]), `searchName`, `inCategory`, `page` (default 0), `orderBy` (`name`\|`nameDesc`\|`lastUpdateAsc`\|`lastUpdateDesc`) | Spring `Page<RecipeDto.Response.SearchResult>` (JSON page envelope: `content`, `totalElements`, `totalPages`, ...) |
| GET | `/api/recipe/{id}` | authenticated | Query: `isIngredient` (bool, default false) | `RecipeDto.Response.Detailed` or 404 |
| GET | `/api/recipe/ingredient/{id}` | authenticated | — | `RecipeDto.Response.Detailed` (ingredient-recipe variant) or 404 |
| GET | `/api/recipe/ingredient` | authenticated | — | `IngredientRecipeDto.Response.SearchResult[]` — currently fabricable "ingredient recipes" |
| POST | `/api/recipe` | RECIPE_CREATOR | multipart: `recipe` = `RecipeDto.Request.Create`, `image` (optional file) | 201 `RecipeDto.Response.Detailed`, `Location` header |
| PUT | `/api/recipe/{id}` | RECIPE_CREATOR + must own recipe (or ADMIN) | multipart: `recipe`, `image` (optional), query `removeImage` (bool) | 200, or 403/404 |
| GET | `/api/recipe/{id}/image` | none | Query: `isIngredient`, `width` (px, resizes preserving 16:9) | raw `image/jpeg` or 404 |
| DELETE | `/api/recipe/{id}` | RECIPE_CREATOR + must own (or ADMIN) | — | 200/403/404 |

`RecipeDto.Request.Create` body shape (`payload/dto/recipe/RecipeDto.java:48-56`):
```json
{
  "name": "Mojito",
  "ownerId": 1,
  "description": "...",
  "productionSteps": [ "ProductionStepDto.Request.Create, see below" ],
  "categoryIds": [1, 2],
  "defaultGlassId": 3
}
```

`RecipeDto.Response.Detailed` shape (`RecipeDto.java:77-124`):
```json
{
  "id": 1, "name": "Mojito", "normalName": "mojito", "ownerId": 1, "ownerName": "admin",
  "boostable": true, "description": "...",
  "productionSteps": [ "ProductionStepDto.Response.Detailed" ],
  "categories": [ {"id": 1, "name": "Classics"} ],
  "hasImage": true,
  "defaultGlass": {"id": 3, "name": "Highball", "size": 350, "emptyWeight": 200, "isDefault": true, "isUseForSingleIngredients": false},
  "lastUpdate": "2026-01-01T00:00:00.000+00:00",
  "minAlcoholContent": 8, "maxAlcoholContent": 12,
  "type": "recipe"
}
```
(Ingredient-recipes get `"type": "ingredient-recipe"` via `IngredientRecipeDto` subclass — check the actual `type` field value in a live response.)

`RecipeDto.Response.SearchResult` (list view, `RecipeDto.java:127-164`) — lighter weight, includes `ingredients: IngredientDto.Response.Reduced[]` instead of full production steps.

### Cocktail — `/api/cocktail`
(`endpoints/CocktailEndpoint.java`) — this is the "order a drink" / production-control API, most relevant for a Home Assistant integration.

| Method | Path | Auth | Params / Body | Response |
|---|---|---|---|---|
| PUT | `/api/cocktail/{recipeId}` | authenticated | Query `isIngredient` (bool); Body `CocktailOrderConfigurationDto.Request.Create` | 202 Accepted (production starts asynchronously — track via WebSocket) |
| PUT | `/api/cocktail/tare` | authenticated | — | 200, or 404 if no load cell configured |
| PUT | `/api/cocktail/{recipeId}/feasibility` | authenticated | Same body as order | `FeasibilityReportDto.Response.Detailed` — whether the drink can currently be made (missing ingredients, insufficient filling level, etc.) |
| DELETE | `/api/cocktail` | authenticated | — | Cancels the current cocktail order; 403 if not your own order (unless ADMIN); 404 if none in progress |
| POST | `/api/cocktail/continueproduction` | authenticated | — | 202 — resumes production after a `MANUAL_ACTION_REQUIRED`/manual-ingredient-add pause |

`FeasibilityReportDto.Response.Detailed` (`payload/dto/cocktail/FeasibilityReportDto.java`) — the response of the `/feasibility` check:
```json
{
  "isFeasible": true,
  "failNoGlass": false,
  "allIngredientGroupsReplaced": true,
  "totalAmountInMl": 350,
  "totalPrice": 4.20,
  "ingredientGroupReplacements": [ {"ingredientGroup": "IngredientGroupDto.Response.Reduced", "selectedReplacement": "AddableIngredientDto.Response.Detailed or null"} ],
  "requiredIngredients": [ {"ingredient": "IngredientDto.Response.Detailed", "amountRequired": 50, "amountMissing": 0} ]
}
```
`isFeasible` is only true when `!failNoGlass && allIngredientGroupsReplaced &&` every `requiredIngredients[].amountMissing == 0` — check this field directly rather than re-deriving it client-side.

`CocktailOrderConfigurationDto.Request.Create` body (`payload/dto/cocktail/CocktailOrderConfigurationDto.java`):
```json
{
  "amountOrderedInMl": 350,
  "ingredientGroupReplacements": [ {"ingredientGroupId": 1, "ingredientId": 5} ],
  "customisations": {
    "boost": 0,
    "additionalIngredients": [ {"ingredientId": 7, "amount": 20} ]
  }
}
```
`amountOrderedInMl` is optional — if omitted, the endpoint defaults it to the recipe's default glass size.

Only one cocktail can be in production at a time system-wide; ordering while another user's cocktail is in
progress will queue/reject depending on service logic — poll/subscribe to `CocktailProgress` (WebSocket) to know current state.

### Pump — `/api/pump`
(`endpoints/PumpEndpoint.java`) — the second most relevant area for Home Assistant (expose as switches/sensors per pump).

| Method | Path | Auth | Params / Body | Response |
|---|---|---|---|---|
| GET | `/api/pump` | authenticated | — | `PumpDto.Response.Detailed[]` (all configured pumps) |
| GET | `/api/pump/{id}` | authenticated | — | `PumpDto.Response.Detailed` or 404 |
| POST | `/api/pump` | SUPER_ADMIN | `PumpDto.Request.Create` (polymorphic, see below) | 201, `Location` header |
| PATCH | `/api/pump/{id}` | PUMP_INGREDIENT_EDITOR | `PumpDto.Request.Create` partial — field-level authority gating (see note) | `PumpDto.Response.Detailed` |
| DELETE | `/api/pump/{id}` | SUPER_ADMIN | — | 200/404 |
| PUT | `/api/pump/{id}/pumpup` | PUMP_INGREDIENT_EDITOR | — | 201, body = `jobId` (long); triggers a `PUMP_UP` job (primes the tube) |
| PUT | `/api/pump/{id}/pumpback` | PUMP_INGREDIENT_EDITOR | — | 201, body = `jobId`; triggers `PUMP_DOWN` (empties the tube back) |
| PUT | `/api/pump/{id}/runjob` | ADMIN | `PumpAdvice {type, amount}` | 201, body = `jobId`; arbitrary job dispatch (see `PumpAdvice.Type` below) |
| PUT | `/api/pump/start` | PUMP_INGREDIENT_EDITOR | Query `id` (optional — omit to start **all** pumps) | 200 (all) or 201 + `jobId` (single); starts continuous `RUN` |
| PUT | `/api/pump/stop` | PUMP_INGREDIENT_EDITOR | Query `id` (optional — omit to stop **all** pumps) | 200/404 |
| GET | `/api/pump/jobmetrics/{id}` | PUMP_INGREDIENT_EDITOR | — | `JobMetrics` or 404 |

`PumpAdvice.Type` enum (`model/pump/PumpAdvice.java:8`): `RUN`, `PUMP_UP`, `PUMP_DOWN`, `PUMP_ML`, `PUMP_TIME`, `PUMP_STEPS`.
`PumpAdvice` body: `{"type": "PUMP_ML", "amount": 50}` — `amount` semantics depend on `type` (ml, ms, or steps).

`PumpDto.Response.Detailed` (`payload/dto/pump/PumpDto.java:102-134`) — polymorphic on `"type"`: `"dc"`, `"stepper"`, or `"valve"` (subtypes add pump-type-specific fields like `timePerClInMs` for DC or `stepsPerCl` for stepper):
```json
{
  "type": "dc",
  "id": 1, "name": "Vodka pump", "printName": "Vodka pump",
  "tubeCapacityInMl": 50.0, "fillingLevelInMl": 500, "powerConsumption": 0,
  "pumpedUp": true, "canControlDirection": false,
  "currentIngredient": { "...": "AutomatedIngredientDto.Response.Detailed or null" },
  "state": "READY", "setupStage": 3
}
```
`state` enum (`PumpDto.java:156-158`): `INCOMPLETE`, `TESTABLE`, `DISABLED`, `READY`.

`PumpDto.Request.Create` is polymorphic on `"type"`: `"dc"` → `DcPumpDto.Request.Create`, `"valve"` → `ValveDto.Request.Create`, `"stepper"` → `StepperPumpDto.Request.Create`. Common fields: `tubeCapacityInMl`, `fillingLevelInMl`, `isPumpedUp`, `currentIngredientId`, `name`, `powerConsumption`, `removeFields` (set of field names to null out on PATCH).

Type-specific fields (`payload/dto/pump/*.java`):
- `dc` (`DcPumpDto`, extends the shared `OnOffPumpDto`): `pin` (`PinDto`), `isPowerStateHigh` (bool), `timePerClInMs` (int, min 1) — a simple timed on/off DC pump.
- `stepper` (`StepperPumpDto`): `enablePin`, `stepPin` (both `PinDto`), `stepsPerCl` (int, min 1), `maxStepsPerSecond` (int, 1-500000), `acceleration` (int, 1-500000).
- `valve` (`ValveDto`, extends `OnOffPumpDto`): `pin`, `isPowerStateHigh`; response adds `loadCell`/`loadCellCalibrated` (bool); `tubeCapacityInMl` is server-fixed at `3.0` and not settable.

**PATCH authority note** (`PumpEndpoint.java:79-120`): a plain `PUMP_INGREDIENT_EDITOR` may only change `isPumpedUp`, `currentIngredient`/`currentIngredientId`, `fillingLevelInMl` via PATCH. `ADMIN`+ may additionally rename the pump and change `timePerClInMs`/`stepsPerCl`. `SUPER_ADMIN` can PATCH any field unrestricted.

`JobMetrics` (`model/pump/JobMetrics.java`):
```json
{ "id": 42, "mlPumped": 30, "stepsMade": 0, "startTime": 1735689600000, "stopTime": null, "timeElapsed": null, "exceptional": false }
```

### Pump settings — `/api/pump/settings`
(`endpoints/PumpSettingsEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| GET/PUT | `/api/pump/settings/reversepumping` | ADMIN | `ReversePumpSettingsDto.Request.Create {enable, settings}` | reverse-pumping (direction-control relay) config |
| GET/PUT | `/api/pump/settings/loadcell` | ADMIN | `LoadCellSettingsDto.Request.Create` | load-cell (glass-weight sensor) config incl. `dispensingArea` |
| GET | `/api/pump/settings/loadcell/read` | ADMIN | — | current raw load-cell reading |
| PUT | `/api/pump/settings/loadcell/calibratezero` | ADMIN | — | zero-calibrates the load cell |
| PUT | `/api/pump/settings/loadcell/calibratereference` | ADMIN | body: raw `long` reference weight in grams | calibrates against a known reference weight |
| GET/PUT | `/api/pump/settings/powerlimit` | ADMIN (GET) / SUPER_ADMIN (PUT) | `PowerLimitSettingsDto.Duplex.Detailed` | limits how many pumps may run concurrently (power-supply protection) |

### Ingredient — `/api/ingredient`
(`endpoints/IngredientEndpoint.java`)

| Method | Path | Auth | Params / Body | Response |
|---|---|---|---|---|
| GET | `/api/ingredient` | authenticated (or ADMIN if no filters given) | Query: `autocomplete` (string, min length 2 unless `inBar`/`onPump`/`inBarOrOnPump`), `filterManualIngredients`, `filterAutomaticIngredients`, `filterIngredientGroups`, `groupChildrenGroupId`, `inBar`, `onPump`, `inBarOrOnPump` (all bool, default false) | `IngredientDto.Response.Detailed[]` |
| POST | `/api/ingredient` | ADMIN | multipart: `ingredient` = `IngredientDto.Request.Create`, `image` optional | 201 `IngredientDto.Response.Detailed` |
| PUT | `/api/ingredient/{id}` | ADMIN | multipart: `ingredient`, `image` optional, query `removeImage` | 200/404 |
| GET | `/api/ingredient/{id}/image` | none | — | raw `image/jpeg` or 404 |
| DELETE | `/api/ingredient/{id}` | ADMIN | — | 200/404 |
| GET | `/api/ingredient/export` | ADMIN | — | `IngredientDto.Response.Detailed[]` in export order |
| PUT | `/api/ingredient/{id}/bar` | PUMP_INGREDIENT_EDITOR | — | marks ingredient "in bar" (physically available) |
| DELETE | `/api/ingredient/{id}/bar` | PUMP_INGREDIENT_EDITOR | — | removes "in bar" flag |

`IngredientDto` is polymorphic on `"type"`: `"manual"` (hand-added, not pumped), `"automated"` (assigned to a pump), `"group"` (an ingredient group / substitutable category). Common response fields (`payload/dto/recipe/ingredient/IngredientDto.java:72-90`): `id`, `name`, `normalName`, `parentGroupId`, `parentGroupName`, `unit`, `inBar`, `onPump`, `lastUpdate`.

`Ingredient.Unit` enum (`model/recipe/ingredient/Ingredient.java`), serialized as its display string via `@JsonValue`: `MILLILITER` → `"ml"`, `GRAM` → `"g"`, `TEASPOON` → `"teaspoon(s)"`, `TABLESPOON` → `"tablespoon(s)"`, `PIECE` → `"piece(s)"`. `automated` and `group` ingredients always report unit `MILLILITER`.

Type-specific fields on top of the common ones:
- `manual`/`automated` (both extend `AddableIngredientDto`): `alcoholContent` (0-100), `bottlePrice` (Double), `hasImage` (bool), `bottleSize` (Integer). `automated` additionally has `pumpTimeMultiplier` (double) and is always considered `onPump`; `manual` is always `onPump: false`.
- `group` (`IngredientGroupDto`): `leafIds` (Set<Long> — the concrete ingredients this group can resolve to), `minAlcoholContent`/`maxAlcoholContent` (derived from leaves), `inBar`/`onPump` (true if *any* leaf is).

### Category — `/api/category`
(`endpoints/CategoryEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| GET | `/api/category` | authenticated | — | `CategoryDto.Duplex.Detailed[]` |
| GET | `/api/category/{id}` | authenticated | — | `CategoryDto.Duplex.Detailed` or 404 |
| POST | `/api/category` | ADMIN | `{"name": "Classics"}` | 201, `Location` header |
| PUT | `/api/category/{id}` | ADMIN | `{"name": "..."}` | 200/404 |
| DELETE | `/api/category/{id}` | ADMIN | — | 200 |

`CategoryDto.Duplex.Detailed`: `{"id": 1, "name": "Classics"}`.

### Glass — `/api/glass`
(`endpoints/GlassEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| GET | `/api/glass` | authenticated | — | `GlassDto.Duplex.Detailed[]` |
| GET | `/api/glass/{id}` | authenticated | — | `GlassDto.Duplex.Detailed` or 404 |
| POST | `/api/glass` | ADMIN | `GlassDto.Duplex.Detailed` | 201 |
| PUT | `/api/glass/{id}` | ADMIN | `GlassDto.Duplex.Detailed` | 200/404 |
| DELETE | `/api/glass/{id}` | ADMIN | — | 200 |

`GlassDto.Duplex.Detailed`: `{"id": 1, "name": "Highball", "size": 350, "emptyWeight": 200, "isDefault": true, "isUseForSingleIngredients": false}` (`size` in ml, 1-5000; `emptyWeight` in grams, used with load-cell).

### Collection — `/api/collection`
(`endpoints/CollectionEndpoint.java`) — user-curated recipe playlists.

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/api/collection` | authenticated | `CollectionDto.Request.Create` | 201 `CollectionDto.Response.Detailed` |
| GET | `/api/collection/{id}` | authenticated | — | `CollectionDto.Response.Detailed` or 404 |
| GET | `/api/collection` | authenticated | Query `ownerId` (optional) | `CollectionDto.Response.Detailed[]` |
| GET | `/api/collection/{id}/image` | none | — | raw `image/jpeg` or 404 |
| PUT | `/api/collection/{id}` | owner or ADMIN | multipart: `collection`, `image` optional, query `removeImage` | 200/403/404 |
| DELETE | `/api/collection/{id}` | owner or ADMIN | — | 200/403/404 |
| POST | `/api/collection/{id}/add` | owner or ADMIN | body: raw `long` recipe id | adds recipe to collection |
| DELETE | `/api/collection/{id}/{recipeId}` | owner or ADMIN | — | removes recipe from collection |

### GPIO — `/api/gpio`
(`endpoints/GpioEndpoint.java`) — low-level board/pin management (all SUPER_ADMIN only).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/gpio` | Query `dType` (optional board-type filter) | `GpioBoardDto.Response.Detailed[]` |
| GET | `/api/gpio/{id}` | — | `GpioBoardDto.Response.Detailed` or 404 |
| POST | `/api/gpio` | `GpioBoardDto.Request.Create` | 201 |
| PUT | `/api/gpio/{id}` | `GpioBoardDto.Request.Create` | 200/404 |
| DELETE | `/api/gpio/{id}` | — | 200/404 |
| GET | `/api/gpio/status` | — | `GpioStatus` — just pin/board usage counts, no per-board health (see below) |
| GET | `/api/gpio/{id}/pin` | — | `PinDto.Response.Detailed[]` for that board |
| POST | `/api/gpio/{id}/restart` | — | restarts the given I2C board |

`GpioBoardDto.Response.Detailed` (`payload/dto/gpio/GpioBoardDto.java:39-69`) — polymorphic on `"type"` (`"local"` or `"i2c"`, subtypes add board-specific fields like the I2C address):
```json
{
  "id": 1,
  "name": "Main board",
  "type": "i2c",
  "pinCount": 16,
  "usedPinCount": 6,
  "errors": [ {"exceptionTraceMessages": ["I2C bus not reachable"]} ]
}
```
`errors` (`ErrorInfo[]`, `model/system/ErrorInfo.java`) is the board's actual health signal — each entry's `exceptionTraceMessages` is the causal-chain message list for one currently-active fault (e.g. an I2C bus that failed to initialize); an empty/absent list means the board is healthy. **This is the field to poll for GPIO/I2C health, not `GpioStatus`** — `GpioStatus` (`model/system/GpioStatus.java`) is just `{"pinsUsed": 6, "pinsAvailable": 10, "boardsAvailable": 1}`, aggregate usage counts with no error/health info at all, despite the endpoint being named `/status`.

### Event action — `/api/eventaction`
(`endpoints/EventActionEndpoint.java`) — SUPER_ADMIN-only automation/triggers subsystem (e.g. run a script/URL-call/audio-clip on cocktail events). Potentially useful as the HA-integration side of a two-way automation bridge.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/eventaction` | — | `EventActionDto.Response.Detailed[]` |
| GET | `/api/eventaction/executiongroup` | — | list of execution groups (actions in the same group run mutually exclusive) |
| DELETE | `/api/eventaction/process/{id}` | — | 202 if a running action process was killed, else 404 |
| GET | `/api/eventaction/{id}` | — | `EventAction` or 404 |
| POST | `/api/eventaction/{id}/start` | — | manually triggers the action; broadcasts status over WS |
| POST | `/api/eventaction` | multipart: `eventAction` = `EventActionDto.Request.Create` (polymorphic: file/URL-call/python/audio/do-nothing), `file` optional (required for file-type actions) | 201 |
| PUT | `/api/eventaction/{id}` | same as POST | 200 |
| DELETE | `/api/eventaction/{id}` | — | 200/404 |

Action types, with their `"type"` discriminator value for the polymorphic `EventActionDto.Request/Response` (`payload/dto/eventaction/*.java`):
- `"callUrl"` (`CallUrlEventActionDto`): `requestMethod` (HTTP method enum), `url` (string, max 255) — calls an external URL; this is the natural hook point for a *bidirectional* HA bridge (CocktailPi → HA webhook on cocktail events).
- `"execPy"` (`ExecutePythonEventActionDto`): runs an uploaded Python file (`fileName`).
- `"playAudio"` (`PlayAudioEventActionDto`): `fileName`, `onRepeat` (bool), `volume` (0-100), `soundDevice`.
- `"doNothing"` (`DoNothingEventActionDto`): no extra fields — a placeholder/no-op action.

All types share `trigger` (`EventTrigger`), `executionGroups` (mutually-exclusive execution group names), and `comment` (max 40 chars).

### User — `/api/user`
(`endpoints/UserEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/api/user` | ADMIN | `UserDto.Request.Create` (incl. `adminLevel`) | 201, `Location` header (can't create a user with a higher role than yourself) |
| PUT | `/api/user/{id}` or `/api/user/current` | authenticated (self) / ADMIN (others) | `UpdateUserRequest {userDto, updatePassword}` | `UserDto.Response.Detailed`; self-edits can't change own role or lock state |
| DELETE | `/api/user/{id}` | ADMIN | — | 204 (can't delete yourself or a higher-role user) |
| GET | `/api/user/{id}` or `/api/user/current` | authenticated (self) / ADMIN (others) | — | `UserDto.Response.Detailed` or 404 |
| GET | `/api/user` | ADMIN | — | `UserDto.Response.Detailed[]` |

### System — `/api/system`
(`endpoints/SystemEndpoint.java`)

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| GET | `/api/system/pythonlibraries` | SUPER_ADMIN | — | installed python libs (for custom event actions) |
| GET | `/api/system/audiodevices` | SUPER_ADMIN | — | available audio output devices |
| PUT | `/api/system/settings/donated` | authenticated | raw `bool` | records donation-dialog dismissal |
| GET/PUT | `/api/system/settings/appearance` | GET: none; PUT: ADMIN | `AppearanceSettingsDto.Duplex.Detailed` | UI appearance/localization settings, incl. `recipePageSize` |
| GET | `/api/system/settings/appearance/language` | none | — | `Language[]` enum values |
| PUT | `/api/system/settings/sawdonationdisclaimer` | authenticated | — | marks donation disclaimer as seen |
| PUT | `/api/system/shutdown` | ADMIN | Query `isReboot` (bool) | shuts down / reboots the host Pi |
| GET | `/api/system/settings/global` | authenticated | — | global settings blob |
| GET/PUT | `/api/system/settings/i2c` | GET: ADMIN; PUT: SUPER_ADMIN | `I2cSettingsDto.Request` | I2C bus config |
| GET | `/api/system/i2cprobe` | SUPER_ADMIN | — | `I2cAddressDto.Response[]` — scans I2C bus for devices |
| GET/PUT | `/api/system/settings/defaultfilter` | authenticated | `DefaultFilterDto.Duplex.Detailed` | default recipe list filter preferences |
| GET | `/api/system/version` | none | — | current app version string |
| GET | `/api/system/checkupdate` | SUPER_ADMIN | — | checks for a new CocktailPi release |
| POST | `/api/system/performupdate` | SUPER_ADMIN | — | triggers self-update |

### Transfer — `/api/transfer`
(`endpoints/TransferEndpoint.java`) — recipe/config import-export, all ADMIN only.

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/transfer/import` | multipart `file` (a CocktailPi export zip) | 201 `ExportContents` describing what the zip contains, `Location` header w/ import id |
| POST | `/api/transfer/import/{id}` | `ImportConfirmRequest` | confirms/applies a previously-staged import |
| POST | `/api/transfer/export` | `ExportRequest` | raw `application/zip` bytes (`Content-Disposition: attachment`) |
| POST | `/api/transfer/export/recipes` | — | `RecipeDto.Response.Detailed[]` — all recipes, JSON (despite POST) |

## WebSocket (real-time push) API

CocktailPi uses **STOMP over SockJS/raw WebSocket** for real-time state (cocktail production progress,
pump status, dispensing-area/glass detection, event-action logs). This is the primary way a Home
Assistant integration should track *live* state rather than polling.

- **Endpoint**: `ws(s)://<host>/websocket/` (raw STOMP) — also registered with SockJS fallback at the
  same path (`WebSocketAuthenticationConfig.java:47-49`).
- **Auth on CONNECT**: send a STOMP `CONNECT` frame with a native header `Authorization: Bearer <jwt>`
  (or just `<jwt>` — same `jwtUtils.parseJwt` stripping logic as REST). Without a valid token the
  connection is accepted but treated as anonymous, and most destinations will then reject subscription.
- **Destinations are all per-user** (`convertAndSendToUser`, which Spring STOMP maps to a
  `/user/<destination>` queue from the client's subscription perspective). **Subscribe to
  `/user/queue/...` — the server-side constants below omit the `/user` prefix Spring adds; the client
  must subscribe using `/user/<topic path>` per Spring's STOMP user-destination convention** (i.e. for
  `WS_COCKTAIL_DESTINATION = "/topic/cocktailprogress"`, the client subscribes to
  `/user/topic/cocktailprogress`).
- Direct raw subscriptions to `/topic/**` or `/queue/**` (not prefixed with `/user`) are **denied** by
  `WebSocketSecurityConfig.java:23` — subscription must go through the per-user routing.
- `/topic/eventactionstatus` and `/topic/eventactionlog` additionally require ADMIN-or-higher
  (`WebSocketAuthenticationConfig.java:54-55`, `WebSocketSecurityConfig.java:23-24`; the latter file
  checks `.hasAuthority(ERole.ROLE_ADMIN.name())` i.e. the literal string `"ROLE_ADMIN"`, whereas the
  user's actual granted authority string is `"ADMIN"` (`ERole.getAuthority()`, prefix stripped) —
  this looks like a latent inconsistency in the upstream source; if it behaves as literally read, this
  check would never match and effectively lock these two topics to nobody rather than to admins. Verify
  empirically against a running instance rather than trusting this at face value).
- **On subscribe, the server immediately pushes current state** to the newly-subscribed client
  (`config/websocket/WebSocketEventListener.java`, listens for `SessionSubscribeEvent`, ~10ms delay to
  avoid a race): subscribing to `/user/topic/cocktailprogress` gets the current `CocktailProgress`
  immediately, `/user/topic/pump/layout` gets the current pump list, `/user/topic/eventactionstatus`
  gets currently-running actions, `/user/topic/dispensingarea` gets current glass-detection state, and
  `/user/topic/pump/runningstate/{pumpId}` / `/user/topic/eventactionlog/{actionId}` get their
  respective current state. **This means a client never needs a separate REST call just to learn
  initial state — subscribe and the first message arrives automatically.**

Destinations (`service/WebSocketService.java:34-40`):

| Constant | Path (subscribe as `/user/<path>`) | Payload | Sent on |
|---|---|---|---|
| `WS_COCKTAIL_DESTINATION` | `/topic/cocktailprogress` | `CocktailProgressDto.Response.Detailed`, or literal string `"DELETE"` when no cocktail is in progress | cocktail order progress changes |
| `WS_PUMP_LAYOUT_DESTINATION` | `/topic/pump/layout` | `PumpDto.Response.Detailed[]` | pump configuration changes (added/edited/removed pump) |
| `WS_ACTIONS_STATUS_DESTINATION` | `/topic/eventactionstatus` | `EventActionDto.Response.RunInformation[]` | running event-action status changes (ADMIN only) |
| `WS_ACTIONS_LOG_DESTINATION` | `/topic/eventactionlog/{runningActionId}` | `RunningAction.LogEntry[]`, or literal `"DELETE"` | log lines for a specific running action (ADMIN only) |
| `WS_DISPENSING_AREA` | `/topic/dispensingarea` | `DispensingAreaStateDto` | glass-detection sensor / dispensing-area state changes |
| `WS_PUMP_RUNNING_STATE_DESTINATION` | `/topic/pump/runningstate/{pumpId}` | `PumpJobState` | a specific pump's running job state changes |
| `WS_UI_STATE_INFOS` | `/topic/uistateinfos` | literal string `"INVALIDATE_CACHED_RECIPES"` | tells clients their cached recipe list/search results are stale |

`CocktailProgressDto.Response.Detailed` (`payload/dto/cocktail/CocktailProgressDto.java:26-57`):
```json
{
  "recipe": { "...": "RecipeDto.Response.SearchResult" },
  "progress": 42,
  "userId": 1,
  "state": "RUNNING",
  "currentIngredientsToAddManually": [ "..." ],
  "writtenInstruction": "Add mint leaves and stir",
  "loadCellValue": 180,
  "showLoadCellValue": true
}
```
`state` enum (`model/cocktail/CocktailProgress.java:30`): `RUNNING`, `MANUAL_INGREDIENT_ADD`, `MANUAL_ACTION_REQUIRED`, `CANCELLED`, `FINISHED`, `ERROR`, `READY_TO_START`.

`PumpJobState` (`model/pump/PumpJobState.java`):
```json
{
  "lastJobId": 42,
  "runningState": { "jobId": 42, "isRunInfinity": false, "isForward": true, "percentage": 55, "state": "RUNNING" }
}
```

`DispensingAreaStateDto` (`payload/response/DispensingAreaStateDto.java`) — only meaningful on machines with glass-detection/load-cell hardware; on machines without it the backend still pushes this topic, just always with `areaEmpty: true` and `glass: null`:
```json
{
  "glass": { "id": 3, "name": "Highball", "size": 350, "emptyWeight": 200, "isDefault": true, "isUseForSingleIngredients": false },
  "areaEmpty": false
}
```
`glass` (`GlassDto.Duplex.Detailed`, same shape as the [Glass](#glass---apiglass) endpoint) is only non-null when a glass is detected and matched against a configured glass; `areaEmpty` is the more reliable general-purpose "is something on the dispensing area" flag — don't rely on `glass` alone being non-null as the detection signal.

## Roles / permission model

`ERole` (`model/user/ERole.java:6-11`), ordered by ascending privilege level (`hasAuthority` checks are
inclusive of this ordering in application code, but Spring's `hasAuthority` itself is an exact match —
endpoints instead compare `authority.getLevel()` where they need "this role or higher"):

| Role | Level | Typical capability |
|---|---|---|
| `USER` | 0 | Order cocktails, browse recipes |
| `RECIPE_CREATOR` | 1 | + create/edit/delete own recipes |
| `PUMP_INGREDIENT_EDITOR` | 2 | + manage pump filling levels/current ingredient, start/stop pumps, bar management |
| `ADMIN` | 3 | + manage users (below own level), categories, glasses, ingredients, system settings, run arbitrary pump jobs |
| `SUPER_ADMIN` | 4 | + GPIO/hardware config, create/delete pumps, event actions, full pump PATCH access |

The `ROLE_` prefix is stripped for `hasAuthority()` checks (`WebSecurityConfig.java:36`) — the
`Authorization` bearer JWT's embedded authority strings are `USER`, `RECIPE_CREATOR`, etc, not
`ROLE_USER`.

For a Home Assistant integration, a dedicated non-admin user with at least `PUMP_INGREDIENT_EDITOR`
(to start/stop pumps and read fill levels) is recommended; use `ADMIN` only if you also want to
trigger `runjob`-style arbitrary pump advice from HA.

## Key domain model notes

- **Recipe vs. Ingredient-recipe**: an "ingredient recipe" (`IngredientRecipe`) is a `Recipe` subtype
  representing a pre-mixed/prepared ingredient made from other ingredients (e.g. a house-made syrup) —
  most endpoints that take a recipe id also take an `isIngredient` flag to disambiguate the two id spaces.
- **Pump types**: `dc` (simple on/off DC pump, timed dispensing via `timePerClInMs`), `stepper`
  (`stepsPerCl`-based precise dispensing), `valve` (gravity-fed, on/off only, no filling-level tracking
  by volume in the same way). Always check the `type` discriminator field before assuming shape.
- **Cocktail production is asynchronous and single-slot**: ordering (`PUT /api/cocktail/{recipeId}`)
  returns `202 Accepted` immediately; actual state must be tracked via the
  `/user/topic/cocktailprogress` WebSocket subscription, not by polling a REST endpoint (there isn't one
  for "current progress" outside of the initial socket message on connect).
- **Feasibility checks** (`PUT /api/cocktail/{recipeId}/feasibility`) let a client (like a Home Assistant
  script) validate a drink can be made — and surface missing/insufficient ingredients — before actually
  ordering it.
