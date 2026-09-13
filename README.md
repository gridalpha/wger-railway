# wger on Railway

Deployment image for [wger](https://github.com/wger-project/wger), the FLOSS
workout, nutrition and weight tracker, built for Railway.

One image, three roles. `WGER_ROLE` selects which:

| `WGER_ROLE` | Process | Public |
|---|---|---|
| `web` (default) | Caddy on `$PORT` in front of gunicorn, plus the media proxy | yes |
| `worker` | `celery worker`, behind an HTTP liveness probe on `$PORT` | no |
| `beat` | `celery beat`, behind an HTTP liveness probe on `$PORT` | no |

## Why this repo exists

Upstream's `docker.io/wger/server` image is complete; these are the three gaps
between its docker-compose stack and Railway.

**Static and media files.** Upstream runs an nginx container that serves
`/static/` and `/media/` from two volumes it shares with the web and celery
containers. Railway volumes are 1:1, so that layout cannot be reproduced.
Instead:

- `/static/` is served by a Caddy inside this container, straight from the
  `collectstatic` output in the image filesystem.
- `/media/` lives in Railway's managed object storage, which both the web and the
  worker write to. The bucket has no anonymous read and wger hardcodes
  `AWS_QUERYSTRING_AUTH = False`, so `railway/media_proxy.py` signs and streams
  those reads on the browser's behalf, on loopback, restricted to the media
  prefix. `AWS_S3_CUSTOM_DOMAIN` therefore points at the app's own public domain.

**The JWT keypair.** wger signs the mobile app's tokens with an RS256 keypair and
ships a published default. It is a *matched* pair, so no Railway variable can
generate one. `railway/jwt_keys.py` generates it at first boot and stores it in
the application database, where the worker and beat read the same pair back. Set
`JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` yourself to override.

**The default admin password.** `wger bootstrap` seeds `admin` / `adminadmin`
from a fixture. `railway/seed_admin.py` replaces it from `WGER_ADMIN_PASSWORD`
before anything binds a port, and only while the password is still that default,
so it never reverts a change made in the admin.

## Variables

Everything upstream documents in
[`config/prod.env`](https://github.com/wger-project/docker/blob/master/config/prod.env)
applies. The ones this repo adds or needs:

| Variable | Purpose |
|---|---|
| `WGER_ROLE` | `web`, `worker` or `beat` |
| `WGER_ADMIN_PASSWORD` | replaces the seeded default admin password |
| `WGER_ADMIN_EMAIL` | optional; sets the admin's address at the same time |
| `AWS_S3_CUSTOM_DOMAIN` | the app's public domain, so media URLs come back through the signing proxy |
| `WGER_MEDIA_PROXY_PORT` | loopback port for the media proxy (default `8081`) |

## Licence

wger is AGPL-3.0-or-later. This repo carries only deployment glue; see
[LICENSE](LICENSE).
