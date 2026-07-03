"""
Run once after first launch to create the admin account.
Usage: python seed_admin.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import Base, engine, SessionLocal
from app.models.models import User, Role
from app.auth import hash_password

Base.metadata.create_all(bind=engine)

db = SessionLocal()
email = "admin@healthbook.com"
existing = db.query(User).filter(User.email == email).first()
if existing:
    print(f"Admin already exists: {email}")
else:
    admin = User(
        email=email,
        hashed_password=hash_password("admin123"),
        full_name="System Admin",
        role=Role.admin,
    )
    db.add(admin)
    db.commit()
    print(f"✅ Admin created: {email} / admin123")
    print("   ⚠️  Change this password before deploying to production!")
db.close()
