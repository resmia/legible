"""Transport regressions use fictional hosts and bounded in-memory streams."""
import gzip
import io
import socket
import ssl
from email.message import Message
from unittest.mock import MagicMock
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request

import pytest
from legible.fetch import page, safety


def response(body, encoding=None, length=None):
    r = io.BytesIO(body)
    r.status = 200
    r.geturl = lambda: 'https://docs.widget.test/contract'
    r.headers = Message()
    r.headers['Content-Type'] = 'text/plain'
    if encoding: r.headers['Content-Encoding'] = encoding
    if length: r.headers['Content-Length'] = length
    return r


@pytest.mark.parametrize('encoding', [None, 'gzip', 'deflate'])
@pytest.mark.parametrize('size', [8, 9, 100000])
def test_decoded_stream_limit(monkeypatch, encoding, size):
    import zlib
    body = b'x' * size
    if encoding == 'gzip': body = gzip.compress(body)
    if encoding == 'deflate': body = zlib.compress(body)
    monkeypatch.setattr(page, 'MAX_RESPONSE_BYTES', 8)
    r = response(body, encoding)
    result = page._observe_response(r.geturl(), r)
    assert (result.text == 'xxxxxxxx') if size == 8 else (result.text is None and 'size limit' in result.error)


def test_truncated_compression_cannot_be_evidence():
    r = response(gzip.compress(b'API reference')[:-4], 'gzip')
    result = page._observe_response(r.geturl(), r)
    assert result.text is None and result.error


@pytest.mark.parametrize('ip', ['100.64.0.1', '198.18.0.1', '240.0.0.1', '::', '::1', 'fc00::1', 'fe80::1', 'ff02::1', '2001:db8::1', '::ffff:10.1.2.3'])
def test_nonpublic_addresses(monkeypatch, ip):
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))])
    with pytest.raises(safety.UnsafeURL): safety.public_addresses('https://docs.widget.test/')


@pytest.mark.parametrize('url', ['https://user:password@widget.test/', 'https://widget.test:22/', 'https://[fe80::1%25en0]/', 'https://widget.test/\nsecret'])
def test_unsafe_urls_rejected_before_dns(monkeypatch, url):
    lookup = MagicMock()
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lookup)
    with pytest.raises(safety.UnsafeURL): safety.public_addresses(url)
    lookup.assert_not_called()


def handlers(monkeypatch):
    values = []
    opener = MagicMock()
    monkeypatch.setattr(page, 'build_opener', lambda *args: values.extend(args) or opener)
    page.urlopen('https://docs.widget.test/')
    return values, opener


def test_tls_preserves_hostname_and_verification(monkeypatch):
    values, opener = handlers(monkeypatch)
    handler = next(h for h in values if isinstance(h, HTTPSHandler))
    captured = []
    monkeypatch.setattr(handler, 'do_open', lambda cls, *a, **kw: captured.append(cls))
    handler.https_open(Request('https://docs.widget.test/'))
    conn = captured[0]('docs.widget.test', timeout=15)
    assert conn._context.check_hostname
    assert conn._context.verify_mode == ssl.CERT_REQUIRED
    sock = MagicMock()
    conn._create_connection = lambda *a, **k: sock
    wrap = MagicMock(return_value=sock)
    monkeypatch.setattr(conn._context, 'wrap_socket', wrap)
    conn.connect()
    wrap.assert_called_once_with(sock, server_hostname='docs.widget.test')
    conn.putrequest('GET', '/')
    assert b'Host: docs.widget.test' in conn._buffer
    req = opener.open.call_args.args[0]
    assert req.get_header('User-agent').startswith('Legible/')
    assert 'text/plain' in req.get_header('Accept')


