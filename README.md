# CivicCare AI — v5.8 Final

AI-powered civic complaint and urban-risk intelligence platform with a clean Purple + Navy + Cool Gray interface.

## Included
- Citizen registration/login and complaint reporting
- Authority login with department-specific queues
- Complaint routing, SLA/status lifecycle and authority action history
- Admin/System Configuration with TomTom status
- Interactive Leaflet area-intelligence map
- Weather, traffic and incident provider states shown explicitly
- Historical accident analytics and Random Forest risk baseline
- 20,000-record accident dataset
- Local MySQL support with SQLite fallback
- JWT authentication
- Responsive UI with readable live-intelligence cards

## Demo accounts

Citizen:
- `citizen@civiccare.local` / `Citizen@123`

Authority password for all departments:
- `Authority@123`

Authority emails:
- `roads@civiccare.local`
- `traffic@civiccare.local`
- `water@civiccare.local`
- `sanitation@civiccare.local`
- `electrical@civiccare.local`
- `disaster@civiccare.local`
- `emergency@civiccare.local`
- `general@civiccare.local`

Admin:
- `admin@civiccare.local` / `Admin@123`

These are local/demo credentials only. Change them before any real deployment.

## Run with local MySQL

1. Make sure MySQL Server is running.
2. Create `.env` from `.env.example`.
3. Set:

```env
CIVICCARE_DB_ENGINE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=YOUR_MYSQL_PASSWORD
MYSQL_DATABASE=civiccare
CIVICCARE_JWT_SECRET=YOUR_RANDOM_SECRET
TOMTOM_API_KEY=YOUR_TOMTOM_KEY
```

The application creates the `civiccare` database and required tables automatically when the MySQL account has permission to create databases/tables.

Generate a JWT secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

4. Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

5. Start:

```powershell
python run.py
```

Open `http://127.0.0.1:8000`.

## SQLite fallback

If you want zero-configuration local mode, set:

```env
CIVICCARE_DB_ENGINE=sqlite
CIVICCARE_DB_PATH=data/civiccare.db
```

## TomTom

TomTom is optional. If no key is configured, the interface explicitly shows traffic/incidents as unavailable instead of inventing live values.

Open-Meteo weather does not require an API key.

## Validation

The final package was checked with:
- `python -m py_compile app/main.py`
- `node --check app/static/app.js`
- `pytest -q` — 4 tests passed

## UI changes in v5.8

The final readability pass fixes the issues where live data was squeezed into one-character columns or low-contrast cards. The intelligence panel now reserves a usable desktop width, the three live signal cards have controlled typography, weather details use a two-column metric grid, historical evidence has a stable layout, Leaflet popups have readable contrast, and the home data-source cards use dark text on white surfaces.
