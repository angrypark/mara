"""Append-only evidence store. Local OS administrator is trusted; tenants are not."""
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .domain import dumps, day

SHARED = '__market__'


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=15)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.in_transaction = False
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
          owner TEXT NOT NULL, kind TEXT NOT NULL, effective TEXT NOT NULL,
          recorded TEXT NOT NULL, run_id TEXT, body TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_lookup ON events(owner,kind,effective,seq);
        CREATE INDEX IF NOT EXISTS events_run ON events(owner,run_id,kind,seq);
        CREATE TABLE IF NOT EXISTS locks(owner TEXT PRIMARY KEY, run_id TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT,'immutable event'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT,'immutable event'); END;
        ''')
        self.db.commit()

    def create_user(self, user):
        if not user or user == SHARED: raise ValueError('Invalid user')
        token = secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO users VALUES (?,?)', (user, self.token_hash(token)))
        self.db.commit()
        return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token):
        row = self.db.execute('SELECT id FROM users WHERE token_hash=?', (self.token_hash(token),)).fetchone()
        if row is None: raise PermissionError('Invalid tenant token')
        return Session(self, row['id'])

    def _append(self, owner, kind, body, effective, run_id=None):
        day(effective)
        payload = dumps(body)
        eid = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute('INSERT INTO events(id,owner,kind,effective,recorded,run_id,body,digest) VALUES(?,?,?,?,?,?,?,?)',
                        (eid, owner, kind, effective, now, run_id, payload, hashlib.sha256(payload.encode()).hexdigest()))
        if not self.in_transaction: self.db.commit()
        return eid

    def publish_market(self, body):
        from .domain import market
        market(body)
        return self._append(SHARED, 'market', body, body['as_of'])

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.in_transaction = True
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self.in_transaction = False

    def close(self):
        self.db.close()


class Session:
    def __init__(self, store, owner):
        self.store, self.owner = store, owner

    def append(self, kind, body, effective, run_id=None):
        return self.store._append(self.owner, kind, body, effective, run_id)

    @staticmethod
    def decode(row):
        if row is None: return None
        result = dict(row)
        if hashlib.sha256(result['body'].encode()).hexdigest() != result['digest']: raise ValueError('Corrupt evidence')
        result['body'] = json.loads(result['body'])
        return result

    def get(self, eid):
        row = self.store.db.execute('SELECT * FROM events WHERE id=? AND owner IN (?,?)', (eid, self.owner, SHARED)).fetchone()
        if row is None: raise PermissionError('Evidence unavailable for this tenant')
        return self.decode(row)

    def events(self, kind, as_of='9999-12-31', shared=False):
        owner = SHARED if shared else self.owner
        rows = self.store.db.execute('SELECT * FROM events WHERE owner=? AND kind=? AND effective<=? ORDER BY effective,seq', (owner,kind,as_of)).fetchall()
        return [self.decode(r) for r in rows]

    def latest(self, kind, as_of='9999-12-31', shared=False):
        rows = self.events(kind, as_of, shared)
        return rows[-1] if rows else None

    def lock(self, run_id):
        try:
            self.store.db.execute('INSERT INTO locks VALUES (?,?)', (self.owner,run_id))
            self.store.db.commit()
        except sqlite3.IntegrityError:
            raise RuntimeError('An execution is already running; inspect it before recover')

    def unlock(self, run_id):
        self.store.db.execute('DELETE FROM locks WHERE owner=? AND run_id=?', (self.owner,run_id))
        self.store.db.commit()

    def recover(self, reason, as_of):
        if not reason.strip(): raise ValueError('Recovery reason required')
        lock = self.store.db.execute('SELECT run_id FROM locks WHERE owner=?', (self.owner,)).fetchone()
        if lock:
            self.append('recovery', {'run_id': lock['run_id'], 'reason': reason}, as_of)
            self.unlock(lock['run_id'])

    def export(self):
        rows = self.store.db.execute('SELECT * FROM events WHERE owner=? ORDER BY seq', (self.owner,)).fetchall()
        own = [self.decode(r) for r in rows]
        # Include only shared market records actually referenced by this user's runs.
        mids = {e['body']['market_id'] for e in own if e['kind'] == 'run_started'}
        return {'owner': self.owner, 'events': own, 'market_evidence': [self.get(x) for x in sorted(mids)]}
