#!/usr/bin/env bash
# Run ON THE SERVER: create deploy/.env.production with fresh random secrets (never overwrites).
set -euo pipefail
cd "$(dirname "$0")"
[ -e .env.production ] && { echo ".env.production exists; not overwriting"; exit 0; }
: "${MARKETOPS_DOMAIN:?export MARKETOPS_DOMAIN first}" "${ACME_EMAIL:?export ACME_EMAIL first}"
gen() { python3 -c "import secrets; print(secrets.token_urlsafe(24))"; }
umask 077
sed -e "s|^MARKETOPS_DOMAIN=.*|MARKETOPS_DOMAIN=${MARKETOPS_DOMAIN}|" \
    -e "s|^ACME_EMAIL=.*|ACME_EMAIL=${ACME_EMAIL}|" \
    -e "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=$(gen)|" \
    -e "s|^DEMO_OPERATOR_PASSWORD=$|DEMO_OPERATOR_PASSWORD=$(gen)|" \
    -e "s|^DEMO_OPERATOR2_PASSWORD=$|DEMO_OPERATOR2_PASSWORD=$(gen)|" \
    -e "s|^DEMO_VIEWER_PASSWORD=$|DEMO_VIEWER_PASSWORD=$(gen)|" \
    .env.production.example > .env.production
echo "wrote deploy/.env.production (mode 600). Operator passwords are only in this file."
