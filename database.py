import sqlite3
from datetime import datetime

DATABASE_PATH = 'gate_system.db'

def init_db():
    """Initialize the database with required tables."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create persons table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS persons (
            id_number TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_blocked INTEGER DEFAULT 0,
            block_reason TEXT
        )
    ''')
    
    # Create entries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            id_number TEXT NOT NULL,
            status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_person(id_number):
    """Get person by ID number."""
    conn = get_db_connection()
    person = conn.execute('SELECT * FROM persons WHERE id_number = ?', (id_number,)).fetchone()
    conn.close()
    return person

def create_person(id_number, name):
    """Create a new person record."""
    conn = get_db_connection()
    conn.execute('INSERT INTO persons (id_number, name, is_blocked) VALUES (?, ?, 0)', 
                 (id_number, name))
    conn.commit()
    conn.close()

def create_entry(name, id_number, status):
    """Create a new entry record."""
    conn = get_db_connection()
    conn.execute('INSERT INTO entries (name, id_number, status) VALUES (?, ?, ?)', 
                 (name, id_number, status))
    conn.commit()
    conn.close()

def block_person(id_number, reason="Administrative decision"):
    """Block a person."""
    conn = get_db_connection()
    conn.execute('UPDATE persons SET is_blocked = 1, block_reason = ? WHERE id_number = ?', 
                 (reason, id_number))
    conn.commit()
    conn.close()

def unblock_person(id_number):
    """Unblock a person."""
    conn = get_db_connection()
    conn.execute('UPDATE persons SET is_blocked = 0, block_reason = NULL WHERE id_number = ?', 
                 (id_number,))
    conn.commit()
    conn.close()

def get_all_persons():
    """Get all persons."""
    conn = get_db_connection()
    persons = conn.execute('SELECT * FROM persons ORDER BY name').fetchall()
    conn.close()
    return persons

def get_all_entries():
    """Get all entries."""
    conn = get_db_connection()
    entries = conn.execute('SELECT * FROM entries ORDER BY timestamp DESC LIMIT 100').fetchall()
    conn.close()
    return entries