def test_redirect_discards_sensitive_headers_and_validates(monkeypatch):
    values, _ = handlers(monkeypatch)
    validate = MagicMock()
    monkeypatch.setattr(page, 'public_addresses', validate)
    redirect = next(h for h in values if isinstance(h, HTTPRedirectHandler))
    req = Request('https://docs.widget.test/', headers={'Authorization': 'secret', 'Cookie': 'secret', 'X-Api-Key': 'secret'})
    target = redirect.redirect_request(req, None, 302, 'Found', {}, 'https://other.widget.test/')
    validate.assert_called_once()
    assert not any(k.lower() in {'authorization', 'cookie', 'x-api-key'} for k in target.headers)


def test_genuine_403_is_preserved_without_retry(monkeypatch):
    from urllib.error import HTTPError
    r = response(b'Access refused')
    err = HTTPError(r.geturl(), 403, 'Forbidden', r.headers, r)
    fetch = MagicMock(side_effect=err)
    monkeypatch.setattr(page, 'urlopen', fetch)
    result = page.fetch_page(r.geturl())
    assert result.status == 403 and result.text == 'Access refused'
    assert fetch.call_count == 1


def test_redirect_loops_and_total_limit(monkeypatch):
    values, _ = handlers(monkeypatch)
    monkeypatch.setattr(page, 'public_addresses', lambda *a: [])
    redirect = next(h for h in values if isinstance(h, HTTPRedirectHandler))
    req = Request('https://docs.widget.test/')
    with pytest.raises(safety.UnsafeURL, match='loop'):
        redirect.redirect_request(req, None, 302, '', {}, req.full_url)
    for index in range(page.MAX_REDIRECTS):
        req = redirect.redirect_request(req, None, 302, '', {}, f'https://host{index}.widget.test/')
    with pytest.raises(safety.UnsafeURL, match='limit'):
        redirect.redirect_request(req, None, 302, '', {}, 'https://overflow.widget.test/')


def test_redirect_body_is_closed_without_reading(monkeypatch):
    values, _ = handlers(monkeypatch)
    monkeypatch.setattr(page, 'public_addresses', lambda *a: [])
    redirect = next(h for h in values if isinstance(h, HTTPRedirectHandler))
    redirect.parent = MagicMock()
    body = MagicMock()
    redirect.http_error_302(Request('https://docs.widget.test/'), body, 302, '', {'Location': '/next'})
    body.read.assert_not_called()
    body.close.assert_called_once()
    assert 0 < redirect.parent.open.call_args.kwargs['timeout'] <= page.TIMEOUT


def test_http_response_ignores_false_small_content_length(monkeypatch):
    from http.client import HTTPResponse
    wire = b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nConnection: close\r\n\r\n' + b'x' * 9
    sock = MagicMock()
    sock.makefile.return_value = io.BytesIO(wire)
    r = HTTPResponse(sock)
    r.begin()
    r.geturl = lambda: 'https://docs.widget.test/'
    monkeypatch.setattr(page, 'MAX_RESPONSE_BYTES', 8)
    result = page._observe_response(r.geturl(), r)
    assert result.text is None and 'size limit' in result.error


