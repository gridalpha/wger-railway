"""
Serve wger's media files from Railway's managed object storage.

Railway's bucket has no anonymous read: a plain GET is 403 on both addressing
styles and PutBucketPolicy is not implemented, so the bucket cannot be opened for
a prefix either. wger hardcodes AWS_QUERYSTRING_AUTH = False, so django-storages
hands the browser unsigned URLs - which means the URLs it renders have to point at
something that signs on the reader's behalf.

This is that something: a loopback-only HTTP server that Caddy routes /media/* to.
It signs with the same bucket credentials the app writes with, streams the body
back, and passes Range requests through so uploaded videos can be seeked. It will
only read keys under the media prefix, so the app's own objects elsewhere in the
bucket stay unreachable.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import boto3
from botocore.client import Config

BIND = ('127.0.0.1', int(os.environ.get('WGER_MEDIA_PROXY_PORT', '8081')))
BUCKET = os.environ['AWS_STORAGE_BUCKET_NAME']
PREFIX = os.environ.get('S3_MEDIA_FILES_LOCATION', 'media').strip('/')
CHUNK = 64 * 1024

s3 = boto3.client(
    's3',
    endpoint_url=os.environ['AWS_S3_ENDPOINT_URL'],
    aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
    region_name=os.environ.get('AWS_S3_REGION_NAME', 'auto'),
    config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
)

PASS_THROUGH = (
    ('ContentType', 'Content-Type'),
    ('ContentLength', 'Content-Length'),
    ('ETag', 'ETag'),
    ('ContentRange', 'Content-Range'),
    ('ContentEncoding', 'Content-Encoding'),
    ('ContentDisposition', 'Content-Disposition'),
)


def key_for(path):
    """Map a request path to a bucket key, or None if it is out of bounds."""
    key = unquote(urlparse(path).path).lstrip('/')
    if not key or not key.startswith(PREFIX + '/'):
        return None
    parts = key.split('/')
    if any(p in ('', '.', '..') for p in parts):
        return None
    return key


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'wger-media-proxy'

    def log_message(self, fmt, *args):  # keep the loopback hop out of the deploy log
        pass

    def _fail(self, code, message):
        body = message.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _serve(self, body_wanted):
        key = key_for(self.path)
        if key is None:
            self._fail(404, 'not found')
            return

        kwargs = {'Bucket': BUCKET, 'Key': key}
        rng = self.headers.get('Range')
        if rng:
            kwargs['Range'] = rng

        try:
            obj = s3.get_object(**kwargs)
        except s3.exceptions.NoSuchKey:
            self._fail(404, 'not found')
            return
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode')
            if code in (404, 416):
                self._fail(code, 'not found' if code == 404 else 'range not satisfiable')
                return
            print(f'[media-proxy] {key}: {exc}', file=sys.stderr, flush=True)
            self._fail(502, 'storage error')
            return

        self.send_response(206 if 'ContentRange' in obj else 200)
        for src, header in PASS_THROUGH:
            if obj.get(src) is not None:
                self.send_header(header, str(obj[src]))
        if obj.get('LastModified'):
            self.send_header('Last-Modified', obj['LastModified'].strftime('%a, %d %b %Y %H:%M:%S GMT'))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()

        stream = obj['Body']
        try:
            if body_wanted:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stream.close()

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)


def main():
    print(
        f'[media-proxy] serving bucket {BUCKET} prefix {PREFIX}/ on '
        f'{BIND[0]}:{BIND[1]}',
        file=sys.stderr,
        flush=True,
    )
    ThreadingHTTPServer(BIND, Handler).serve_forever()


if __name__ == '__main__':
    main()
