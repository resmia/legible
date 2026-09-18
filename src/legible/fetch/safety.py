"""Public address validation shared by admission and pinned HTTP connections."""
from ipaddress import ip_address, ip_network
import socket
from urllib.parse import urlsplit, urlunsplit


# Conservatively exclude special/transition allocations whose treatment differs
# across supported Python versions, including embedded IPv4 routing mechanisms.
SPECIAL_NETWORKS = tuple(map(ip_network, (
    '192.0.0.0/24', '192.88.99.0/24', '64:ff9b::/96', '64:ff9b:1::/48',
    '2001::/23', '2002::/16', '3fff::/20', '5f00::/16',
)))


class UnsafeURL(ValueError):
    pass


def validated_target(url, local_origin=None):
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeURL('Whitespace or control character in URL')
    parsed = urlsplit(url)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise UnsafeURL('Unsupported URL or embedded credentials')
    host = parsed.hostname
    if '%' in host or '\\' in host:
        raise UnsafeURL('Invalid hostname or scoped address')
    origin = (parsed.scheme, host, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if origin != local_origin and origin[2] not in {80, 443}:
        raise UnsafeURL('Nonstandard public port rejected')
    return parsed, origin


def public_addresses(url, local_origin=None):
    parsed, origin = validated_target(url, local_origin)
    addresses = socket.getaddrinfo(parsed.hostname, origin[2], type=socket.SOCK_STREAM)
    if not addresses:
        raise UnsafeURL('Hostname has no addresses')
    for _, _, _, _, address in addresses:
        if '%' in address[0] or len(address) > 3 and address[3]:
            raise UnsafeURL('Scoped connection address rejected')
        ip = ip_address(address[0])
        ip = getattr(ip, 'ipv4_mapped', None) or ip
        if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified
                or any(ip in network for network in SPECIAL_NETWORKS if ip.version == network.version)) and not (origin == local_origin and ip.is_loopback):
            raise UnsafeURL('Destination does not resolve exclusively to public addresses')
    return addresses


def validate_public_url(url):
    if urlsplit(url).scheme != 'https':
        raise UnsafeURL('New published origins require HTTPS')
    public_addresses(url)


def related_host(host, root):
    # No public-suffix guess: retain the full input host, stripping only www.
    # This is an explicit publisher relationship, not registrable-domain proof.
    root = root.lower().rstrip('.').removeprefix('www.')
    host = host.lower().rstrip('.')
    return host == root or host.endswith('.' + root)


def evidence_url(url):
    """Do not retain URL credentials or query values in public scan observations."""
    if not url:
        return url
    try:
        parsed = urlsplit(url)
        netloc = parsed.netloc.rsplit('@', 1)[-1]
        return urlunsplit((parsed.scheme, netloc, parsed.path,
                           'redacted' if parsed.query else '', ''))
    except ValueError:
        return '[invalid URL]'
