import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .catalog import UserError


class Storage:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('FRIDGE_DB', 'runtime/fridge.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS inventory (
                    name TEXT PRIMARY KEY, qty INTEGER NOT NULL CHECK(qty >= 0)
                );
                CREATE TABLE IF NOT EXISTS revision (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL);
                INSERT OR IGNORE INTO revision VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS meals (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, required TEXT NOT NULL, confirmed TEXT
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def read(db):
        version = db.execute('SELECT version FROM revision WHERE id=1').fetchone()[0]
        return version, dict(db.execute('SELECT name, qty FROM inventory ORDER BY name'))

    def snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN')
            return self.read(db)

    def set_item(self, name, quantity):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, current = self.read(db)
            if current.get(name, 0) == quantity:
                return
            if quantity == 0:
                db.execute('DELETE FROM inventory WHERE name=?', (name,))
            else:
                db.execute('INSERT INTO inventory VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET qty=excluded.qty',
                           (name, quantity))
            db.execute('UPDATE revision SET version=version+1 WHERE id=1')

    def save_meal(self, version, required):
        meal_id = uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO meals VALUES (?, ?, ?, NULL)', (meal_id, version, json.dumps(required)))
        return meal_id

    def confirm(self, meal_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute('SELECT version, required, confirmed FROM meals WHERE id=?', (meal_id,)).fetchone()
            if record is None:
                raise UserError('查無可確認的菜單，請重新規劃。')
            meal_version, required_json, confirmed = record
            if confirmed is not None:
                return {'status': 'already_confirmed', 'deducted': json.loads(confirmed)}
            version, inventory = self.read(db)
            if version != meal_version:
                raise UserError('規劃後庫存已變更。請重新規劃，再確認扣除。')
            required = json.loads(required_json)
            if any(inventory.get(name, 0) < qty for name, qty in required.items()):
                raise UserError('庫存不足，沒有扣除任何食材。')
            for name, qty in required.items():
                db.execute('UPDATE inventory SET qty=qty-? WHERE name=?', (qty, name))
            db.execute('DELETE FROM inventory WHERE qty=0')
            db.execute('UPDATE revision SET version=version+1 WHERE id=1')
            db.execute('UPDATE meals SET confirmed=? WHERE id=?', (required_json, meal_id))
            return {'status': 'confirmed', 'deducted': required}
