#!/bin/sh
# Tools Control — start on macOS/Linux. TC_DEMO=1 ./start.sh for pretend chats and tools.
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
echo "Tools Control on http://127.0.0.1:${PORT:-8450}"
exec .venv/bin/python -m uvicorn tctl.main:app --host 127.0.0.1 --port "${PORT:-8450}" --log-level warning
