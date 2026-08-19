#!/usr/bin/env bash
#
# Starts all three Curriculum Portal services (nlp-engine, backend, frontend)
# in one command, in dependency order, with readiness checks between them.
#
#     nlp-engine (:8000) -> backend (:4000) -> frontend (:5173)
#
# Each service starts only once the previous one reports healthy, so you never
# get a frontend loading against a backend that can't analyze anything. All
# three run as children of this script — Ctrl+C once stops every one of them.
#
# Postgres is NOT started here: it's usually a system service or a Docker
# container with its own lifecycle. The nlp-engine's readiness check covers
# whether the database is reachable and seeded — see RUN.md step 1.
#
# Usage:
#     ./start-all.sh --install     # first run: venv, pip, spaCy model, npm install
#     ./start-all.sh               # every run after that
#     ./start-all.sh --no-health-wait
#
# The PowerShell equivalent for Windows is start-all.ps1.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NLP_DIR="$ROOT/nlp-engine"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_PYTHON="$NLP_DIR/venv/bin/python"

BIND_HOST="${BIND_HOST:-127.0.0.1}"
NLP_PORT="${NLP_PORT:-8000}"
BACKEND_PORT="${BACKEND_PORT:-4000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
# The first ever run downloads ~100MB of models, so be patient by default.
READY_TIMEOUT="${READY_TIMEOUT:-900}"

DO_INSTALL=false
HEALTH_WAIT=true

for arg in "$@"; do
  case "$arg" in
    --install) DO_INSTALL=true ;;
    --no-health-wait) HEALTH_WAIT=false ;;
    -h|--help) sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }
err()  { printf '\033[31m    %s\033[0m\n' "$1" >&2; }
note() { printf '\033[90m    %s\033[0m\n' "$1"; }

PIDS=()
NAMES=()
LAST_PID=""
HEALTH_BODY=""

