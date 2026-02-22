from .database import SessionLocal, engine
from .models import Base, User
from passlib.hash import pbkdf2_sha256

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Admin účet
admin = db.query(User).filter(User.username == "admin").first()
if not admin:
    admin = User(
        username="admin",
        password_hash=pbkdf2_sha256.hash("admin123"),
        is_admin=True
    )
    db.add(admin)
    db.commit()
    print("Admin created: admin / admin123")

# Test používateľ
user = db.query(User).filter(User.username == "test").first()
if not user:
    user = User(
        username="test",
        password_hash=pbkdf2_sha256.hash("test123"),
        is_admin=False
    )
    db.add(user)
    db.commit()
    print("User created: test / test123")

db.close()
print("Setup complete.")
