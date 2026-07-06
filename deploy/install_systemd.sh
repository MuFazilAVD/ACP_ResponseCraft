#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-response-drafter}"
PORT="${PORT:-8006}"
PYTHON_BIN="${PYTHON_BIN:-python3.14}"
WORKERS="${WORKERS:-4}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/venv}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn)}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "ERROR: ${PYTHON_BIN} was not found on PATH."
  echo "Install Python 3.14 first, or run with PYTHON_BIN=/absolute/path/to/python3.14."
  exit 1
fi

cd "${APP_DIR}"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -r requirements.txt

if [ ! -f "${APP_DIR}/.env" ] && [ -f "${APP_DIR}/.env.example" ]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from .env.example. Review secrets and runtime values before production traffic."
fi

SERVICE_CONTENT="[Unit]
Description=TCS RFP Response Drafter FastAPI Application
After=network.target

[Service]
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
Environment=\"PATH=${VENV_DIR}/bin\"
EnvironmentFile=-${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/gunicorn \\
  -w ${WORKERS} \\
  -k uvicorn.workers.UvicornWorker \\
  response_drafter_agent.main:app \\
  --bind 0.0.0.0:${PORT} \\
  --access-logfile - \\
  --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"

printf "%s" "${SERVICE_CONTENT}" | sudo tee "${SERVICE_FILE}" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now "${APP_NAME}.service"

echo "Installed and started ${APP_NAME}.service on port ${PORT}."
echo "Check status: sudo systemctl status ${APP_NAME}.service"
echo "View logs:    sudo journalctl -u ${APP_NAME}.service -f"
