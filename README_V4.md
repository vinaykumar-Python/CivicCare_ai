# CivicCare AI v4 — Live Urban Intelligence

CivicCare AI v4 upgrades the local-first civic complaint and accident-risk platform with a clearer live-intelligence workflow.

## What changed

- Live weather is a first-class intelligence signal using Open-Meteo.
- Added `GET /api/live/weather` for current weather at a selected coordinate.
- Live area analysis keeps **LIVE**, **HISTORICAL**, **CIVIC REPORTS**, and **ML ESTIMATE** separate.
- Missing live providers are excluded from the weighted evidence score instead of being replaced with synthetic values.
- The ML component is no longer labelled as available when the live model cannot be evaluated.
- Area analysis now reports the actual dominant historical accident cause.
- Area analysis reports the historical peak accident hour and common historical weather.
- Geographic map queries use a bounding-box pre-filter before distance calculations.
- Map issue queries can be scoped to the selected latitude/longitude/radius instead of loading the broad dataset.
- Live map UI adds weather detail, freshness/source badges, road-condition signals, evidence breakdown, and provider status.
- Dashboard live workspace uses a Midnight Navy / Civic Teal / Signal Amber visual system.

## Live data sources

- **Open-Meteo:** current weather and weather conditions.
- **TomTom Traffic:** live traffic flow when `TOMTOM_API_KEY` is configured.
- **TomTom Traffic Incidents:** current incidents when `TOMTOM_API_KEY` is configured.
- **OpenStreetMap / Nominatim / Overpass:** map, location and road context.
- **CivicCare SQLite:** current citizen reports and imported historical accident records.

No fake live traffic values are generated. Provider failure is surfaced explicitly.

## Risk calculation boundary

The live area score is an **evidence-based decision-support score**, not a calibrated probability that an accident will occur.

The current fusion uses available evidence:

- Random Forest live-context estimate — 45%
- Live traffic congestion — 25%
- Live incidents — 20%
- Nearby CivicCare reports — 10%

Unavailable components are removed and the remaining weights are renormalized. Weather is used as contextual input to the Random Forest rather than being assigned an arbitrary standalone percentage.

## ML boundary

The Random Forest predicts the supplied dataset's continuous `risk_score`. Current reported offline metrics remain:

- R²: 0.8862
- MAE: 0.0522
- 80/20 held-out evaluation
- 20,000 accident records

These metrics are not live-world accident accuracy claims.

## Run

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
# Optional: add TOMTOM_API_KEY=your_key to .env
py run.py
```

Open `http://127.0.0.1:8000`.

## Tests

```powershell
pytest -q
```

The v4 upgrade preserves the existing smoke/map test suite.
