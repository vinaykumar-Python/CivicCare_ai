# CivicCare AI — Live Urban Intelligence v3

This upgrade keeps the existing 20,000-record accident dataset as the **historical ML layer** and adds a separate **live intelligence layer**.

## Live architecture

- **OpenStreetMap**: map tiles and place/road context.
- **Open-Meteo**: current weather; no API key required for its non-commercial free tier.
- **TomTom Traffic**: live traffic flow and current traffic incidents when `TOMTOM_API_KEY` is configured.
- **CivicCare database**: current citizen reports and historical accident records, stored in local MySQL when configured.
- **Random Forest**: evaluates current location/time/weather/traffic/road context using the existing trained feature schema.
- **Risk engine**: combines available evidence and renormalizes weights when a live source is unavailable. It never substitutes historical data and labels it as live.

## Configure live traffic

1. Create a TomTom developer account/API key.
2. Copy `.env.example` to `.env`.
3. Set `TOMTOM_API_KEY=your_key`.
4. Restart the application.

Without the key, the application still runs, but traffic flow and live traffic incidents are explicitly marked unavailable. **No simulated traffic is generated.**

## Run

```powershell
py -m venv .venv
.venv\\Scripts\\activate
python -m pip install -r requirements.txt
py run.py
```

Open `http://127.0.0.1:8000`.

## Accuracy / model boundary

The existing Random Forest metrics (R² 0.8862, MAE 0.0522) describe the supplied historical accident `risk_score` task. They are not real-world accident probabilities. The live area score is a transparent decision-support evidence score and is not presented as a probability of an accident.

## Data freshness

- Live traffic / incidents: provider observation timestamp.
- Weather: current provider observation.
- CivicCare complaints: database timestamps.
- Accident dataset: historical records only.

## Important service policies

Use OpenStreetMap/Nominatim according to their current usage policies and provide attribution. The UI uses end-user-triggered place search rather than autocomplete or background bulk geocoding.


### TomTom connection test
Admin → System Configuration now performs an actual TomTom Traffic Flow request. `Configured` means a key is loaded; `Connected` means the provider answered successfully. HTTP/provider errors are shown without exposing the key.
