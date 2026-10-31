# CampusBites – Backend

API REST (FastAPI + SQLite) compartida por **todos** los fronts de CampusBites (Android/Kotlin y el otro cliente).
Sirve el catálogo de restaurantes y recibe la telemetría con la que se responden las business questions:

| # | Business question | Endpoint |
|---|---|---|
| BQ1 | What is the percentage of restaurant page loads that take more than 3 seconds? By device and OS | `GET /api/v1/analytics/slow-page-loads?thresholdMs=3000` |
| BQ2 | What is the percentage of failed requests when loading the restaurant's information? | `GET /api/v1/analytics/failed-requests` |
| BQ3 | Which restaurants receive the highest number of page views and searches during each hour? | `GET /api/v1/analytics/spot-views-by-hour` |
| BQ3 | What are the nearest restaurants with the highest average rating that the user hasn't tried yet? | `GET /api/v1/users/{userId}/recommendations/nearby?lat=&lng=&maxWalkMinutes=15&limit=5` |
| BQ5 | Which restaurants in the user's favorites are open now and within a 15-minute walk? | `GET /api/v1/users/{userId}/favorites/nearby?lat=&lng=&maxWalkMinutes=15` |
| BQ6 | Which restaurants have the shortest waiting time and the best match with my taste profile? | `GET /api/v1/recommendations/best-for-you?freshMinutes=120` |
| BQ7 | How many active users add one or more restaurants to their favorites each month? | `GET /api/v1/analytics/monthly-active-favoriters` |
| BQ10 | What percentage of users use the restaurant rating feature when looking at a restaurant's page? | `GET /api/v1/analytics/rating-usage?months=6` |
| BQ13 | How does the number of app crashes during the restaurant review submission affect the number of reviews successfully published and what changes to the review submission feature should be prioritized based on this information? | `GET /api/v1/analytics/review-crashes?months=3&maxCrashPercentage=5` |
| BQ14 | How many times does the app display the restaurant's location incorrectly on the map or not at all, and should the map feature be improved or changed based on this? | `GET /api/v1/analytics/map-display-issues?months=3&maxIssuePercentage=10` |

> **Nota de numeración:** hay dos preguntas marcadas BQ3, la de vistas por hora (telemetría) y la de
> recomendaciones cercanas (feature de la *Taste Map*). Falta confirmar con el equipo cuál conserva el número.

BQ1 y BQ2 son de **tipo 1** (rendimiento técnico de la app). BQ3 es de **tipo 4** (comportamiento de uso por hora);
además de responderse en el endpoint, su resultado se muestra al usuario como la sección **"Popular right now"** del feed
*For You* y la pantalla *Popular by hour*.

BQ1 y BQ2 aceptan filtros opcionales `since`, `until` (ISO-8601) y `platform` (`android-kotlin`, `flutter`, `simulator`…).
BQ3 acepta `platform`, `days` (ventana hacia atrás, por defecto 7), `limit` (restaurantes por hora, por defecto 5),
`hour` (0–23: devuelve solo esa hora; la app manda la hora local del celular) y `tzOffsetMinutes`
(por defecto `-300`, Bogotá; configurable con `CAMPUS_TZ_OFFSET_MINUTES`).

