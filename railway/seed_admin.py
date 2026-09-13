"""
Replace the published default admin password.

`wger bootstrap` loads a fixture that creates `admin` with the password
`adminadmin`, documented in upstream's own README. On a public URL that is a live
credential, so the entrypoint runs this before the server binds.

It only ever acts while the stored password is still the shipped default, so an
operator who changes the password in the admin is never reverted, and a redeploy
is a no-op.
"""

import os
import secrets
import sys

import django

django.setup()

from django.contrib.auth.models import User  # noqa: E402

DEFAULT_PASSWORD = 'adminadmin'


def log(msg):
    print(f'[seed-admin] {msg}', file=sys.stderr)


def main():
    user = User.objects.filter(username='admin').first()
    if user is None:
        log('no admin user found, nothing to do')
        return

    if not user.check_password(DEFAULT_PASSWORD):
        log('admin password has already been changed, leaving it alone')
        return

    password = os.environ.get('WGER_ADMIN_PASSWORD', '').strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(24)
        generated = True

    user.set_password(password)
    user.is_staff = True
    user.is_superuser = True
    email = os.environ.get('WGER_ADMIN_EMAIL', '').strip()
    if email:
        user.email = email
    user.save()

    if generated:
        log('=' * 72)
        log('WGER_ADMIN_PASSWORD was not set, so a random password was generated')
        log(f'    username: admin')
        log(f'    password: {password}')
        log('Set WGER_ADMIN_PASSWORD on every wger service to pick your own.')
        log('=' * 72)
    else:
        log('admin password set from WGER_ADMIN_PASSWORD')


if __name__ == '__main__':
    main()
