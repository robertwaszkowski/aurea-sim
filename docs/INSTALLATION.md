# AureaSim installation guide

## Supported environment

- Python 3.9-3.11;
- Node.js 20 or newer;
- Windows, macOS, or Linux;
- Prosimos 1.2.4, installed with the Python dependencies.

## Unified launcher

macOS/Linux:

```bash
./aureasim.sh
```

Windows:

```powershell
.\aureasim.bat
```

The launcher detects Conda, creates the `aureasim` environment when needed,
installs frontend dependencies, and offers the terminal or web interface.

## Manual installation

```bash
conda env create -f environment.yml
conda activate aureasim
cd frontend
npm ci
npm run build
cd ..
python server.py
```

Open `http://localhost:8000`.

For frontend development, run the backend with `python server.py`, run
`npm run dev` inside `frontend/`, and open `http://localhost:3000`.

## Live AI-assisted generation

Set `GEMINI_API_KEY` in the process environment or in a local `.env` file.
Start from `.env.example`; never commit `.env`.

Offline examples, completed project inspection, manual parameter editing, and
most tests do not require an API key.

## Docker

```bash
docker build -t aureasim:1.3.0 .
docker run --rm -p 8000:8000 \
  -e GEMINI_API_KEY="your-key" \
  aureasim:1.3.0
```

Omit the environment variable when using offline examples.
