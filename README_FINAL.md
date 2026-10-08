
# CivicCare AI v5.3 — Civic Earth Production UI

This release uses the Civic Earth visual system: warm limestone, ivory surfaces, deep forest navigation, refined civic green actions, restrained copper/steel data accents, and semantic status colors. Citizen, Authority, and Admin workspaces use larger information hierarchy and authority users receive a department-specific operational map.

# CivicCare AI — Complete Role-Based Civic Intelligence Platform

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py run.py
```

Open `http://127.0.0.1:8000`.

## Login roles

The login screen uses one **Who are you?** dropdown:

- Citizen — public reporting, live map, own complaints and tracking
- Authority — choose department, then access only that department's complaint queue

### Demo citizen
- Email: `citizen@civiccare.local`
- Password: `Citizen@123`

### Demo authorities
- Roads: `roads@civiccare.local`
- Traffic: `traffic@civiccare.local`
- Water: `water@civiccare.local`
- Sanitation: `sanitation@civiccare.local`
- Electrical: `electrical@civiccare.local`
- Disaster Management: `disaster@civiccare.local`
- Emergency: `emergency@civiccare.local`
- General Services: `general@civiccare.local`
- Password for all authority accounts: `Authority@123`

### Demo admin
- Email: `admin@civiccare.local`
- Password: `Admin@123`

## Complaint workflow

Citizen report → CivicCare classification → responsible department → authority queue → authority action → citizen tracking → confirm/reopen.

Authorities can only act on complaints assigned to their own authority account.

## API configuration

Admin → System configuration → TomTom API.

Required external key:
- `TOMTOM_API_KEY` for live traffic and live traffic incidents.

No key is required for:
- Open-Meteo weather
- OpenStreetMap/Nominatim geocoding
- Overpass (current configured endpoint)
- Local Random Forest historical accident model

A local `.env` file is included with placeholders. Never commit real secrets to GitHub.

## Database persistence (v5.6)
Local deployment is configured for MySQL in this build. Set `CIVICCARE_DB_ENGINE=mysql` plus `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE`. The application creates the `civiccare` database and schema automatically when permitted. SQLite remains available as a fallback with `CIVICCARE_DB_ENGINE=sqlite`.

The browser now sends the selected Citizen/Authority workspace during login, existing accounts are validated against their real role/department, registration is awaited before opening the dashboard, and authentication errors are shown clearly.

## Local MySQL database
The current build supports local MySQL as the application database. Install dependencies, make sure MySQL Server is running, and create a `.env` file from `.env.example` with your local credentials:

```env
CIVICCARE_DB_ENGINE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=YOUR_MYSQL_PASSWORD
MYSQL_DATABASE=civiccare
```

The application creates the `civiccare` database (if the MySQL user has permission), creates the required tables, seeds demo users/zones/complaints, and imports the 20,000 accident records into MySQL on first startup. No SQLite database is used when `CIVICCARE_DB_ENGINE=mysql`.

If MySQL is not running, Windows users can start the MySQL service from Services or their MySQL installation control panel.
