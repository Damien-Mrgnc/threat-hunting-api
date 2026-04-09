from sqlalchemy import create_engine, text
import os
import bcrypt

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://analyst_user:secure_password_123@db:5432/threat_hunting_db")
engine = create_engine(DATABASE_URL)

# Password to set
username = "analyst"
password = "analyst"

# Generate Hash
salt = bcrypt.gensalt()
new_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

with engine.connect() as conn:
    print(f"Updating {username} password hash...")
    conn.execute(text(f"UPDATE users SET hashed_password = :h WHERE username = :u"), {"h": new_hash, "u": username})
    conn.commit()
    print("Done.")
