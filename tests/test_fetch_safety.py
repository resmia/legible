"""DNS and redirects are validated before opening a public connection."""
import socket
from email.message import Message
from unittest.mock import MagicMock
from urllib.request import HTTPRedirectHandler, Request

import pytest
from legible.fetch import page, safety


def answers(ip, port=443):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.1.2.3', '169.254.169.254', '192.0.2.1', '0.0.0.0', '224.0.0.1'])
def test_private_and_special_addresses_rejected(monkeypatch, ip):
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **kw: answers(ip))
    with pytest.raises(safety.UnsafeURL):
        safety.validate_public_url('https://docs.widget.test/')


def test_mixed_dns_answers_rejected(monkeypatch):
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **kw: answers('93.184.216.34')+answers('127.0.0.1'))
    with pytest.raises(safety.UnsafeURL):
        safety.validate_public_url('https://docs.widget.test/')


def test_redirect_to_private_is_rejected(monkeypatch):
    handlers = []
    opener = MagicMock()
    monkeypatch.setattr(page, 'build_opener', lambda *values: handlers.extend(values) or opener)
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **kw: answers('127.0.0.1'))
    page.urlopen('https://docs.widget.test/')
    redirect = next(h for h in handlers if isinstance(h, HTTPRedirectHandler))
    with pytest.raises(safety.UnsafeURL):
        redirect.redirect_request(Request('https://docs.widget.test/'), None, 302, 'Found', {}, 'https://internal.widget.test/')
    with pytest.raises(safety.UnsafeURL):
        redirect.redirect_request(Request('https://docs.widget.test/'), None, 302, 'Found', {}, 'http://public.widget.test/')


def test_response_size_is_bounded(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = 'https://widget.test/'
    response.status = 200
    response.headers = Message()
    response.read.return_value = b'x' * 9
    monkeypatch.setattr(page, 'MAX_RESPONSE_BYTES', 8)
    monkeypatch.setattr(page, 'urlopen', lambda url: response)
    result = page.fetch_page('https://widget.test/')
    assert result.text is None and 'size limit' in result.error
    response.read.assert_called_once_with(9)


def test_connection_pins_public_resolution(monkeypatch):
    from urllib.request import HTTPSHandler
    handlers = []
    opener = MagicMock()
    monkeypatch.setattr(page, 'build_opener', lambda *items: handlers.extend(items) or opener)
    page.urlopen('https://docs.widget.test/')
    handler = next(h for h in handlers if isinstance(h, HTTPSHandler))
    captured = []
    monkeypatch.setattr(handler, 'do_open', lambda cls, *a, **kw: captured.append(cls))
    handler.https_open(Request('https://docs.widget.test/'))
    conn = captured[0]('docs.widget.test', timeout=page.TIMEOUT)
    sock = MagicMock()
    monkeypatch.setattr(page.socket, 'socket', lambda *a: sock)
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **kw: answers('93.184.216.34'))
    conn._create_connection(('docs.widget.test', 443), page.TIMEOUT)
    sock.connect.assert_called_once_with(('93.184.216.34', 443))
    sock.reset_mock()
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda *a, **kw: answers('127.0.0.1'))
    with pytest.raises(safety.UnsafeURL):
        conn._create_connection(('docs.widget.test', 443), page.TIMEOUT)
    sock.connect.assert_not_called()
