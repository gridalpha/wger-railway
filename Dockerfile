# wger on Railway
#
# Upstream publishes a complete application image; everything below exists because
# Railway's shape differs from the docker-compose stack upstream ships:
#
#   * upstream puts an nginx container in front of gunicorn to serve /static/ and
#     /media/ from two volumes shared with the web and celery containers. Railway
#     volumes are strictly 1:1, so the reverse proxy moves *into* this container:
#     Caddy serves the collected static files from the image and hands /media/ to a
#     small signing proxy in front of Railway's managed object storage.
#   * the JWT signing keypair the mobile app uses is a matched RSA pair. No Railway
#     variable can compute one, so it is generated once at boot and shared through
#     the application database.
#   * the image seeds a published default admin password on first boot; the
#     entrypoint replaces it before the server binds.
#
# The same image runs all three roles (web, celery worker, celery beat); WGER_ROLE
# selects which.

FROM caddy:2-alpine AS caddy

# Pinned: docker.io/wger/server:latest is the 2.8.0-dev branch build, not the
# release line, and the three services built from this repo must be the same build.
FROM wger/server:2.7

USER root

COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY railway/Caddyfile /etc/caddy/Caddyfile
COPY railway/entrypoint.sh /home/wger/railway/entrypoint.sh
COPY railway/jwt_keys.py railway/seed_admin.py railway/media_proxy.py railway/child_health.py /home/wger/railway/

RUN set -eux; \
    chmod +x /home/wger/railway/entrypoint.sh; \
    chown -R wger:wger /home/wger/railway; \
    caddy version; \
    bash -n /home/wger/railway/entrypoint.sh; \
    PORT=8080 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

USER wger
WORKDIR /home/wger/src

# As the runtime user: wger installs its python packages with `pip3 install --user`,
# so root cannot see them and an import check above would test the wrong interpreter.
RUN set -eux; \
    for f in /home/wger/railway/*.py; do python3 -m py_compile "$f"; done; \
    python3 -c "import boto3, psycopg, jwt, cryptography, gevent"

CMD ["/home/wger/railway/entrypoint.sh"]
