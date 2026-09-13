#!/bin/bash
#
# One entrypoint for all three wger roles. WGER_ROLE picks which: web (default),
# worker or beat.
set -euo pipefail

cd /home/wger/src

echo "[entrypoint] role=${WGER_ROLE:-web}"

# The mobile app's JWT keypair. Generated once and shared through the database so
# every role signs and verifies with the same key; an operator-supplied pair wins.
if [[ -z "${JWT_PRIVATE_KEY:-}" || -z "${JWT_PUBLIC_KEY:-}" ]]; then
    python3 /home/wger/railway/jwt_keys.py > /tmp/jwt-keys.env
    # shellcheck disable=SC1091
    source /tmp/jwt-keys.env
    rm -f /tmp/jwt-keys.env
else
    echo "[entrypoint] using the JWT keypair from the environment"
fi

case "${WGER_ROLE:-web}" in
    worker)
        exec python3 /home/wger/railway/child_health.py -- /start-worker
        ;;
    beat)
        exec python3 /home/wger/railway/child_health.py -- /start-beat
        ;;
    web)
        ;;
    *)
        echo "[entrypoint] unknown WGER_ROLE '${WGER_ROLE}', expected web|worker|beat" >&2
        exit 1
        ;;
esac

# First boot only: migrate, load the exercise/muscle/language fixtures and create
# the admin user. A no-op once the user table has rows.
wger bootstrap --no-process-static

echo "[entrypoint] collecting static files"
python3 manage.py collectstatic --no-input

echo "[entrypoint] applying database migrations"
python3 manage.py migrate --no-input

# django.contrib.sites row, from SITE_URL. Without it wger builds links against
# example.com and bounces visitors off the deployment.
python3 manage.py set-site-url

# Runs before anything binds a public port, so the shipped admin/adminadmin
# credential is never reachable.
python3 /home/wger/railway/seed_admin.py

python3 /home/wger/railway/media_proxy.py &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &

echo "[entrypoint] starting gunicorn on 127.0.0.1:8000 behind Caddy on ${PORT:-8080}"
exec gunicorn wger.wsgi:application --preload --bind 127.0.0.1:8000
