"""Transactional room state. No emulator memory or game state is trusted as SQL."""
import json
import secrets
import sqlite3
from enum import IntFlag

PROTOCOL = 1
BUILD = 0x534C0001
AREAS = 512
AVAILABLE, PENDING, LINKED, DEAD, FORFEITED = range(5)


class Rules(IntFlag):
    DUPES = 1
    SHINY = 2
    GENDER = 4
    PAIR_TYPE = 8
    TEAM_TYPE = 16
    PAIRED_PARTY = 32
    WIPE = 64
    SEPARATE_GIFTS = 128
    RANDOM_WILD = 256
    RANDOM_STARTERS = 512
    SIMILAR = 1024
    NO_LEGENDS = 2048
    NO_BATTLE_ITEMS = 4096
    FORCE_SET = 8192


DEFAULT_RULES = int(Rules.DUPES | Rules.PAIRED_PARTY | Rules.WIPE)


# Starting options share the existing 32-bit configuration word.
START_OPTIONS = 1 << 23
DEFAULT_START_OPTIONS = START_OPTIONS | (2 << 14) | (1 << 16) | (1 << 17)


class ProtocolError(ValueError):
    pass


def integer(value, low=0, high=0xFFFFFFFF):
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise ProtocolError('invalid integer') from exc
    if not low <= number <= high:
        raise ProtocolError('integer outside range')
    return number


def validate_rules(value):
    value = integer(value, 0, 0xFFFFFF)
    if ((value >> 14) & 3) > 2 or ((value >> 18) & 31) > 19:
        raise ProtocolError("invalid starting game options")
    if not value & START_OPTIONS and value >> 14:
        raise ProtocolError("starting options require the presence flag")
    return value