BQ5 es una feature para el usuario (filtro "Open • ≤15 min" de *Saved* en el front Flutter): la app manda su ubicación y
el servidor decide qué favoritos están abiertos y a cuántos minutos caminando. El `userId` de la ruta es el de la
sesión (ver [Autenticación](#autenticación)); sin sesión se acepta un id de desarrollo (`--dart-define=DEV_USER_ID=<id>`).

BQ3 (recomendaciones) es la otra feature para el usuario: alimenta la pantalla *Taste Map* del front Flutter.
La app manda su ubicación y el servidor devuelve los restaurantes mejor calificados que quedan a una caminata
corta y que el usuario **todavía no ha probado**. Acepta `maxWalkMinutes` (por defecto 15, de 1 a 120) y
`limit` (por defecto 5, de 1 a 20). El `userId` de la ruta es el de la sesión, igual que en la BQ5.

BQ7 acepta `months` (meses calendario hacia atrás incluido el actual, por defecto 12, máx. 36), `tzOffsetMinutes` y
`platform`. Cuenta el `userId` de cada evento: el del token si la petición está autenticada; los ids de desarrollo
(sin token) también cuentan, así que para la medición real hay que usar la app con sesión iniciada.

BQ14 es de **tipo \*** (decisión de producto): mide cuántas veces el mapa (*Taste Map* del front Flutter) no muestra
la ubicación de los restaurantes o la muestra mal, y recomienda mejorar o mantener el mapa. Acepta `months` (meses
calendario hacia atrás incluido el actual, por defecto 3, máx. 36), `tzOffsetMinutes` y `maxIssuePercentage`
(por defecto 10, de 0 a 100): si el porcentaje de problemas de toda la ventana lo supera, `recommendation` es
`improve`; si no, `keep`. Todos los datos para la BQ14 salen de la tabla `page_load_events`; no hay tabla nueva.

BQ6 es de **tipo 2** y alimenta la sección **"Best for you right now"** del feed *For You* en la app Kotlin, que
reemplaza el porcentaje de *Taste Match* que antes venía escrito a mano en el catálogo. Junta dos cosas: el último
tiempo de espera que reportaron los estudiantes (los mismos datos de la BQ4) y el perfil de gusto. Acepta
`freshMinutes` (por defecto 120: un reporte más viejo no cuenta), `limit` (opcional, de 1 a 50; sin él devuelve todo el
catálogo ordenado) y el perfil, todo opcional: `budget`, `dietary` y `cuisines` (estos dos se pueden repetir).
**La app Kotlin no manda el perfil**: lo guarda en el celular (DataStore), así el perfil funciona sin red y no sale
del teléfono. Pide la lista sin perfil y calcula la compatibilidad en el celular con la misma fórmula.

Todas las BQ del equipo se ven juntas en el **[Dashboard](#dashboard)** (`GET /dashboard`).

## Correr

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/mac: source .venv/bin/activate)
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Swagger / documentación interactiva: http://localhost:8000/docs
- Tests: `pytest -q`
- Datos sintéticos para la demo: `python scripts/simulate_telemetry.py --n 300` (quedan con `platform=simulator`, se pueden excluir filtrando `?platform=android-kotlin`). Mezcla vistas y búsquedas repartidas por hora (café en la mañana, hamburguesas al mediodía, street food de noche) para que el ranking de BQ3 cambie según la hora.
- Requiere **Python 3.10+** (usa `X | None` en los tipos).
- Autenticación: en producción definir `JWT_SECRET` (32+ bytes aleatorios). Si no está, el backend genera uno al crear
  la base y lo guarda en ella (tabla `app_meta`), así los tokens sobreviven reinicios. `JWT_EXPIRE_MINUTES` (por
  defecto 10080 = 7 días) controla la vigencia.
- Modo caos (para demostrar BQ1/BQ2 con cargas reales lentas o fallidas):
  `CHAOS_MAX_DELAY_MS=5000 CHAOS_FAILURE_RATE=0.2 uvicorn app.main:app --host 0.0.0.0 --port 8000`

Desde el **emulador** Android el backend es `http://10.0.2.2:8000/` (valor por defecto en el front).
En un **celular físico** agregar `API_BASE_URL=http://<IP-del-PC>:8000/` en `front-kotlin/gradle.properties`.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| POST | `/api/v1/auth/signup` | Crear cuenta (`201`); devuelve el token |
| POST | `/api/v1/auth/login` | Iniciar sesión; devuelve el token |
| GET | `/api/v1/auth/me` | Usuario del token (para validar la sesión guardada al abrir la app) |
| POST | `/api/v1/auth/change-password` | Cambiar contraseña con token (`currentPassword`, `newPassword`). Devuelve un token nuevo y **cierra las demás sesiones**. `400` si la actual no coincide o la nueva es igual |
| GET | `/api/v1/spots` | Lista resumida de restaurantes (sin menú ni reseñas) |
| GET | `/api/v1/spots/{id}` | Información completa del restaurante: **esta es la "restaurant page load"** que se mide |
| POST | `/api/v1/spots/{id}/reviews` | Publicar calificación con token (`stars` 1–5, `text` opcional). Guarda la reseña y actualiza el promedio en una sola transacción (Unit of Work). `409` si el usuario ya calificó ese restaurante |
| POST | `/api/v1/telemetry/page-loads` | Lote de eventos (1–500), idempotente por `eventId`. `screen` = `restaurant_detail` (vista de página), `search` (elegido desde el buscador) o `favorite_added` (guardó el restaurante; exige `userId` y `spotId`) |
| GET | `/api/v1/analytics/slow-page-loads` | BQ1 |
| GET | `/api/v1/analytics/failed-requests` | BQ2 |
| GET | `/api/v1/analytics/spot-views-by-hour` | BQ3 (vistas + búsquedas por restaurante en cada hora) |
| GET | `/api/v1/analytics/monthly-active-favoriters` | BQ7 (usuarios distintos que agregan favoritos, por mes) |
| GET | `/api/v1/analytics/rating-usage` | BQ10 (de los usuarios que vieron páginas de restaurantes en el mes, % que calificó) |
| GET | `/api/v1/analytics/map-display-issues` | BQ14 (cargas del mapa con problemas, por tipo y por mes, y si conviene mejorar el mapa) |
| GET | `/dashboard` | Dashboard del equipo con todas las BQ (HTML) |
| GET | `/api/v1/users/{userId}/favorites` | Restaurantes guardados por el usuario (mismo formato que `/spots`) |
| PUT | `/api/v1/users/{userId}/favorites/{spotId}` | Guardar restaurante (idempotente, `204`; `404` si el restaurante no existe) |
| DELETE | `/api/v1/users/{userId}/favorites/{spotId}` | Quitar de guardados (idempotente, `204`) |
| GET | `/api/v1/users/{userId}/favorites/nearby` | BQ5 (favoritos abiertos ahora y a ≤ `maxWalkMinutes` caminando) |
| GET | `/api/v1/users/{userId}/recommendations/nearby` | BQ3 (mejor calificados a ≤ `maxWalkMinutes` caminando que el usuario no ha probado) |
| GET / PUT | `/api/v1/users/{userId}/preferences` | Taste Profile y Dietary Preferences del usuario (PUT reemplaza todo). Sin guardar devuelve los valores por defecto con `saved=false` |
| GET | `/api/v1/users/{userId}/matches` | Smart feature de Flutter: compatibilidad 0–100 de cada restaurante para el usuario (su perfil + estudiantes con gustos parecidos) y si choca con su dieta |
| GET | `/api/v1/recommendations/best-for-you` | BQ6 (menos espera según la BQ4 + compatibilidad con el perfil de gusto; el perfil es opcional) |
| GET | `/health` | Health check |

### Autenticación

Email + contraseña → JWT (HS256) de **7 días**, sin refresh token: al vencer, cualquier endpoint responde `401` y el
cliente vuelve a `/auth/login`. Las contraseñas se guardan con **bcrypt** (ver *Contraseñas* abajo).

```
POST /api/v1/auth/signup   {"email": "ana@uniandes.edu.co", "password": "segura123"}   → 201
POST /api/v1/auth/login    {"email": "ana@uniandes.edu.co", "password": "segura123"}   → 200
{ "userId": "3ddd5f3c-…", "email": "ana@uniandes.edu.co", "accessToken": "eyJhbGciOi…", "tokenType": "bearer",
  "expiresIn": 604800, "expiresAt": "2026-10-09T18:30:00.123456Z" }

GET /api/v1/auth/me        Authorization: Bearer <accessToken>                          → 200 {"userId", "email"}
```

- `email` se normaliza (sin espacios, minúsculas). `password` en el registro y `newPassword` al cambiarla:
  **8 a 128 caracteres** (ver *Contraseñas*). En el login solo se exige 1 a 128.
- **Contraseñas**: se normalizan con **NFKC**, así "ñ" escrita como un carácter o como "n" + tilde es la misma
  contraseña. El largo se cuenta en caracteres (*code points*) después de normalizar: un emoji cuenta 1, no sus 4
  bytes. Se guarda `"v2$" + bcrypt(base64(sha256(contraseña normalizada)))`: el pre-hash siempre mide 44 bytes, así
  bcrypt nunca trunca y ya no existe el límite de 72 bytes. Los hashes anteriores (bcrypt directo, sin prefijo) siguen
  funcionando y se migran solos al esquema `v2$` en el siguiente login correcto, sin cerrar sesiones.
- Errores: `409` email ya registrado · `401` email o contraseña incorrectos (mismo mensaje en ambos casos) ·
  `422` datos inválidos. Todo `401` trae `WWW-Authenticate: Bearer`.
- En las demás peticiones: header `Authorization: Bearer <accessToken>`. El `userId` de la respuesta es el que va en
  `/users/{userId}/...`; con otro `userId` en la ruta → `403`. En la telemetría `userId` puede omitirse (se toma del
  token); si viene distinto → `403`.
- Token vencido, mal firmado, mal formado o de una cuenta borrada → `401`. **Si el header viene, se valida siempre**.
- **Override de desarrollo**: una petición **sin** header `Authorization` puede usar cualquier `userId` (ruta o evento),
  como el `DEV_USER_ID` del front, **excepto** el de una cuenta registrada (`401`): sin token no se puede actuar a nombre
  de otro usuario real.

Contrato del evento de telemetría (cualquier front debe enviarlo igual):

```json
{ "events": [ {
  "eventId": "uuid", "screen": "restaurant_detail", "spotId": "nitro-coffee",
  "durationMs": 1830, "success": true, "httpStatus": 200, "errorType": null,
  "deviceModel": "Samsung Galaxy A14", "osName": "Android", "osVersion": "13",
  "platform": "android-kotlin", "appVersion": "1.0", "sessionId": "uuid",
  "occurredAt": "2026-10-01T15:04:05.123Z"
} ] }
```

`errorType`: `TIMEOUT`, `NO_CONNECTION`, `HTTP_<code>`, `PARSE_ERROR`, `NETWORK_ERROR`, `UNKNOWN`.

**Definiciones**
- *Carga de página de restaurante*: desde que el usuario abre el restaurante hasta que llega su información completa (menú + reseñas) o falla. Se mide en el cliente, porque solo el cliente ve la latencia real de la red móvil y los errores que nunca llegan al servidor (sin conexión, timeout).
- BQ1 usa solo cargas **exitosas** y cuenta como lenta `durationMs > thresholdMs` (exactamente 3000 ms no es "más de 3 s").
- BQ2 usa **todos** los intentos: `fallidos / intentos × 100`, desglosado por tipo de error, restaurante, SO y plataforma.
- BQ3 reutiliza la **misma telemetría** más un segundo tipo de evento. *Vista de página* = evento
  `screen=restaurant_detail` con `spotId` (haya cargado o no: cuenta la intención del estudiante). *Búsqueda* = evento
  `screen=search` con `spotId`, que la app envía cuando el usuario escribe en el buscador y elige ese restaurante
  (`durationMs=0`, `success=true`). Se agrupan por restaurante y por **hora local** (`occurredAt` UTC desplazado con
  `tzOffsetMinutes`) y se ordenan por `pageViews + searches`. BQ1/BQ2 ignoran los eventos `search`.
- BQ5 parte de los favoritos del usuario (tabla `favorites`). *Abierto ahora* = alguna franja de `spot_opening_hours`
  cubre la hora local (`now` UTC + `tzOffsetMinutes`, por defecto Bogotá); una franja con `closes_at <= opens_at` cruza
  la medianoche (El Vagón, 17:00–02:00, sigue abierto el sábado a la 01:30). *Distancia* = Haversine en línea recta
  desde `lat`/`lng`. *Minutos caminando* = metros / **80 m/min** (4,8 km/h, `WALKING_SPEED_M_PER_MIN`); como es línea
  recta, la caminata real puede ser algo mayor. Se descartan los que superan `maxWalkMinutes` (por defecto 15, máx. 120)
  y se ordena del más cercano al más lejano. Coordenadas y horarios del seed son **datos de ejemplo** alrededor de Uniandes.
- BQ3 (recomendaciones) parte del catálogo completo, no de los favoritos. *Probado* = el usuario tiene una reseña
  suya (`reviews.user_id`) de ese restaurante; las reseñas del catálogo (`user_id` nulo) no cuentan, así que cada
  usuario ve su propia lista. *Rating* = el promedio actual de `spots.rating`, ya actualizado por las calificaciones
  que publican los usuarios (BQ10). *Distancia* y *minutos caminando* se calculan igual que en la BQ5 (Haversine y
  80 m/min, reutilizando `haversine_m` y `WALKING_SPEED_M_PER_MIN`). El orden es **rating de mayor a menor** y, entre
  los que empatan, el más cercano; se descartan los que superan `maxWalkMinutes` y los que no tienen coordenadas.
  Está implementado como un *pipeline* de pipes and filters (`app/services/recommendations_service.py`): cada paso
  (`exclude_tried`, `add_distance`, `within_walk`, `rank`) recibe una lista y devuelve otra.
- BQ6: *Puntaje de espera* (0–100) = `100 × (1 − minutos / 40)`, con piso en 0, sobre el reporte más nuevo de
  `wait_time_reports`; si el reporte es más viejo que `freshMinutes` o no hay ninguno vale **50** (neutro: no se sabe
  cómo está la fila). *Compatibilidad* (0–100) = puntos ganados / puntos posibles, contando solo lo que el perfil
  llenó: cocina 50 (alguna cocina favorita aparece en el tipo de comida o el nombre: "Artisan Burgers" → `burger`,
  "Crepas & Bowls" → `bowl`/`crepa`, "Specialty Coffee" → `coffee`/`café`, "Asian Wok" → `wok`/`asian`), dieta 30
  (si el perfil pide Vegetarian o Vegan, el restaurante tiene que ser vegetariano) y presupuesto 20 (solo
  "Budget-friendly" exige `is_budget`). Si nada aplica vale 50. *Puntaje* = 0,5 × espera + 0,5 × compatibilidad (sin
  perfil, solo la espera). Orden: puntaje de mayor a menor; si empatan, la espera conocida más corta y después el
  mejor calificado. Igual que la BQ3, es un pipeline de pipes and filters (`app/services/best_for_you_service.py`:
  `add_wait`, `add_taste`, `add_score`, `rank`).
- BQ7: *usuario activo que agrega favoritos* = `userId` distinto con al menos un evento `screen=favorite_added` en el
  mes calendario local (`occurredAt` desplazado con `tzOffsetMinutes`): `COUNT(DISTINCT userId)` por mes. Se reporta
  también el total de eventos del mes. Los meses sin actividad salen en `0`. BQ1/BQ2/BQ3 ignoran estos eventos.
- BQ14: la app manda eventos `screen=map_display` (sin `spotId`). *Carga del mapa* = un evento `map_display` cuyo
  `errorType` es nulo o distinto de `tiles_failed`: la app manda **uno por carga**, con `success=true` si todo salió
  bien o `success=false` y `errorType` = `load_failed` (no llegaron los restaurantes), `location_fallback` (sin
  ubicación del usuario: el mapa se centra en el campus) o `invalid_coordinates` (algún restaurante con coordenadas
  fuera de rango, en 0,0 o a más de 5 km; ese pin no se dibuja). Además, como máximo un evento extra por carga con
  `success=false` y `errorType=tiles_failed` cuando fallan las imágenes del mapa. *Problema* = cualquier evento
  `map_display` con `success=false` (incluido `tiles_failed`, que es problema pero **no** cuenta como carga).
  `issuePercentage` = problemas / cargas × 100 con 1 decimal (como `tiles_failed` no es carga, en teoría puede pasar
  de 100). `issuesByType` va de mayor a menor y `mainIssue` es el tipo con más problemas (`null` si no hubo). Se
  agrupa por mes calendario local, igual que la BQ7; los meses sin cargas salen en `0`. Las cargas que la app sirve
  desde su caché en memoria (LRU) no mandan evento. BQ1/BQ2/BQ3 ignoran estos eventos.

Evento de búsqueda (mismo endpoint y contrato):

```json
{ "eventId": "uuid", "screen": "search", "spotId": "nitro-coffee", "durationMs": 0, "success": true,
  "httpStatus": null, "errorType": null, "deviceModel": "...", "osName": "Android", "osVersion": "14",
  "platform": "android-kotlin", "appVersion": "1.0", "sessionId": "uuid", "occurredAt": "2026-10-01T17:04:05.123Z" }
```

Evento de favorito (BQ7; mismo endpoint y contrato, más `userId`). La app lo manda al tocar el corazón para guardar:

```json
{ "eventId": "uuid", "screen": "favorite_added", "spotId": "nitro-coffee", "userId": "<id del usuario>",
  "durationMs": 0, "success": true, "httpStatus": null, "errorType": null, "deviceModel": "...", "osName": "Android",
  "osVersion": "14", "platform": "flutter", "appVersion": "1.0", "sessionId": "uuid", "occurredAt": "2026-10-01T17:04:05.123Z" }
```

Ejemplo de respuesta de BQ7 (`?months=2`):

```json
{ "question": "How many active users add one or more restaurants to their favorites each month?",
  "months": 2, "tzOffsetMinutes": -300,
  "byMonth": [ { "month": "2026-09", "activeFavoriters": 14, "favoriteEvents": 31 },
               { "month": "2026-10", "activeFavoriters": 3, "favoriteEvents": 5 } ] }
```

Ejemplo de respuesta de BQ14 (`?months=2`):

```json
{ "mapLoads": 40, "issues": 6, "issuePercentage": 15.0,
  "issuesByType": { "invalid_coordinates": 3, "tiles_failed": 2, "location_fallback": 1 },
  "mainIssue": "invalid_coordinates",
  "question": "How many times does the app display the restaurant's location incorrectly on the map or not at all, and should the map feature be improved or changed based on this?",
  "months": 2, "tzOffsetMinutes": -300, "maxIssuePercentage": 10.0, "recommendation": "improve",
  "byMonth": [
    { "mapLoads": 15, "issues": 1, "issuePercentage": 6.7, "issuesByType": { "location_fallback": 1 },
      "mainIssue": "location_fallback", "month": "2026-09" },
    { "mapLoads": 25, "issues": 5, "issuePercentage": 20.0,
      "issuesByType": { "invalid_coordinates": 3, "tiles_failed": 2 }, "mainIssue": "invalid_coordinates", "month": "2026-10" } ] }
```

Ejemplo de respuesta de BQ5 (`GET /api/v1/users/ana/favorites/nearby?lat=4.6019&lng=-74.0658&maxWalkMinutes=15`;
es un **arreglo** sin envoltorio, como lo espera el front Flutter; un usuario sin favoritos recibe `[]`):

```json
[ { "id": "nitro-coffee", "name": "Nitro Coffee & Brew", "emoji": "☕", "distanceMeters": 0, "walkMinutes": 0.0, "closesAt": "19:00" },
  { "id": "green-bowl-co", "name": "Green Bowl Co.", "emoji": "🥗", "distanceMeters": 95, "walkMinutes": 1.2, "closesAt": "20:00" } ]
```

Ejemplo de respuesta de BQ3 recomendaciones
(`GET /api/v1/users/ana/recommendations/nearby?lat=4.6019&lng=-74.0658&maxWalkMinutes=15&limit=3`; también es un
**arreglo** sin envoltorio; si el usuario ya probó todos los cercanos recibe `[]`):

```json
[ { "id": "nitro-coffee", "name": "Nitro Coffee & Brew", "emoji": "☕", "rating": 5.0,
    "latitude": 4.6019, "longitude": -74.0658, "distanceMeters": 0, "walkMinutes": 0.0 },
  { "id": "conda-de-bons", "name": "Conda de Bons", "emoji": "🍔", "rating": 5.0,
    "latitude": 4.6031, "longitude": -74.0662, "distanceMeters": 141, "walkMinutes": 1.8 },
  { "id": "la-esquina-burger-lab", "name": "La Esquina Burger Lab", "emoji": "🍔", "rating": 4.8,
    "latitude": 4.6006, "longitude": -74.0646, "distanceMeters": 196, "walkMinutes": 2.5 } ]
```

Ejemplo de respuesta de BQ3 (`?hour=12&limit=2`; sin `hour` devuelve una entrada por cada hora con actividad):

```json
{ "question": "Which restaurants receive the highest number of page views and searches during each hour?",
  "days": 7, "tzOffsetMinutes": -300,
  "hours": [ { "hour": 12, "totalPageViews": 61, "totalSearches": 28,
               "spots": [ { "rank": 1, "spotId": "la-esquina-burger-lab", "name": "La Esquina Burger Lab", "emoji": "🍔",
                            "pageViews": 14, "searches": 6, "total": 20 },
                          { "rank": 2, "spotId": "conda-de-bons", "name": "Conda de Bons", "emoji": "🍔",
                            "pageViews": 12, "searches": 5, "total": 17 } ] } ] }
```

## Dashboard

Una sola página con **todas** las business questions del equipo, leída de la misma base SQLite a través de los
endpoints `/api/v1/analytics/...` (no consulta la base directamente). Con el backend corriendo, abrir
**http://localhost:8000/dashboard** en el navegador.

- Una tarjeta por BQ: BQ1 y BQ2 (Tomas Diaz), BQ6 (Lucas Galindo), BQ7 (Camilo Linares), BQ10 (Gabriela Perdomo), BQ11 (Lucas Galindo),
  BQ12 (Alejandro Vides) y BQ14 (Esteban Alvarado), con la pregunta, el número clave y un gráfico simple. La BQ14
  muestra los problemas por tipo, el % de cada mes y la recomendación (`IMPROVE` / `KEEP`) en grande.
- Botón **Refresh** y actualización automática cada 30 s. Si un endpoint falla, solo su tarjeta muestra el error.
- La BQ11 todavía no tiene endpoint: su tarjeta dice "Endpoint not available yet". Cuando exista, basta con poner su
  ruta y su `render` en la lista `CARDS` de `app/static/dashboard.html`.
- Es un solo archivo HTML + CSS + JavaScript (Chart.js desde cdnjs), sin build ni framework. Los datos sintéticos
  de `python scripts/simulate_telemetry.py` llenan BQ1, BQ2 y BQ12; las demás tarjetas se llenan usando la app.

## a. Architecture – estructura general y componentes

Arquitectura **cliente-servidor por capas**:

```
┌──────────────── Clientes (N fronts) ────────────────┐
│ Android/Kotlin (Compose)        Otro front          │
│  UI (Views) → ViewModel → Repository → Retrofit     │
│                     ├→ TelemetriaCargas (async)     │
│                     └→ PopularidadRepository (BQ3,  │
│                        cache + ContextoHorario)     │
└───────────────┬─────────────────────────────────────┘
                │ HTTP/REST + JSON (camelCase, /api/v1)
┌───────────────▼──────────── Backend (FastAPI) ──────┐
│ Routers      auth · spots · telemetry · analytics   │  ← capa de presentación (API)
│              · users                                │
│ Services     AnalyticsService (BQ1, BQ2, BQ3)       │  ← lógica de negocio / motor de analítica
│              FavoritesService (BQ5) · AuthService   │
│ Repositories SpotsRepository · TelemetryRepository  │  ← acceso a datos
│              FavoritesRepository · UsersRepository  │
│ SQLite       spots, menu_items, reviews,            │  ← persistencia centralizada
│              spot_opening_hours, favorites, users,  │
│              page_load_events                       │
└─────────────────────────────────────────────────────┘
```

Componentes del cliente Android (en `front-kotlin`):
- **GUI**: pantallas Compose (`PantallaParaTi`, `PantallaDetalle`, …).
- **Processing**: `CampusBitesViewModel` (estado, medición de tiempos) y `TelemetriaCargas` (cola y envío en segundo plano).
- **Local storage**: catálogo empaquetado (`SpotsData.kt`) como respaldo offline.
- **Backend services & analytics engine**: este proyecto.

## b. Architecture design – cómo interactúan

1. **Cliente-Servidor REST/HTTP** (asíncrono, coroutines + Retrofit):
   - Abrir la app → `GET /spots`.
   - Abrir un restaurante → el ViewModel arranca un cronómetro, hace `GET /spots/{id}` y al terminar (éxito o error) lo detiene.
2. **Telemetría asíncrona, fire-and-forget**: el ViewModel entrega el evento a `TelemetriaCargas`, que lo encola y envía en lote (`POST /telemetry/page-loads`) en un hilo de IO; nunca bloquea la UI. Si falla, se reintenta con el siguiente evento.
3. **Analítica bajo demanda**: los endpoints `/analytics/*` agregan los eventos con SQL (`GROUP BY` dispositivo, SO, tipo de error…) y devuelven el porcentaje.
4. **Flujo interno del cliente (unidireccional / reactivo)**: evento de UI → ViewModel muta estado → Compose recompone la vista.
5. **Ciclo cerrado de la BQ3**: la telemetría que produce la app vuelve a la app como feature. Al abrir *For You*,
   el ViewModel pide `GET /analytics/spot-views-by-hour?hour=<hora local>` a través de `PopularidadRepository`;
   el backend agrega vistas y búsquedas de esa hora y el feed muestra "Popular right now · 12:00–13:00". Al cerrar
   un restaurante se refresca el ranking, porque esa vista (o búsqueda) ya es un evento más.

Ejemplo, BQ1:
`Usuario toca restaurante → ViewModel (t0) → Repository → GET /spots/{id} → (t1) → UI muestra menú → TelemetriaCargas POST {durationMs=t1-t0, device, OS} → page_load_events → GET /analytics/slow-page-loads`

Ejemplo, BQ3:
`Usuario escribe "burger" en el buscador → toca "La Esquina Burger Lab" → TelemetriaCargas POST {screen=search, spotId} + abrirSitio (POST {screen=restaurant_detail}) → page_load_events → ContextoHorario (hora local 12, UTC-5) → PopularidadRepository (¿cache vigente?) → GET /analytics/spot-views-by-hour?hour=12&tzOffsetMinutes=-300 → SQL: vistas y búsquedas por spot con hora local = 12 → SeccionPopularidad "🔥 Popular right now"`

## c. Design patterns & tactics – y quién es responsable

| Patrón / táctica | Dónde | Responsable |
|---|---|---|
| **Client-Server** | Toda la solución; un solo backend para varios fronts | Backend: `app/main.py` |
| **Layered architecture** | Routers → Services → Repositories → DB | Backend `app/` |
| **Repository** | Aísla el origen de datos | `SpotsRepository`, `TelemetryRepository` (backend); `SpotsRepository.kt` (front) |
| **MVVM** | UI observa estado, ViewModel no conoce la vista | `CampusBitesViewModel.kt` + pantallas Compose |
| **Adapter / DTO + Mapper** | JSON (hex, strings) ↔ modelo de UI (`Color`, enums) | `ApiDtos.kt`, `toModel()` en `SpotsRepository.kt`; `schemas.py` |
| **Dependency Injection** | Conexión DB y servicios inyectados por request | `Depends(...)` en routers; constructor del ViewModel |
| Táctica **performance – procesamiento asíncrono** | Red y telemetría fuera del hilo principal; lotes | coroutines (`viewModelScope`, `Dispatchers.IO`) |
| Táctica **performance – endpoints livianos** | Lista sin menú/reseñas; detalle bajo demanda | `/spots` vs `/spots/{id}` |
| Táctica **availability – degradación/fallback** | Si `/spots` falla se muestra el catálogo local + aviso offline | `SpotsRepository.listarSitios()` |
| Táctica **reliability – timeouts + retry idempotente** | Timeout 10 s; reintento manual en detalle; `eventId` único evita duplicados | `ApiClient`, `TelemetriaCargas`, `UNIQUE(event_id)` |
| Táctica **monitoring / telemetry** | Cada carga se mide y se reporta | `TelemetriaCargas` → `page_load_events` |
| **Observer** (estado observable) | La UI de "Popular right now" se recompone sola cuando el ViewModel actualiza `EstadoPopularidad`; ninguna pantalla consulta la red directamente | `mutableStateOf` en `CampusBitesViewModel.kt`, `SeccionPopularidad.kt` |
| Táctica **context awareness** | La feature "Popular right now" se adapta a la hora y zona horaria del celular: pide solo la hora actual | `ContextoHorario.kt` → parámetro `hour` de BQ3 |
| Táctica **performance – cache-aside con TTL** | El ranking por hora se guarda 5 min en memoria; se invalida al abrir un restaurante | `PopularidadRepository.kt` |
| Táctica **availability – degradación** | Sin red, la sección "Popular right now" se oculta y el feed sigue funcionando | `EstadoPopularidad.error` en `CampusBitesViewModel.kt` |
| Táctica **monitoring – eventos de búsqueda** | El buscador reporta qué restaurante eligió el usuario (`screen=search`) con el mismo contrato y cola que las cargas | `TelemetriaCargas.registrarBusqueda()` |
| Táctica **fault injection** (testability) | Modo caos para provocar lentitud/fallas | `CHAOS_*` en `app/routers/spots.py` |
| Táctica **security** | Validación de entrada (Pydantic), SQL parametrizado, HTTP plano solo en debug | `schemas.py`, repositorios, `build.gradle.kts` |
| Táctica **security – autenticación** | Email + contraseña (bcrypt) → JWT Bearer de 7 días; el `userId` sale del token y no se puede actuar a nombre de una cuenta registrada sin su token | `auth_service.py`, `security.py` (`optional_user_id`, `resolve_acting_user`) |
| Táctica **interoperability** | Contrato JSON versionado (`/api/v1`), camelCase, CORS abierto para el otro front | `schemas.py`, `main.py` |
