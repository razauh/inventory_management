from ..database import get_connection

def run():
    conn = get_connection()
    # ensure base rows exist (from schema default inserts)
    assert conn.execute("SELECT 1 FROM uoms LIMIT 1").fetchone()
    print("DB OK")

if __name__ == "__main__":
    run()