def test_deadline_is_not_reset_for_redirects(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(page.time, 'monotonic', lambda: now[0])
    values, _ = handlers(monkeypatch)
    monkeypatch.setattr(page, 'public_addresses', lambda *a: [])
    redirect = next(h for h in values if isinstance(h, HTTPRedirectHandler))
    redirect.parent = MagicMock()
    now[0] += page.TIMEOUT + 1
    with pytest.raises(TimeoutError):
        redirect.http_error_302(Request('https://docs.widget.test/'), MagicMock(), 302, '', {'Location': '/next'})
    redirect.parent.open.assert_not_called()


def test_deceptive_related_host():
    assert not safety.related_host('widget.test.evil.invalid', 'www.widget.test')
    assert safety.related_host('platform.widget.test', 'www.widget.test')


@pytest.mark.parametrize('length', ['1', '100', 'invalid'])
def test_false_or_truncated_length_not_positive(length):
    r = response(b'Public documentation', length=length)
    result = page._observe_response(r.geturl(), r)
    assert result.text is None and result.error


def test_conflicting_lengths_not_positive():
    r = response(b'Public documentation', length='20')
    r.headers['Content-Length'] = '1'
    assert page._observe_response(r.geturl(), r).text is None


def test_error_body_has_same_stream_limit(monkeypatch):
    from http.client import HTTPResponse
    from urllib.error import HTTPError
    sock = MagicMock()
    sock.makefile.return_value = io.BytesIO(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 1\r\n\r\n' + b'x'*9)
    r = HTTPResponse(sock); r.begin()
    err = HTTPError('https://docs.widget.test/', 403, 'Forbidden', r.headers, r)
    monkeypatch.setattr(page, 'MAX_RESPONSE_BYTES', 8)
    result = page._observe_response(err.geturl(), err, 'HTTP error: 403')
    assert result.status == 403 and result.text is None and 'size limit' in result.error


def test_url_evidence_redacts_credentials_and_query():
    assert safety.evidence_url('https://user:secret@widget.test/docs?token=secret#secret') == 'https://widget.test/docs?redacted'


@pytest.mark.parametrize('ip', ['192.0.0.8', '192.88.99.1', '64:ff9b::a00:1', '2002:a00:1::', '3fff::1'])
def test_special_allocations_conservatively_rejected(monkeypatch, ip):
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))])
    with pytest.raises(safety.UnsafeURL): safety.public_addresses('https://docs.widget.test/')


def test_public_markdown_through_pinned_https_transport(monkeypatch):
    from types import SimpleNamespace
    sock = MagicMock()
    class Wire(io.BytesIO):
        raw = SimpleNamespace(_sock=sock)
    body = b'# API contract\nPublic documentation.'
    sock.makefile.return_value = Wire(b'HTTP/1.1 200 OK\r\nContent-Type: text/markdown\r\nContent-Length: '
        + str(len(body)).encode() + b'\r\n\r\n' + body)
    monkeypatch.setattr(page.socket, 'socket', lambda *a: sock)
    lookups = []
    def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    monkeypatch.setattr(safety.socket, 'getaddrinfo', resolve)
    def tls(context, connection, *, server_hostname, **kwargs):
        assert server_hostname == 'docs.widget.test'
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        return connection
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', tls)
    result = page.fetch_page('https://docs.widget.test/llms.txt')
    assert result.status == 200 and result.text == body.decode() and result.error is None
    assert lookups == ['docs.widget.test']
    sock.connect.assert_called_once_with(('93.184.216.34', 443))
    request = b''.join(call.args[0] for call in sock.sendall.call_args_list)
    assert b'GET /llms.txt HTTP/1.1' in request
    assert b'Host: docs.widget.test\r\n' in request
    assert b'User-Agent: Legible/' in request


def test_safe_redirect_rebind_is_rejected_before_second_socket(monkeypatch):
    from types import SimpleNamespace
    sock = MagicMock()
    class Wire(io.BytesIO):
        raw = SimpleNamespace(_sock=sock)
    sock.makefile.return_value = Wire(b'HTTP/1.1 302 Found\r\nLocation: https://next.widget.test/docs\r\n\r\n')
    sockets = MagicMock(return_value=sock)
    monkeypatch.setattr(page.socket, 'socket', sockets)
    next_answers = iter(['93.184.216.34', '127.0.0.1'])
    def resolve(host, port, **kwargs):
        ip = next(next_answers) if host == 'next.widget.test' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]
    monkeypatch.setattr(safety.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', lambda self, connection, **kwargs: connection)
    result = page.fetch_page('https://docs.widget.test/')
    assert result.status is None and 'public addresses' in result.error
    assert sockets.call_count == 1
    assert result.metadata.redirects[0].target_url == 'https://next.widget.test/docs'
    assert result.metadata.redirects[0].status == 302
