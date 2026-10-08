# CivicCare AI v4.2 — Public Civic Intelligence + Authority Routing

CivicCare is a public-facing civic reporting and urban intelligence platform. Citizens can explore live area conditions, submit civic issues, and track their reports. Reports are automatically classified and routed to the responsible civic department/authority, where authorized staff can review and update them.

## Core flow

Citizen -> Report issue -> Local AI classification -> Department routing -> Authority queue -> Status updates -> Citizen tracking

## Public experience
- Home overview
- Live map with live/historical separation
- Civic issue reporting
- My Reports and activity timeline
- Routing visibility after submission

## Authority experience
- Role-based Authority Desk
- Department-scoped assigned queue
- Priority/status filtering through the queue API
- Acknowledged / In Progress / Resolved / Escalated / Rejected updates
- Citizen sees recorded activity

## Security improvement
The complaint creation response exposes only safe assigned-authority fields (id, name, department, role), never password hashes or other internal database fields.

## External services
- TomTom: live traffic and traffic incidents; requires `TOMTOM_API_KEY`
- Open-Meteo: live weather; current integration requires no API key
- Nominatim/OpenStreetMap: geocoding and map context
- Overpass/OpenStreetMap: road context

## Environment
```env
CIVICCARE_JWT_SECRET=generate-a-long-random-secret
TOMTOM_API_KEY=your-tomtom-key
OVERPASS_URL=https://overpass-api.de/api/interpreter
CIVICCARE_HTTP_TIMEOUT=8
CIVICCARE_LIVE_CACHE_TTL=60
```

Never commit `.env` to GitHub.
