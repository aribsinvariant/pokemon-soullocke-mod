"""LAN discovery and ownership-aware UPnP forwarding. Calls run off the UI thread."""
import ipaddress
import secrets
import socket
import urllib.request


def is_public_ipv4(value):
    try:
        address = ipaddress.ip_address(value)
        return isinstance(value, str) and address.version == 4 and address.is_global
    except (ValueError, TypeError):
        return False


def public_ipv4(opener=None):
    """Discover the public address independently of router configuration."""
    opener = opener or urllib.request.urlopen
    for url in ('https://api.ipify.org', 'https://checkip.amazonaws.com'):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'EmeraldSoulLink/1'})
            with opener(request, timeout=3) as response:
                address = response.read(65).decode('ascii').strip()
            if is_public_ipv4(address):
                return address
        except (OSError, ValueError, UnicodeError):
            continue
    return None


def lan_address():
    # UDP connect chooses the local route; it sends no packet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 9))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


class PortMapping:
    def __init__(self, factory=None):
        self.factory = factory
        self.device = None
        self.port = None
        self.client = None
        self.description = 'EmeraldSoulLink-' + secrets.token_hex(8)
        self.lease = 3600

    def _owned(self, entry):
        return (entry and entry[0] == self.client and int(entry[1]) == self.port
                and len(entry) > 2 and entry[2] == self.description)

    def open(self, port):
        external = None
        if self.factory is None:
            try:
                import miniupnpc
            except ImportError:
                return dict(ok=False, message='UPnP support is not installed. Use manual port forwarding.')
            self.factory = miniupnpc.UPnP
        try:
            device = self.factory()
            device.discoverdelay = 1500
            if not device.discover():
                return dict(ok=False, message='No UPnP router found. UPnP may be disabled; use manual forwarding.')
            device.selectigd()
            self.client = device.lanaddr
            external = device.externalipaddress()
            if not ipaddress.ip_address(external).is_global:
                return dict(ok=False, message='The router has a private or CGNAT WAN address. '
                            'An upstream router or your ISP must also allow inbound connections.', address=external)
            existing = device.getspecificportmapping(port, 'TCP')
            if existing:
                return dict(ok=False, address=external, message='That external port already has a router mapping. '
                            'It was left untouched. Choose another port or configure forwarding manually.')
            self.device, self.port = device, port
            try:
                mapped = device.addportmapping(port, 'TCP', self.client, port, self.description, '', self.lease)
            except Exception as exc:
                if '725' not in str(exc) and 'OnlyPermanentLeases' not in str(exc):
                    raise
                self.lease = 0
                mapped = device.addportmapping(port, 'TCP', self.client, port, self.description, '', 0)
            if not mapped:
                raise RuntimeError('Router declined the mapping')
            return dict(ok=True, address=external, lan=self.client,
                        message='Port configured by UPnP. Internet reachability is confirmed when your partner connects.')
        except Exception:
            return dict(ok=False, address=external,
                        message='UPnP could not configure this router. Use the manual forwarding details.')

    def renew(self):
        if self.device and self.port and self._owned(
                self.device.getspecificportmapping(self.port, 'TCP')):
            if not self.lease:
                return True
            return self.device.addportmapping(self.port, 'TCP', self.client, self.port,
                                             self.description, '', self.lease)
        return False

    def close(self):
        if self.device and self.port:
            try:
                if self._owned(self.device.getspecificportmapping(self.port, 'TCP')):
                    self.device.deleteportmapping(self.port, 'TCP')
            finally:
                self.device, self.port = None, None