cleanup() {
  if [ ${#PIDS[@]} -eq 0 ]; then return; fi
  printf '\n\033[36m==> Shutting down...\033[0m\n'
  # Reverse order, so dependents stop before what they depend on and nothing
  # logs connection errors on the way out.
  local i pid
  for (( i=${#PIDS[@]}-1; i>=0; i-- )); do
    pid="${PIDS[$i]}"
    if kill -0 "$pid" 2>/dev/null; then
      note "stopping ${NAMES[$i]}..."
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  # Anything that ignored SIGTERM (node --watch can outlive its child) gets
  # killed outright rather than left holding a port.
  for pid in "${PIDS[@]}"; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  PIDS=()
  ok "All services stopped."
}
trap cleanup EXIT INT TERM

# Starts a service in the background and sets LAST_PID. Deliberately doesn't
# echo the pid: the progress lines share stdout, so a caller using $(...) to
# capture it would get the log text too.
start_service() {
  local name="$1" dir="$2"; shift 2
  note "starting $name..."
  # exec so the backgrounded subshell *becomes* the service — then $! is the
  # service's own pid and cleanup can signal it directly.
  ( cd "$dir" && exec "$@" ) &
  LAST_PID=$!
  PIDS+=("$LAST_PID")
  NAMES+=("$name")
}

port_in_use() {
  # No lsof/ss dependency: bash's own /dev/tcp is enough for a connect test.
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# Echoes the health body; returns non-zero only when nothing answered at all.
# `curl -f` is deliberately NOT used: a 503 readiness response carries the body
# explaining *which* dependency isn't ready, and we want to show that.
health_body() {
  curl -fsS --max-time 5 "$1" 2>/dev/null || curl -sS --max-time 5 "$1" 2>/dev/null
}

is_ready() {
  local body="$1"
  # No jq dependency: readiness is a single well-known boolean field, and a
  # body with no `ready` field at all (plain liveness) counts as ready.
  case "$body" in
    *'"ready":true'*|*'"ready": true'*)  return 0 ;;
    *'"ready":false'*|*'"ready": false'*) return 1 ;;
    *'"status"'*) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_ready() {
  local name="$1" url="$2" timeout="$3" pid="$4"
  local deadline=$(( $(date +%s) + timeout ))
  local last_note=""
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      err "$name exited before becoming ready. See its output above."
      exit 1
    fi
    local body
    body="$(health_body "$url" || true)"
    if [ -n "$body" ]; then
      if is_ready "$body"; then
        HEALTH_BODY="$body"
        return 0
      fi
      if [ "$body" != "$last_note" ]; then
        note "waiting on $name - not ready yet"
        last_note="$body"
      fi
    fi
    sleep 2
  done
  err "$name did not become ready within ${timeout}s. Check its output above, or query $url directly."
  exit 1
}

run_setup() {
  step "First-time setup"
  if [ ! -x "$VENV_PYTHON" ]; then
    note "creating Python venv..."
    python3 -m venv "$NLP_DIR/venv"
  fi
  note "installing Python requirements (this takes a few minutes)..."
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install -r "$NLP_DIR/requirements.txt"
  note "downloading the spaCy model..."
  "$VENV_PYTHON" -m spacy download en_core_web_sm
  for dir in "$BACKEND_DIR" "$FRONTEND_DIR"; do
    note "npm install in $(basename "$dir")..."
    ( cd "$dir" && npm install )
  done
  ok "Setup complete."
}

ensure_env_file() {
  local dir="$1" name="$2"
  if [ -f "$dir/.env" ] || [ ! -f "$dir/.env.example" ]; then return; fi
  cp "$dir/.env.example" "$dir/.env"
  warn "$name had no .env - copied .env.example. Check its DATABASE_URL before relying on it."
}

# ---------------------------------------------------------------------------

step "Checking prerequisites"
for tool in node npm python3 curl; do
  command -v "$tool" >/dev/null 2>&1 || { err "'$tool' was not found on PATH. See RUN.md for prerequisites."; exit 1; }
done
ok "node $(node -v), npm $(npm -v), $(python3 --version)"

for pair in "$NLP_DIR:nlp-engine" "$BACKEND_DIR:backend" "$FRONTEND_DIR:frontend"; do
  dir="${pair%%:*}"; name="${pair##*:}"
  [ -d "$dir" ] || { err "Missing directory: $dir. Run this script from inside curriculum-portal/."; exit 1; }
  ensure_env_file "$dir" "$name"
done

if $DO_INSTALL; then run_setup; fi

[ -x "$VENV_PYTHON" ] || { err "No Python venv at $VENV_PYTHON. Run './start-all.sh --install' once."; exit 1; }
for dir in "$BACKEND_DIR" "$FRONTEND_DIR"; do
  [ -d "$dir/node_modules" ] || { err "No node_modules in $dir. Run './start-all.sh --install' once."; exit 1; }
done

for pair in "$NLP_PORT:nlp-engine" "$BACKEND_PORT:backend" "$FRONTEND_PORT:frontend"; do
  port="${pair%%:*}"; name="${pair##*:}"
  if port_in_use "$port"; then
    err "Port $port ($name) is already in use. Stop whatever is listening on it and try again."
    exit 1
  fi
done
ok "Ports $NLP_PORT / $BACKEND_PORT / $FRONTEND_PORT are free."

step "Starting nlp-engine on http://$BIND_HOST:$NLP_PORT"
start_service nlp-engine "$NLP_DIR" "$VENV_PYTHON" -m uvicorn app.main:app --host "$BIND_HOST" --port "$NLP_PORT"
NLP_PID="$LAST_PID"
if $HEALTH_WAIT; then
  note "waiting for models to load and the database to answer..."
  wait_for_ready nlp-engine "http://$BIND_HOST:$NLP_PORT/health" "$READY_TIMEOUT" "$NLP_PID"
  ok "nlp-engine ready."
  case "$HEALTH_BODY" in
    *'"nep_competencies"'*'"status": "empty"'*|*'"nep_competencies"'*'"status":"empty"'*)
      warn "nep_competencies is empty - reports will have a null NEP score. Fix: python database/seed_nep.py" ;;
  esac
fi

step "Starting backend on http://localhost:$BACKEND_PORT"
start_service backend "$BACKEND_DIR" node --watch server.js
if $HEALTH_WAIT; then
  wait_for_ready backend "http://localhost:$BACKEND_PORT/api/health" 60 "$LAST_PID"
  ok "backend ready."
fi

step "Starting frontend on http://localhost:$FRONTEND_PORT"
# Vite's bin script directly, not `npm run dev`: the npm wrapper adds a shell
# process between us and vite, which makes clean shutdown harder.
start_service frontend "$FRONTEND_DIR" node node_modules/vite/bin/vite.js --port "$FRONTEND_PORT" --strictPort

printf '\n\033[32m=========================================================\n'
printf ' All services running\n'
printf '   frontend    http://localhost:%s\n' "$FRONTEND_PORT"
printf '   backend     http://localhost:%s/api/health\n' "$BACKEND_PORT"
printf '   nlp-engine  http://%s:%s/health\n' "$BIND_HOST" "$NLP_PORT"
printf '   all-in-one  http://localhost:%s/api/health/full\n' "$BACKEND_PORT"
printf ' Press Ctrl+C to stop all three.\n'
printf '=========================================================\033[0m\n\n'

# Block until Ctrl+C, or until any service dies (in which case say which).
while true; do
  for i in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
      err "${NAMES[$i]} exited. Stopping the rest."
      exit 1
    fi
  done
  sleep 1
done
