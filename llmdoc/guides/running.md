# Running DeepCode

This guide summarizes the supported ways to run DeepCode locally.

## Option 1: Docker (Recommended)

Docker runs the FastAPI backend and serves the built frontend.

### Start

```bash
./deepcode_docker/run_docker.sh -d
```

Then open:

- `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

### CLI In Docker

```bash
deepcode --cli
```

Or via the script:

```bash
./deepcode_docker/run_docker.sh cli
```

### Stop

```bash
./deepcode_docker/run_docker.sh stop
```

## Option 2: Local New UI (FastAPI + React)

This runs two dev processes.

### Start (one command)

```bash
deepcode --local
```

### Start (manual)

```bash
cd new_ui
chmod +x scripts/start_dev.sh
./scripts/start_dev.sh
```

Endpoints:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

## Option 3: Classic Streamlit UI

```bash
deepcode --classic
```

Default Streamlit URL:

- `http://localhost:8501`

## Option 4: Python CLI (Direct)

Interactive mode:

```bash
python cli/main_cli.py
```

Non-interactive examples:

```bash
python cli/main_cli.py --file /path/to/paper.pdf
python cli/main_cli.py --url https://arxiv.org/abs/...
python cli/main_cli.py --chat "Build a web app that ..."
python cli/main_cli.py --requirement "I want to build ..."
```
