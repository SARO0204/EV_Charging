# GridFlow AI

Phase 1 project setup for the GridFlow AI hackathon prototype.

## Frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

## Backend dependencies

```powershell
Set-Location backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Backend data provider

The backend uses Firestore by default. Deployments with Firebase credentials set
`GRIDFLOW_DATA_PROVIDER=firestore`, `FIREBASE_PROJECT_ID`, and either
`GOOGLE_APPLICATION_CREDENTIALS` or Application Default Credentials.

For a controlled demo without Firebase, set `GRIDFLOW_DATA_PROVIDER=demo` before
starting the backend. The checked-in fixture contains sample EVs, chargers,
charging history, reservations, and a simulation result; timestamps are resolved
relative to startup so queue forecasts remain current. Demo reservation changes
are held in process memory and reset when the backend restarts. Set
`GRIDFLOW_DEMO_DATA_FILE` to use a different fixture JSON file.

```powershell
Set-Location backend
$env:GRIDFLOW_DATA_PROVIDER = "demo"
py -m uvicorn app.main:app --reload
```
