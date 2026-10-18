#!/usr/bin/env bash
# Linux/macOS launcher (this is the path tested in development). Starts the factory server; optional n8n if installed.
cd "$(dirname "$0")"
[ -f secrets/automation_token ] || python3 -c "import secrets;open('secrets/automation_token','w').write(secrets.token_urlsafe(32))"
export FACTORY_TOKEN=$(cat secrets/automation_token) N8N_BLOCK_ENV_ACCESS_IN_NODE=false
if command -v n8n >/dev/null; then
  [ -f data/n8n/.imported ] || { mkdir -p data/n8n && N8N_USER_FOLDER=$PWD/data/n8n n8n import:workflow --separate --input=n8n/workflows && touch data/n8n/.imported; }
  N8N_USER_FOLDER=$PWD/data/n8n n8n start &
fi
exec python3 -m factory serve
