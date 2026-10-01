# CampusBites – Backend

API REST (FastAPI + SQLite) compartida por **todos** los fronts de CampusBites (Android/Kotlin y el otro cliente).
Sirve el catálogo de restaurantes y recibe la telemetría con la que se responden las business questions:

| # | Business question | Endpoint |
|---|---|---|
| BQ1 | What is the percentage of restaurant page loads that take more than 3 seconds? By device and OS | `GET /api/v1/analytics/slow-page-loads?thresholdMs=3000` |
| BQ2 | What is the percentage of failed requests when loading the restaurant's information? | `GET /api/v1/analytics/failed-requests` |

Ambos aceptan filtros opcionales `since`, `until` (ISO-8601) y `platform` (`android-kotlin`, `flutter`, `simulator`…).

## Correr

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/mac: source .venv/bin/activate)
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Swagger / documentación interactiva: http://localhost:8000/docs
- Tests: `pytest -q`
- Datos sintéticos para la demo: `python scripts/simulate_telemetry.py --n 300` (quedan con `platform=simulator`, se pueden excluir filtrando `?platform=android-kotlin`).
- Modo caos (para demostrar BQ1/BQ2 con cargas reales lentas o fallidas):
  `CHAOS_MAX_DELAY_MS=5000 CHAOS_FAILURE_RATE=0.2 uvicorn app.main:app --host 0.0.0.0 --port 8000`

Desde el **emulador** Android el backend es `http://10.0.2.2:8000/` (valor por defecto en el front).
En un **celular físico** agregar `API_BASE_URL=http://<IP-del-PC>:8000/` en `front-kotlin/gradle.properties`.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/v1/spots` | Lista resumida de restaurantes (sin menú ni reseñas) |
| GET | `/api/v1/spots/{id}` | Información completa del restaurante: **esta es la "restaurant page load"** que se mide |
| POST | `/api/v1/telemetry/page-loads` | Lote de eventos de carga (1–500), idempotente por `eventId` |
| GET | `/api/v1/analytics/slow-page-loads` | BQ1 |
| GET | `/api/v1/analytics/failed-requests` | BQ2 |
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

---

## a. Architecture – estructura general y componentes

Arquitectura **cliente-servidor por capas**:

```
┌──────────────── Clientes (N fronts) ────────────────┐
│ Android/Kotlin (Compose)        Otro front          │
│  UI (Views) → ViewModel → Repository → Retrofit     │
│                     └→ TelemetriaCargas (async)     │
└───────────────┬─────────────────────────────────────┘
                │ HTTP/REST + JSON (camelCase, /api/v1)
┌───────────────▼──────────── Backend (FastAPI) ──────┐
│ Routers      spots · telemetry · analytics          │  ← capa de presentación (API)
│ Services     AnalyticsService (BQ1, BQ2)            │  ← lógica de negocio / motor de analítica
│ Repositories SpotsRepository · TelemetryRepository  │  ← acceso a datos
│ SQLite       spots, menu_items, reviews,            │  ← persistencia centralizada
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

Ejemplo, BQ1:
`Usuario toca restaurante → ViewModel (t0) → Repository → GET /spots/{id} → (t1) → UI muestra menú → TelemetriaCargas POST {durationMs=t1-t0, device, OS} → page_load_events → GET /analytics/slow-page-loads`

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
| Táctica **fault injection** (testability) | Modo caos para provocar lentitud/fallas | `CHAOS_*` en `app/routers/spots.py` |
| Táctica **security** | Validación de entrada (Pydantic), SQL parametrizado, HTTP plano solo en debug | `schemas.py`, repositorios, `build.gradle.kts` |
| Táctica **interoperability** | Contrato JSON versionado (`/api/v1`), camelCase, CORS abierto para el otro front | `schemas.py`, `main.py` |
