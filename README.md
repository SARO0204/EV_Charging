# GridFlow AI

GridFlow helps EV drivers and charging operators choose a practical charger using vehicle urgency, station queues, charging capacity, and grid conditions.

> Instead of asking which charger is nearest, GridFlow asks which charger is the best choice right now.

## The problem

- A nearest-station choice can send an EV to a busy charger or a station under grid stress.
- Drivers and operators need to weigh charge urgency, travel distance, expected wait, connector power, and available grid capacity together.

## What GridFlow does

- Calculates an explainable EV priority from battery urgency and the requested charge gap.
- Estimates queue and wait using recent charging-session history and reservations.
- Assesses current and projected station grid load.
- Ranks available chargers using priority, distance, predicted wait, suitable charging power, and grid risk. The API explains the recommendation and lists alternatives.
- Recommends a practical charging slot, creates reservations, and can reassess or apply a reservation reallocation when conditions justify it.
- Provides an emergency charging recommendation for critical-priority EVs.
- Shows an estimated road route to the selected charger using OSRM geometry and OpenStreetMap tiles. It is not live-traffic navigation.
- Compares baseline and GridFlow outcomes in a what-if grid simulation.

## Decision approach

- The current implementation is an explainable decision engine, not a trained machine-learning model.
- Queue prediction is a prototype baseline derived from observed session durations, recent arrivals, current queue, and upcoming reservations. It is not a trained forecast model.
- Simulation uses generated EV arrivals and the existing baseline and GridFlow policies. Results are scenario estimates, not promises of operational improvement.

## Application flow

1. Select an EV and review its battery, charge target, vehicle, and locations.
2. Review priority, charger recommendation, queue estimate, grid assessment, and alternatives.
3. View an estimated road route to the recommended charger.
4. Review and reserve a charging slot.
5. Run a baseline-versus-GridFlow grid simulation.

## Architecture and data

- React frontend calls the FastAPI backend for EV, priority, queue, grid, recommendation, slot, reservation, emergency, reallocation, dashboard, and simulation APIs.
- The backend validates provider records with Pydantic and passes them to the existing intelligence services.
- `GRIDFLOW_DATA_PROVIDER=firestore` selects Firestore and is the default. Configure `FIREBASE_PROJECT_ID` and either `GOOGLE_APPLICATION_CREDENTIALS` or Application Default Credentials.
- `GRIDFLOW_DATA_PROVIDER=demo` selects the checked-in controlled JSON dataset and requires no Firebase credentials. Fixture timestamps are relative to process startup. Demo reservation and reallocation changes are held in process memory and reset when the backend restarts. `GRIDFLOW_DEMO_DATA_FILE` can point to another fixture.

## Technology

- Frontend: React, Vite, Tailwind CSS, React Router, Axios, Leaflet, React-Leaflet, and Recharts.
- Backend: Python, FastAPI, Pydantic, Uvicorn, Pandas, NumPy, scikit-learn, and Firebase Admin for Firestore access.
- Maps: OpenStreetMap tiles and the OSRM public routing service.
- Pandas, NumPy, and scikit-learn are in the backend requirements; the current decision and prediction paths do not use a trained ML model.

## Live demo

- Frontend: https://ev-charging-lime.vercel.app
- Backend: https://ev-charging-v572.onrender.com
- API documentation: https://ev-charging-v572.onrender.com/docs

For a separate frontend/backend deployment, set the frontend build variable `VITE_API_BASE_URL` to `https://ev-charging-v572.onrender.com`. The backend CORS policy allows the deployed frontend origin above.

## Run locally

Install and run the backend in demo mode from PowerShell:

```powershell
Set-Location backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:GRIDFLOW_DATA_PROVIDER = "demo"
py -m uvicorn app.main:app --reload --port 8003
```

In a second terminal, run the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite development server proxies `/api` to `http://127.0.0.1:8003`. For Firestore locally, set `GRIDFLOW_DATA_PROVIDER=firestore`, `FIREBASE_PROJECT_ID`, and the credential configuration before starting the backend.

Build the frontend with `npm run build` from `frontend/`. Run backend tests with `py -m unittest discover -s tests -v` from `backend/`.
