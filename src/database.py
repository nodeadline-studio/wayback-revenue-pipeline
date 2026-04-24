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
        # Support both SERVICE_KEY and the standard SUPABASE_KEY naming from LeadIdeal
        self.key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        self.local_db = 'saas.sqlite'

        self.use_supabase = all([self.url, self.key, create_client is not None])

        self.init_sqlite()
        if self.use_supabase:
            logger.info(f"Database: Using Supabase Cloud (URL: {self.url})")
            self.supabase: Client = create_client(self.url, self.key)
        else:
            logger.info("Database: Using SQLite (Local)")
            if create_client is None:
                logger.warning("Supabase library not installed. Defaulting to SQLite.")

    def init_sqlite(self):
        with sqlite3.connect(self.local_db) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_paid BOOLEAN DEFAULT 0,
                tier TEXT DEFAULT 'free'
            )''')
            # Migrate: add tier column to existing databases
            try:
                conn.execute("ALTER TABLE users ADD COLUMN tier TEXT DEFAULT 'free'")
            except Exception:
                pass  # column already exists
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
            conn.execute('''CREATE TABLE IF NOT EXISTS forensic_jobs (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                target_url TEXT NOT NULL,
                status TEXT DEFAULT 'processing',
                progress INTEGER DEFAULT 0,
                stage_label TEXT,
                report_file TEXT,
                public_report_file TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                referrer TEXT,
                utm_source TEXT,
                utm_medium TEXT,
                utm_campaign TEXT,
                user_agent TEXT,
                job_type TEXT DEFAULT 'demo'
            )''')
            # Migrate: add acquisition columns to existing databases
            for _col, _default in [
                ('referrer', 'NULL'), ('utm_source', 'NULL'), ('utm_medium', 'NULL'),
                ('utm_campaign', 'NULL'), ('user_agent', 'NULL'), ('job_type', "'demo'"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE forensic_jobs ADD COLUMN {_col} TEXT DEFAULT {_default}")
                except Exception:
                    pass  # column already exists

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
            try:
                res = self.supabase.table('users').select('*').eq('email', email).execute()
                return res.data[0] if res.data else None
            except Exception as e:
                logger.warning(f"Supabase get_user failed, falling back to SQLite: {e}")

        return self.fetch_one('SELECT * FROM users WHERE email = ?', (email,))

    def update_user_paid_status(self, email: str, is_paid: bool = True):
        if self.use_supabase:
            try:
                self.supabase.table('users').update({'is_paid': is_paid}).eq('email', email).execute()
                return
            except Exception as e:
                logger.warning(f"Supabase update_user_paid_status failed, falling back to SQLite: {e}")

        val = 1 if is_paid else 0
        self.execute('UPDATE users SET is_paid = ? WHERE email = ?', (val, email))

    def upgrade_user_tier(self, email: str, tier: str = 'unlimited'):
        """Upsert the tier for a user. Creates user record if not present."""
        if self.use_supabase:
            try:
                # Try update first; if no rows, insert
                res = self.supabase.table('users').update({'tier': tier}).eq('email', email).execute()
                if not (res.data):
                    self.supabase.table('users').insert({
                        'id': str(uuid.uuid4()), 'email': email,
                        'password': '', 'is_paid': tier == 'unlimited', 'tier': tier
                    }).execute()
                return
            except Exception as e:
                logger.warning(f"Supabase upgrade_user_tier failed, falling back to SQLite: {e}")
        existing = self.fetch_one('SELECT id FROM users WHERE email = ?', (email,))
        if existing:
            self.execute('UPDATE users SET tier = ? WHERE email = ?', (tier, email))
        else:
            self.execute(
                'INSERT INTO users (id, email, password, is_paid, tier) VALUES (?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), email, '', 1 if tier == 'unlimited' else 0, tier),
            )

    def create_user(self, email: str, password: str, is_paid: bool = False):
        user_id = str(uuid.uuid4())
        if self.use_supabase:
            try:
                self.supabase.table('users').insert({
                    'id': user_id,
                    'email': email,
                    'password': password,
                    'is_paid': is_paid
                }).execute()
                return
            except Exception as e:
                logger.warning(f"Supabase create_user failed, falling back to SQLite: {e}")

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
            return order_id
        else:
            with sqlite3.connect(self.local_db) as conn:
                cur = conn.cursor()
                cur.execute('''INSERT INTO orders
                    (paypal_order_id, email, package, amount, status, created_at, target_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (paypal_id, email, package, amount, 'created', created_at, target_url))
                order_id = cur.lastrowid
                conn.commit()
            return order_id

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

    def get_order(self, paypal_id):
        """Get order by paypal_order_id."""
        if self.use_supabase:
            result = self.supabase.table('orders').select('*').eq('paypal_order_id', paypal_id).execute()
            return result.data[0] if result.data else None
        else:
            return self.fetch_one('SELECT * FROM orders WHERE paypal_order_id = ?', (paypal_id,))

    def upsert_job(self, job_id, email, data):
        """Persist or update an investigation job state."""
        vals = {
            'id': job_id,
            'email': email,
            'target_url': data.get('target_url') or '',
            'status': data.get('status') or 'processing',
            'progress': data.get('progress_percent') or 0,
            'stage_label': data.get('stage_label') or data.get('status_detail') or '',
            'report_file': data.get('report_file') or '',
            'public_report_file': data.get('public_report_file') or '',
            'created_at': data.get('created_at') or datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'referrer': data.get('referrer') or None,
            'utm_source': data.get('utm_source') or None,
            'utm_medium': data.get('utm_medium') or None,
            'utm_campaign': data.get('utm_campaign') or None,
            'user_agent': data.get('user_agent') or None,
            'job_type': data.get('type') or 'demo',
        }

        if self.use_supabase:
            try:
                self.supabase.table('forensic_jobs').upsert(vals).execute()
                return
            except Exception as e:
                logger.warning(f"Supabase upsert_job failed, falling back to SQLite: {e}")

        with sqlite3.connect(self.local_db) as conn:
                conn.execute('''
                    INSERT INTO forensic_jobs (id, email, target_url, status, progress, stage_label, report_file, public_report_file, created_at, updated_at, referrer, utm_source, utm_medium, utm_campaign, user_agent, job_type)
                    VALUES (:id, :email, :target_url, :status, :progress, :stage_label, :report_file, :public_report_file, :created_at, :updated_at, :referrer, :utm_source, :utm_medium, :utm_campaign, :user_agent, :job_type)
                    ON CONFLICT(id) DO UPDATE SET
                        status=excluded.status,
                        progress=excluded.progress,
                        stage_label=excluded.stage_label,
                        report_file=excluded.report_file,
                        public_report_file=excluded.public_report_file,
                        updated_at=excluded.updated_at,
                        referrer=coalesce(excluded.referrer, forensic_jobs.referrer),
                        utm_source=coalesce(excluded.utm_source, forensic_jobs.utm_source),
                        utm_medium=coalesce(excluded.utm_medium, forensic_jobs.utm_medium),
                        utm_campaign=coalesce(excluded.utm_campaign, forensic_jobs.utm_campaign),
                        user_agent=coalesce(excluded.user_agent, forensic_jobs.user_agent),
                        job_type=excluded.job_type
                ''', vals)

    def get_user_forensics(self, email: str) -> List[Dict]:
        """Fetch all historical orders AND active investigations for a user."""
        if self.use_supabase:
            # Union of orders and active jobs
            orders = self.supabase.table('orders').select('*').eq('email', email).execute().data
            jobs = self.supabase.table('forensic_jobs').select('*').eq('email', email).execute().data
            return sorted(orders + jobs, key=lambda x: x.get('created_at', ''), reverse=True)
        else:
            orders = self.execute('SELECT * FROM orders WHERE email = ?', (email,), commit=False)
            jobs = self.execute('SELECT * FROM forensic_jobs WHERE email = ?', (email,), commit=False)
            return sorted(orders + jobs, key=lambda x: x.get('created_at', ''), reverse=True)

    def get_user_reports(self, email: str) -> List[Dict]:
        if self.use_supabase:
            res = self.supabase.table('orders').select('*').eq('email', email).order('created_at', desc=True).execute()
            return res.data
        else:
            return self.execute('SELECT * FROM orders WHERE email = ? ORDER BY created_at DESC', (email,), commit=False)

    def list_jobs(self, limit: int = 200) -> List[Dict]:
        """Admin: return most recent forensic_jobs rows across all users."""
        if self.use_supabase:
            try:
                res = self.supabase.table('forensic_jobs').select('*').order('created_at', desc=True).limit(limit).execute()
                return res.data
            except Exception as e:
                logger.warning(f"Supabase list_jobs failed, falling back to SQLite: {e}")
        return self.execute(
            'SELECT * FROM forensic_jobs ORDER BY created_at DESC LIMIT ?', (limit,), commit=False
        )

    def list_jobs(self, limit: int = 200) -> List[Dict]:
        """Admin: return most recent forensic_jobs rows across all users."""
        if self.use_supabase:
            try:
                res = self.supabase.table('forensic_jobs').select('*').order('created_at', desc=True).limit(limit).execute()
                return res.data
            except Exception as e:
                logger.warning(f"Supabase list_jobs failed, falling back to SQLite: {e}")
        return self.execute(
            'SELECT * FROM forensic_jobs ORDER BY created_at DESC LIMIT ?', (limit,), commit=False
        )
