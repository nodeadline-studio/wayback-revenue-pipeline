import os
import sqlite3
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_KEY") # Required for backend writes
        self.local_db = 'saas.sqlite'
        
        self.use_supabase = all([self.url, self.key, create_client is not None])
        
        if self.use_supabase:
            logger.info(f"Database: Using Supabase Cloud (URL: {self.url})")
            self.supabase: Client = create_client(self.url, self.key)
        else:
            logger.info("Database: Using SQLite (Local)")
            if create_client is None:
                logger.warning("Supabase library not installed. Defaulting to SQLite.")
            self.init_sqlite()

    def init_sqlite(self):
        with sqlite3.connect(self.local_db) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_paid BOOLEAN DEFAULT 0
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                paypal_order_id TEXT UNIQUE NOT NULL,
                capture_id TEXT,
                email TEXT NOT NULL,
                package TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'created',
                target_url TEXT,
                report_file TEXT,
                public_report_file TEXT,
                created_at TEXT NOT NULL,
                captured_at TEXT
            )''')

    def execute(self, query, params=(), commit=True):
        """
        Note: This is a legacy method for local SQLite. 
        Supabase uses a fluent interface, so specific methods are preferred.
        """
        if self.use_supabase:
            logger.warning("direct execute() called in Supabase mode - this might not be fully supported for complex queries.")
        
        with sqlite3.connect(self.local_db) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, params)
            if commit:
                conn.commit()
            if query.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cur.fetchall()]
            return cur.rowcount

    def fetch_one(self, query, params=()):
        results = self.execute(query, params, commit=False)
        return results[0] if results else None

    # --- HIGH LEVEL ABSTRACTIONS (Used in app.py) ---

    def get_user(self, email: str) -> Optional[Dict]:
        if self.use_supabase:
            res = self.supabase.table('users').select('*').eq('email', email).execute()
            return res.data[0] if res.data else None
        else:
            return self.fetch_one('SELECT * FROM users WHERE email = ?', (email,))

    def update_user_paid_status(self, email: str, is_paid: bool = True):
        if self.use_supabase:
            self.supabase.table('users').update({'is_paid': is_paid}).eq('email', email).execute()
        else:
            val = 1 if is_paid else 0
            self.execute('UPDATE users SET is_paid = ? WHERE email = ?', (val, email))

    def create_user(self, email: str, password: str, is_paid: bool = False):
        user_id = str(uuid.uuid4())
        if self.use_supabase:
            self.supabase.table('users').insert({
                'id': user_id,
                'email': email,
                'password': password,
                'is_paid': is_paid
            }).execute()
        else:
            self.execute('INSERT INTO users (id, email, password, is_paid) VALUES (?, ?, ?, ?)', 
                         (user_id, email, password, 1 if is_paid else 0))

    def create_order(self, paypal_id, email, package, amount, created_at, target_url=None):
        order_id = str(uuid.uuid4())
        if self.use_supabase:
            self.supabase.table('orders').insert({
                'id': order_id,
                'paypal_order_id': paypal_id,
                'email': email,
                'package': package,
                'amount': amount,
                'status': 'created',
                'target_url': target_url,
                'created_at': created_at
            }).execute()
        else:
            self.execute('''INSERT INTO orders 
                (id, paypal_order_id, email, package, amount, status, created_at, target_url) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                (order_id, paypal_id, email, package, amount, 'created', created_at, target_url))

    def capture_order(self, paypal_id, status='captured', capture_id=None, captured_at=None):
        if self.use_supabase:
            data = {'status': status}
            if capture_id: data['capture_id'] = capture_id
            if captured_at: data['captured_at'] = captured_at
            self.supabase.table('orders').update(data).eq('paypal_order_id', paypal_id).execute()
        else:
            self.execute('UPDATE orders SET status = ?, capture_id = ?, captured_at = ? WHERE paypal_order_id = ?', 
                         (status, capture_id or '', captured_at, paypal_id))

    def update_order_report(self, paypal_id, report_file, public_report_file=None):
        if self.use_supabase:
            data = {'report_file': report_file}
            if public_report_file:
                data['public_report_file'] = public_report_file
            self.supabase.table('orders').update(data).eq('paypal_order_id', paypal_id).execute()
        else:
            if public_report_file:
                self.execute('UPDATE orders SET report_file = ?, public_report_file = ? WHERE paypal_order_id = ?', 
                             (report_file, public_report_file, paypal_id))
            else:
                self.execute('UPDATE orders SET report_file = ? WHERE paypal_order_id = ?', (report_file, paypal_id))

    def get_user_reports(self, email: str) -> List[Dict]:
        if self.use_supabase:
            res = self.supabase.table('orders').select('*').eq('email', email).order('created_at', desc=True).execute()
            return res.data
        else:
            return self.execute('SELECT * FROM orders WHERE email = ? ORDER BY created_at DESC', (email,), commit=False)
