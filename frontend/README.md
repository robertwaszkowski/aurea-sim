# AureaSim web frontend

The Vue/Vuetify frontend presents the projects managed by the FastAPI backend
in `server.py`. It supports project creation, simulation progress, result and
diagram views, analytics, report downloads, baseline editing, parameter
candidate review, historical-task search, validation, and hybrid export.

## Development

Install the repository Python environment first. Then:

```bash
cd frontend
npm ci
npm run dev
```

Run `python server.py` from the repository root in another terminal and open
`http://localhost:3000`.

## Production build

```bash
npm run build
```

The build performs Vue/TypeScript validation and writes `frontend/dist/`.
When that directory exists, `python server.py` serves the single-page
application at `http://localhost:8000`.

## Project data

The backend reads the software-level `projects/` directory. The release
contains three completed gallery projects; newly generated projects are local
runtime state and are ignored by Git.

Live AI generation requires `GEMINI_API_KEY`. Existing projects and offline
demonstrations remain available without it.