def name_bytes(value, length):
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ProtocolError('invalid name encoding') from exc
    if len(data) != length:
        raise ProtocolError('invalid name length')
    return value


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
            room TEXT, player INTEGER, seq INTEGER, payload TEXT NOT NULL,
            PRIMARY KEY(room, player, seq));
        ''')

    def create(self, room, seed=1, rules=DEFAULT_RULES, rom_sha256=None):
        if not room.isalnum() or not 1 <= len(room) <= 32:
            raise ProtocolError('room must be 1-32 letters or digits')
        state = dict(run=secrets.randbelow(0x7FFFFFFE) + 1, seed=integer(seed),
                     rules=validate_rules(rules), version=0, locked=False, ended=False,
                     tokens=[secrets.token_hex(16), secrets.token_hex(16)],
                     confirmed=[False, False], notice=[0, 0], seq=[0, 0], trainers=['ff'*8]*2,
                     mons=[{}, {}], reservations=[{}, {}], failures=[], party=[[], []], proposed=[None, None])
        if rom_sha256 is not None:
            if len(rom_sha256) != 64 or any(c not in '0123456789abcdef' for c in rom_sha256):
                raise ProtocolError('invalid ROM hash')
            state['rom_sha256'] = rom_sha256
        try:
            with self.db:
                self.db.execute('INSERT INTO rooms VALUES (?,?)', (room, json.dumps(state)))
        except sqlite3.IntegrityError as exc:
            raise ProtocolError(
                f'Room {room!r} already exists. Start the relay without --create to resume; '
                f'use --restart {room} only after the run has ended. '
                'Keep the existing database and player scripts.') from exc
        return state

    def configure(self, room, seed, rules):
        """Host launcher settings share the same lock and version as game settings."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state = self.get(room)
            if state['locked']:
                raise ProtocolError('settings are locked for this run')
            state['seed'], state['rules'] = integer(seed), validate_rules(rules)
            state['confirmed'] = [False, False]
            state['version'] += 1
            self.save(room, state)
        return state

    def restart(self, room, seed=None):
        """Start another attempt without replacing room credentials."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.get(room)
            if not previous['ended']:
                raise ProtocolError('only a finished run can be restarted')
            state = dict(previous)
            state.update(run=previous['run'] % 0x7FFFFFFF + 1,
                         seed=previous['seed'] if seed is None else integer(seed),
                         version=0, locked=False, ended=False,
                         confirmed=[False, False], notice=[0, 0], seq=[0, 0],
                         trainers=['ff'*8]*2, mons=[{}, {}], reservations=[{}, {}],
                         failures=[], party=[[], []], proposed=[None, None])
            self.db.execute('DELETE FROM events WHERE room=?', (room,))
            self.save(room, state)
        return state

    def get(self, room):
        row = self.db.execute('SELECT state FROM rooms WHERE id=?', (room,)).fetchone()
        if row is None:
            raise ProtocolError('unknown room')
        return json.loads(row[0])

    def save(self, room, state):
        self.db.execute('UPDATE rooms SET state=? WHERE id=?', (json.dumps(state), room))

    def authenticate(self, room, player, token):
        state = self.get(room)
        if not secrets.compare_digest(state['tokens'][player], token):
            raise ProtocolError('invalid credential')
        return state

    def event(self, room, player, seq, kind, args, expected_run=None):
        seq = integer(seq, 1)
        payload = json.dumps([kind, args], separators=(',', ':'))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state = self.get(room)
            if expected_run is not None and state['run'] != expected_run:
                raise ProtocolError('run restarted; reset mGBA and select New Game')
            existing = self.db.execute('SELECT payload FROM events WHERE room=? AND player=? AND seq=?',
                                       (room, player, seq)).fetchone()
            if existing:
                if existing[0] != payload:
                    raise ProtocolError('save rollback: event identity reused')
                return state
            if seq != state['seq'][player] + 1:
                raise ProtocolError('event sequence gap or unsupported rollback')
            self.apply(state, player, kind, args)
            state['seq'][player] = seq
            state['version'] += 1
            self.db.execute('INSERT INTO events VALUES (?,?,?,?)', (room, player, seq, payload))
            self.save(room, state)
            return state

    @staticmethod
    def apply(s, p, kind, args):
        q = 1-p
        if kind == 'settings':
            if s['locked'] or p != 0 or len(args) != 2:
                raise ProtocolError('settings locked or not host')
            s['rules'], s['seed'] = validate_rules(args[0]), integer(args[1])
            s['confirmed'] = [False, False]
            return
        if kind == 'confirm':
            if len(args) != 2 or [integer(x) for x in args] != [s['rules'], s['seed']]:
                raise ProtocolError('confirm settings mismatch')
            s['confirmed'][p] = True
            s['locked'] = all(s['confirmed'])
            return
        if not s['locked']:
            raise ProtocolError('both players must confirm settings')
        if kind in ('reserve', 'catch'):
            if len(args) != 6:
                raise ProtocolError('invalid catch')
            area = str(integer(args[0], 0, AREAS-1))
            mon = dict(species=integer(args[1], 1, 411), type=integer(args[2], 0, 17),
                       gender=integer(args[3], 0, 255), name=name_bytes(args[4], 11),
                       dead=False, active=bool(integer(args[5], 0, 1)))
            if kind == 'reserve':
                s['reservations'][p].pop(area, None)
                other = s['mons'][q].get(area) or s['reservations'][q].get(area)
                if area not in s['mons'][p] and int(area) not in s['failures'] and (not other or Store.compatible(s['rules'], mon, other)):
                    s['reservations'][p][area] = mon
                return
            if area in s['mons'][p]:
                raise ProtocolError('area already caught')
            other = s['mons'][q].get(area) or s['reservations'][q].get(area)
            if other and int(area) != 511 and not Store.compatible(s['rules'], mon, other):
                # The second incompatible reservation loses; the ROM leaves it unusable.
                mon['dead'] = True
                s['failures'] = sorted(set(s['failures'] + [int(area)]))
            s['mons'][p][area] = mon
            s['reservations'][p].pop(area, None)
            if area in s['mons'][q] and not mon['dead'] and int(area) not in s['failures']:
                if mon['active'] and other['active']:
                    proposed = sorted(set(s['party'][p] + [int(area)]))
                    if Store.valid_party(s, proposed):
                        s['party'] = [proposed[:], proposed[:]]
            return
        if kind == 'finish':
            if len(args) != 1:
                raise ProtocolError('invalid encounter finish')
            area = integer(args[0], 0, AREAS-1)
            if str(area) in s['reservations'][p] and str(area) not in s['mons'][p]:
                s['failures'] = sorted(set(s['failures'] + [area]))
            s['reservations'][p].pop(str(area), None)
            return
        if kind == 'release':
            if len(args) != 1:
                raise ProtocolError('invalid release')
            s['reservations'][p].pop(str(integer(args[0], 0, AREAS-1)), None)
            return
        if kind in ('death', 'fail'):
            if len(args) != 1:
                raise ProtocolError('invalid outcome')
            area = integer(args[0], 0, AREAS-1)
            s['reservations'][p].pop(str(area), None)
            if kind == 'fail':
                s['failures'] = sorted(set(s['failures'] + [area]))
            else:
                if str(area) not in s['mons'][p]:
                    raise ProtocolError('unknown dead Pokemon')
                for mons in s['mons']:
                    if str(area) in mons:
                        mons[str(area)]['dead'] = True
            return
        if kind == 'wipe':
            if args:
                raise ProtocolError('invalid wipe')
            if s['rules'] & Rules.WIPE:
                s['ended'] = True
            return
        if kind == 'party':
            party = sorted(integer(a, 0, AREAS-1) for a in args)
            if len(party) > 6 or len(set(party)) != len(party) or not Store.valid_party(s, party):
                s['notice'][p] = 1
                return
            s['notice'][p] = 0
            s['proposed'][p] = party
            if not s['rules'] & Rules.PAIRED_PARTY:
                s['party'][p] = party
            elif s['proposed'][q] == party:
                s['party'] = [party[:], party[:]]
                s['proposed'] = [None, None]
            return
        if kind == 'rename':
            if len(args) != 4:
                raise ProtocolError('invalid Pokemon update')
            area = str(integer(args[0], 0, AREAS-1))
            if area not in s['mons'][p]:
                raise ProtocolError('unknown Pokemon')
            s['mons'][p][area].update(name=name_bytes(args[1], 11), species=integer(args[2], 1, 411), type=integer(args[3], 0, 17))
            if not Store.valid_party(s, s['party'][p]):
                for party in s['party']:
                    if int(area) in party: party.remove(int(area))
            return
        raise ProtocolError('unknown event')

    @staticmethod
    def compatible(rules, a, b):
        return not ((rules & Rules.GENDER and a['gender'] != 255 and b['gender'] != 255 and a['gender'] == b['gender'])
                    or (rules & Rules.PAIR_TYPE and a['type'] == b['type']))

    @staticmethod
    def status(s, area):
        if area in s['failures']:
            return FORFEITED
        mons = [m.get(str(area)) for m in s['mons']]
        if s['ended'] or any(m and m['dead'] for m in mons):
            return DEAD
        return LINKED if all(mons) else PENDING if any(mons) else AVAILABLE

    @staticmethod
    def valid_party(s, party):
        if not party:
            return False
        if any(Store.status(s, a) != LINKED for a in party):
            return False
        if s['rules'] & Rules.TEAM_TYPE:
            types = []
            for a in party:
                pair_types = [s['mons'][p][str(a)]['type'] for p in range(2)]
                if a == 511: pair_types = list(set(pair_types))
                types.extend(pair_types)
            return len(set(types)) == len(types)
        return True
