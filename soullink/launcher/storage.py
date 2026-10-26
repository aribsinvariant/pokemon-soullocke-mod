"""Validated package, invitation, and local session data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from dataclasses import dataclass
from soullink.relay.model import PROTOCOL, BUILD, DEFAULT_RULES, integer


RULES = (
    'Duplicate-family rerolls', 'Shiny collectibles', 'Opposite pair genders',
    'Different pair types', 'Unique team types', 'Paired parties', 'Wipe ends both runs',
    'Separate gift encounters', 'Randomize wild Pokémon', 'Randomize starters',
    'Similar-strength randomization', 'Exclude legendaries and mythicals',
    'No bag items in battle (except Poké Balls)', 'Force Set battle style',
)


QOL_RULES = ('Teleport to visited places', 'Heal party from menu',
             'Adjust party levels', 'Learn level-up moves', 'Menu Pokémon PC')
RULE_BITS = tuple(range(14)) + tuple(range(24, 29))
RULES += QOL_RULES

def app_directory():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'EmeraldSoulLink'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'EmeraldSoulLink'


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def load_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def validate_host(value):
    value = value.strip()
    if not value or len(value) > 253 or any(c.isspace() for c in value) or any(c in value for c in '/\\?#@'):
        raise ValueError('Enter an IP address or hostname, without http:// or a port.')
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('Use an ASCII IP address or hostname.')
    return value


def validate_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid game build hash')
    return value


@dataclass(frozen=True)
class GamePackage:
    directory: Path
    rom: Path
    sha256: str
    mailbox: int

    @classmethod
    def load(cls, directory):
        directory = Path(directory).resolve()
        manifest = load_json(directory / 'manifest.json')
        if not isinstance(manifest, dict):
            raise ValueError('Select the built dist folder containing manifest.json and emerald-soullink.gba.')
        if manifest.get('protocol') != PROTOCOL or manifest.get('build') != f'{BUILD:08x}':
            raise ValueError('This game package uses an unsupported protocol or build.')
        address = int(manifest['mailbox'], 16)
        if not 0x02000000 <= address < 0x02040000:
            raise ValueError('Invalid game mailbox address')
        expected = validate_hash(manifest.get('sha256'))
        rom = directory / 'emerald-soullink.gba'
        if not rom.is_file() or hashlib.sha256(rom.read_bytes()).hexdigest() != expected:
            raise ValueError('The ROM does not match manifest.json. Package the matching build again.')
        return cls(directory, rom, expected, address)


@dataclass(frozen=True)
class Invite:
    host: str
    port: int
    room: str
    token: str
    sha256: str

    def __post_init__(self):
        object.__setattr__(self, 'host', validate_host(self.host))
        integer(self.port, 1, 65535)
        if not isinstance(self.room, str) or not re.fullmatch('[A-Za-z0-9]{1,32}', self.room):
            raise ValueError('Invalid invite room')
        if not isinstance(self.token, str) or not re.fullmatch('[0-9a-f]{32}', self.token):
            raise ValueError('Invalid invite credential')
        validate_hash(self.sha256)

    def encode(self):
        data = dict(version=1, protocol=PROTOCOL, build=BUILD, player=1,
                    host=self.host, port=self.port, room=self.room, token=self.token, sha256=self.sha256)
        encoded = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
        return 'soullink://join?data=' + encoded

    @classmethod
    def decode(cls, text):
        try:
            prefix = 'soullink://join?data='
            text = text.strip()
            if len(text) > 2048 or not text.startswith(prefix):
                raise ValueError()
            encoded = text[len(prefix):]
            if not re.fullmatch('[A-Za-z0-9_-]+', encoded):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            if (data['version'], data['protocol'], data['build'], data['player']) != (1, PROTOCOL, BUILD, 1):
                raise ValueError()
            return cls(**{key: data[key] for key in ('host', 'port', 'room', 'token', 'sha256')})
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('Invalid or incompatible invite. Paste the complete invite from the host.') from exc


class Profiles:
    def __init__(self, root=None):
        self.root = Path(root) if root else app_directory()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = load_json(self.root / 'settings.json', {})

    def remember(self, **values):
        self.settings.update(values)
        save_json(self.root / 'settings.json', self.settings)

    def list(self):
        return [load_json(path) for path in sorted((self.root / 'sessions').glob('*/profile.json'))]

    def directory(self, profile):
        identifier = profile['id']
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise ValueError('Invalid local profile identifier')
        return self.root / 'sessions' / identifier

    def save(self, profile):
        save_json(self.directory(profile) / 'profile.json', profile)
        return profile

    def create(self, **values):
        return self.save(dict(id=secrets.token_hex(16), **values))
