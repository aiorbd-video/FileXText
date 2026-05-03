from fastapi import FastAPI
import sqlite3

app = FastAPI()

conn = sqlite3.connect("data.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    file_name TEXT,
    file_id TEXT
)
""")

@app.get("/")
def home():
    return {"status": "running"}

@app.get("/files")
def get_files():
    cursor.execute("SELECT * FROM files")
    return cursor.fetchall()

@app.get("/stats")
def stats():
    cursor.execute("SELECT COUNT(*) FROM files")
    return {"total": cursor.fetchone()[0]}
