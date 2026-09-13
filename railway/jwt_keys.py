"""
Generate the RS256 keypair wger signs mobile-app JWTs with, once per deployment,
and share it between the web, worker and beat services through the application
database.

The pair is a *matched* one: no Railway variable can compute it, and a mismatch
between services deploys green and rejects every token. The first container to
boot generates it and writes both halves in one transaction; every other
container reads the row back. An operator who sets JWT_PRIVATE_KEY and
JWT_PUBLIC_KEY themselves wins - this script is never reached in that case.

Prints shell-quoted assignments on stdout; the entrypoint sources them.
"""

import json
import os
import shlex
import sys
import time
from base64 import urlsafe_b64encode

import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

TABLE = 'wger_railway_secrets'
KID = 'wger'


def log(msg):
    print(f'[jwt-keys] {msg}', file=sys.stderr)


def connect():
    """Wait for the database. Railway has no service ordering, so this doubles as
    the 'is Postgres up yet?' gate for every role."""
    dsn = dict(
        dbname=os.environ['DJANGO_DB_DATABASE'],
        user=os.environ['DJANGO_DB_USER'],
        password=os.environ.get('DJANGO_DB_PASSWORD', ''),
        host=os.environ['DJANGO_DB_HOST'],
        port=int(os.environ.get('DJANGO_DB_PORT', '5432')),
        connect_timeout=10,
    )
    last = None
    for attempt in range(1, 61):
        try:
            return psycopg.connect(**dsn)
        except Exception as exc:  # noqa: BLE001 - any driver error is a retry
            last = exc
            if attempt == 1 or attempt % 5 == 0:
                log(f'database not reachable yet (attempt {attempt}): {exc}')
            time.sleep(5)
    raise SystemExit(f'[jwt-keys] database never became reachable: {last}')


def generate():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = json.loads(RSAAlgorithm.to_jwk(key))
    priv['alg'] = 'RS256'
    priv['kid'] = KID
    pub = {k: priv[k] for k in ('kty', 'n', 'e', 'alg', 'kid')}

    def b64(d):
        return urlsafe_b64encode(json.dumps(d).encode()).decode()

    return b64(priv), b64(pub)


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS {TABLE} ('
                '  name TEXT PRIMARY KEY,'
                '  value TEXT NOT NULL,'
                '  created_at TIMESTAMPTZ NOT NULL DEFAULT now())'
            )
            conn.commit()

            cur.execute(
                f'SELECT name, value FROM {TABLE} WHERE name IN (%s, %s)',
                ('jwt_private_key', 'jwt_public_key'),
            )
            found = dict(cur.fetchall())

            if len(found) != 2:
                priv, pub = generate()
                # Both halves in one statement, so a container that loses the race
                # cannot end up with one generated key and one stored one.
                cur.execute(
                    f'INSERT INTO {TABLE} (name, value) VALUES (%s, %s), (%s, %s) '
                    'ON CONFLICT (name) DO NOTHING',
                    ('jwt_private_key', priv, 'jwt_public_key', pub),
                )
                conn.commit()
                cur.execute(
                    f'SELECT name, value FROM {TABLE} WHERE name IN (%s, %s)',
                    ('jwt_private_key', 'jwt_public_key'),
                )
                found = dict(cur.fetchall())
                log('generated and stored a fresh RS256 keypair')
            else:
                log('reusing the stored RS256 keypair')

    if len(found) != 2:
        raise SystemExit('[jwt-keys] could not read the keypair back')

    print(f'export JWT_PRIVATE_KEY={shlex.quote(found["jwt_private_key"])}')
    print(f'export JWT_PUBLIC_KEY={shlex.quote(found["jwt_public_key"])}')


if __name__ == '__main__':
    main()
