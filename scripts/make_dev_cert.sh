#!/usr/bin/env bash
# Self-signed certificate for exercising the HTTPS proxy locally (browsers will warn).
set -euo pipefail
cd "$(dirname "$0")/../infra/certs"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout localhost.key -out localhost.pem 2>/dev/null
chmod 600 localhost.key
echo "wrote infra/certs/localhost.pem and localhost.key (gitignored)"
