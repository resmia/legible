from urllib.error import HTTPError, URLError
from http.client import HTTPConnection, HTTPSConnection, HTTPException, HTTPResponse, IncompleteRead
import socket
import time
import zlib
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.request import build_opener, HTTPHandler, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request

from legible.fetch.models import FetchObservation, FetchMetadata, RedirectObservation
from legible.fetch.safety import UnsafeURL, public_addresses, validated_target, evidence_url

TIMEOUT = 15
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_REDIRECTS = 5
PUBLIC_HEADERS = {
    'User-Agent': 'Legible/0.1 (public integration documentation scanner)',
    'Accept': 'text/html, text/markdown, text/plain, application/json, application/yaml, text/yaml, */*;q=0.5',
    'Accept-Encoding': 'identity',
    'Connection': 'close',
}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Public-resource request deadline exceeded')
    return min(TIMEOUT, remaining)


def urlopen(url):
    """Validate every connection, pin its resolved address, and keep TLS hostname checks."""
    deadline = time.monotonic() + TIMEOUT
    visited = {urldefrag(url)[0]}
    redirects = []
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeURL('Unsupported URL or embedded credentials')
    local = None
    if parsed.hostname in {'localhost', '127.0.0.1', '::1'}:
        local = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))

    validated_target(url, local)

    def connect(address, timeout=TIMEOUT, source_address=None, **kwargs):
        host, port = address
        scheme = 'https' if port == 443 else 'http'
        # Validation uses the original local scheme only for explicit loopback tests.
        if local and host == local[1] and port == local[2]:
            scheme = local[0]
        netloc = f'[{host}]' if ':' in host else host
        addresses = public_addresses(f'{scheme}://{netloc}:{port}', local)
        last = None
        for family, kind, proto, _, sockaddr in addresses:
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(min(timeout, _remaining(deadline)))
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last = exc
                sock.close()
        raise last

    class PublicHTTP(HTTPConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = connect

    class PublicHTTPS(HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = connect

    class HTTP(HTTPHandler):
        def http_open(self, req):
            return self.do_open(PublicHTTP, req)

    class HTTPS(HTTPSHandler):
        def https_open(self, req):
            return self.do_open(PublicHTTPS, req, context=self._context)

    class Redirects(HTTPRedirectHandler):
        max_redirections = MAX_REDIRECTS
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urlsplit(newurl)
            if target.scheme not in {'http', 'https'} or target.username is not None or target.password is not None:
                raise UnsafeURL('Unsafe redirect URL')
            if req.type == 'https' and target.scheme != 'https':
                raise UnsafeURL('HTTPS redirect downgrade rejected')
            public_addresses(newurl, local)
            newurl = urldefrag(newurl)[0]
            if newurl in visited:
                raise UnsafeURL('Redirect loop rejected')
            if len(visited) > MAX_REDIRECTS:
                raise UnsafeURL('Redirect limit exceeded')
            visited.add(newurl)
            redirects.append(RedirectObservation(evidence_url(req.full_url), evidence_url(newurl), code))
            return Request(newurl, headers=PUBLIC_HEADERS, method='GET')

        def http_error_302(self, req, fp, code, msg, headers):
            location = headers.get('Location') or headers.get('URI')
            if not location:
                return None
            try:
                if any(ord(c) < 33 or ord(c) == 127 for c in location):
                    raise UnsafeURL('Invalid redirect location')
                redirect = self.redirect_request(req, fp, code, msg, headers,
                                                 urljoin(req.full_url, location))
            finally:
                # Never consume an unbounded redirect body.
                fp.close()
            return self.parent.open(redirect, timeout=_remaining(deadline))

        http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    opener = build_opener(ProxyHandler({}), HTTP(), HTTPS(), Redirects())
    try:
        response = opener.open(Request(url, headers=PUBLIC_HEADERS, method='GET'), timeout=_remaining(deadline))
    except HTTPError as exc:
        exc.legible_deadline = deadline
        exc.legible_redirects = tuple(redirects)
        raise
    except (URLError, OSError, HTTPException, ValueError) as exc:
        exc.legible_redirects = tuple(redirects)
        raise
    response.legible_deadline = deadline
    response.legible_redirects = tuple(redirects)
    return response


def _read_body(response, stats=None):
    stats = stats if stats is not None else {}
    deadline = getattr(response, 'legible_deadline', None)
    if isinstance(response, HTTPError) and isinstance(response.fp, HTTPResponse):
        response = response.fp
    encoding = (response.headers.get('Content-Encoding') or 'identity').lower().strip()
    if encoding not in {'identity', 'gzip', 'deflate'}:
        raise OSError('Unsupported response content encoding')
    decoder = zlib.decompressobj(31 if encoding == 'gzip' else 15) if encoding != 'identity' else None
    lengths = response.headers.get_all('Content-Length', [])
    declared = None
    if lengths:
        if len(lengths) != 1 or not lengths[0].strip().isdigit():
            raise OSError('Invalid or conflicting Content-Length')
        declared = int(lengths[0])
    body = bytearray()
    wire_bytes = 0
    # Connection: close makes EOF the framing boundary. Do not trust a falsely
    # small Content-Length; chunked framing is still handled by HTTPResponse.
    if isinstance(response, HTTPResponse) and not response.chunked:
        response.length = None
    read = response.read1 if isinstance(response, HTTPResponse) else response.read
    while True:
        if isinstance(deadline, (int, float)):
            remaining = _remaining(deadline)
            if isinstance(response, HTTPResponse) and response.fp:
                response.fp.raw._sock.settimeout(remaining)
        chunk = read(min(65536, MAX_RESPONSE_BYTES - len(body) + 1))
        if not chunk:
            break
        wire_bytes += len(chunk)
        stats['encoded_bytes'] = wire_bytes
        # Encoded data has its own small overhead allowance; decoded data never does.
        if wire_bytes > MAX_RESPONSE_BYTES + 65536:
            raise OSError('Response exceeds public-resource size limit')
        decoded = decoder.decompress(chunk, MAX_RESPONSE_BYTES - len(body) + 1) if decoder else chunk
        body.extend(decoded)
        stats['decoded_bytes'] = len(body)
        if len(body) > MAX_RESPONSE_BYTES:
            raise OSError('Response exceeds public-resource size limit')
        if decoder and (decoder.unused_data or decoder.unconsumed_tail):
            raise OSError('Invalid or oversized compressed response')
    if declared is not None and declared != wire_bytes:
        raise OSError('Response length does not match Content-Length')
    if decoder and not decoder.eof:
        raise OSError('Truncated compressed response')
    stats['complete'] = True
    return bytes(body)


def _observe_response(url: str, response, error: str | None = None) -> FetchObservation:
    final_url = evidence_url(response.geturl())
    status = response.status
    content_type = response.headers.get("Content-Type")
    text = None
    stats = {}
    truncated = False
    transport_response = response.fp if isinstance(response, HTTPError) and isinstance(response.fp, HTTPResponse) else response
    method = getattr(transport_response, '_method', 'GET')
    method = method if isinstance(method, str) else 'GET'
    redirects = getattr(response, 'legible_redirects', ())
    redirects = redirects if isinstance(redirects, tuple) else ()
    if method != 'GET':
        return FetchObservation(evidence_url(url), final_url, status, content_type, None,
                                'No document body: reachability probe', FetchMetadata(method=method, redirects=redirects))
    try:
        body = _read_body(response, stats)
        text = body.decode(response.headers.get_content_charset() or "utf-8")
    except (OSError, HTTPException, UnicodeError, LookupError, zlib.error) as exc:
        truncated = isinstance(exc, IncompleteRead) or 'length does not match' in str(exc) or 'Truncated compressed' in str(exc)
        detail = f"Could not read response: {exc}"
        error = f"{error}; {detail}" if error else detail
    metadata = FetchMetadata(method, redirects, stats.get('encoded_bytes', 0),
                             len(body) if text is not None else 0,
                             truncated or bool(stats.get('encoded_bytes') and not stats.get('complete')),
                             response.headers.get('Content-Encoding') or 'identity')
    return FetchObservation(evidence_url(url), final_url, status, content_type, text, error, metadata)


def fetch_page(url: str) -> FetchObservation:
    """Fetch once, preserving response evidence and expected failures."""
    try:
        with urlopen(url) as response:
            return _observe_response(url, response)
    except HTTPError as exc:
        with exc:
            return _observe_response(url, exc, f"HTTP error: {exc.code}")
    except URLError as exc:
        return FetchObservation(evidence_url(url), error=f"Could not reach URL: {str(exc.reason).replace(url, evidence_url(url))}", metadata=FetchMetadata(redirects=getattr(exc, 'legible_redirects', ())))
    except (OSError, HTTPException, ValueError) as exc:
        return FetchObservation(evidence_url(url), error=f"Could not reach URL: {str(exc).replace(url, evidence_url(url))}", metadata=FetchMetadata(redirects=getattr(exc, 'legible_redirects', ())))
