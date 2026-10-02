# CampusBites – Backend

API REST (FastAPI + SQLite) compartida por **todos** los fronts de CampusBites (Android/Kotlin y el otro cliente).
Sirve el catálogo de restaurantes y recibe la telemetría con la que se responden las business questions:

| # | Business question | Endpoint |
|---|---|---|
| BQ1 | What is the percentage of restaurant page loads that take more than 3 seconds? By device and OS | `GET /api/v1/analytics/slow-page-loads?thresholdMs=3000` |
| BQ2 | What is the percentage of failed requests when loading the restaurant's information? | `GET /api/v1/analytics/failed-requests` |
| BQ3 | Which restaurants receive the highest number of page views and searches during each hour? | `GET /api/v1/analytics/spot-views-by-hour` |
| BQ5 | Which restaurants in the user's favorites are open now and within a 15-minute walk? | `GET /api/v1/users/{userId}/favorites/nearby?lat=&lng=&maxWalkMinutes=15` |

BQ1 y BQ2 son de **tipo 1** (rendimiento técnico de la app). BQ3 es de **tipo 4** (comportamiento de uso por hora);
además de responderse en el endpoint, su resultado se muestra al usuario como la sección **"Popular right now"** del feed
*For You* y la pantalla *Popular by hour*.

BQ1 y BQ2 aceptan filtros opcionales `since`, `until` (ISO-8601) y `platform` (`android-kotlin`, `flutter`, `simulator`…).
BQ3 acepta `platform`, `days` (ventana hacia atrás, por defecto 7), `limit` (restaurantes por hora, por defecto 5),
`hour` (0–23: devuelve solo esa hora; la app manda la hora local del celular) y `tzOffsetMinutes`
(por defecto `-300`, Bogotá; configurable con `CAMPUS_TZ_OFFSET_MINUTES`).

BQ5 es una feature para el usuario (filtro "Open • ≤15 min" de *Saved* en el front Flutter): la app manda su ubicación y
el servidor decide qué favoritos están abiertos y a cuántos minutos caminando. **Todavía no hay autenticación**: el
`userId` de la ruta es el identificador que manda el cliente (en Flutter, `--dart-define=DEV_USER_ID=<id>`).

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
- Modo caos (para demostrar BQ1/BQ2 con cargas reales lentas o fallidas):
  `CHAOS_MAX_DELAY_MS=5000 CHAOS_FAILURE_RATE=0.2 uvicorn app.main:app --host 0.0.0.0 --port 8000`

Desde el **emulador** Android el backend es `http://10.0.2.2:8000/` (valor por defecto en el front).
En un **celular físico** agregar `API_BASE_URL=http://<IP-del-PC>:8000/` en `front-kotlin/gradle.properties`.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/v1/spots` | Lista resumida de restaurantes (sin menú ni reseñas) |
| GET | `/api/v1/spots/{id}` | Información completa del restaurante: **esta es la "restaurant page load"** que se mide |
| POST | `/api/v1/telemetry/page-loads` | Lote de eventos (1–500), idempotente por `eventId`. `screen` = `restaurant_detail` (vista de página) o `search` (elegido desde el buscador) |
| GET | `/api/v1/analytics/slow-page-loads` | BQ1 |
| GET | `/api/v1/analytics/failed-requests` | BQ2 |
| GET | `/api/v1/analytics/spot-views-by-hour` | BQ3 (vistas + búsquedas por restaurante en cada hora) |
| GET | `/api/v1/users/{userId}/favorites` | Restaurantes guardados por el usuario (mismo formato que `/spots`) |
| PUT | `/api/v1/users/{userId}/favorites/{spotId}` | Guardar restaurante (idempotente, `204`; `404` si el restaurante no existe) |
| DELETE | `/api/v1/users/{userId}/favorites/{spotId}` | Quitar de guardados (idempotente, `204`) |
| GET | `/api/v1/users/{userId}/favorites/nearby` | BQ5 (favoritos abiertos ahora y a ≤ `maxWalkMinutes` caminando) |
| GET | `/health` | Health check |

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

Evento de búsqueda (mismo endpoint y contrato):

```json
{ "eventId": "uuid", "screen": "search", "spotId": "nitro-coffee", "durationMs": 0, "success": true,
  "httpStatus": null, "errorType": null, "deviceModel": "...", "osName": "Android", "osVersion": "14",
  "platform": "android-kotlin", "appVersion": "1.0", "sessionId": "uuid", "occurredAt": "2026-10-01T17:04:05.123Z" }
```

Ejemplo de respuesta de BQ5 (`GET /api/v1/users/ana/favorites/nearby?lat=4.6019&lng=-74.0658&maxWalkMinutes=15`;
es un **arreglo** sin envoltorio, como lo espera el front Flutter; un usuario sin favoritos recibe `[]`):

```json
[ { "id": "nitro-coffee", "name": "Nitro Coffee & Brew", "emoji": "☕", "distanceMeters": 0, "walkMinutes": 0.0, "closesAt": "19:00" },
  { "id": "green-bowl-co", "name": "Green Bowl Co.", "emoji": "🥗", "distanceMeters": 95, "walkMinutes": 1.2, "closesAt": "20:00" } ]
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
│ Routers      spots · telemetry · analytics · users  │  ← capa de presentación (API)
│ Services     AnalyticsService (BQ1, BQ2, BQ3)       │  ← lógica de negocio / motor de analítica
│              FavoritesService (BQ5)                 │
│ Repositories SpotsRepository · TelemetryRepository  │  ← acceso a datos
│              FavoritesRepository                    │
│ SQLite       spots, menu_items, reviews,            │  ← persistencia centralizada
│              spot_opening_hours, favorites,         │
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
| Táctica **interoperability** | Contrato JSON versionado (`/api/v1`), camelCase, CORS abierto para el otro front | `schemas.py`, `main.py` |
