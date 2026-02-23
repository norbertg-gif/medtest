from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from passlib.hash import pbkdf2_sha256
import os
import csv
import io
import json
from datetime import datetime

from .database import SessionLocal, engine
from .models import Base, User, Question, Answer, UserAnswer, Test, TestResult

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-secret")
)

templates = Jinja2Templates(directory="app/templates")


# ================= DATABASE =================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(request: Request, db: Session):
    user = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()
    if not user or not user.is_admin:
        return None
    return user


# ================= LOGIN =================

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request,
          username: str = Form(...),
          password: str = Form(...),
          db: Session = Depends(get_db)):

    user = db.query(User).filter(User.username == username).first()

    if not user or not pbkdf2_sha256.verify(password, user.password_hash):
        return RedirectResponse("/", status_code=302)

    request.session["user_id"] = user.id

    if user.is_admin:
        return RedirectResponse("/admin", status_code=302)

    if not user.assigned_test_id:
        return HTMLResponse("<h2>Nemáš priradený test.</h2>")

    return RedirectResponse("/question", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


# ================= ADMIN DASHBOARD =================

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    users = db.query(User).filter(User.is_admin == False).all()
    tests = db.query(Test).all()
    results = db.query(TestResult).order_by(TestResult.id.desc()).all()

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "admin": admin,
        "users": users,
        "tests": tests,
        "results": results
    })


# ================= CREATE TEST =================

@app.post("/admin/create-test")
def create_test(request: Request,
                name: str = Form(...),
                db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    db.add(Test(name=name))
    db.commit()

    return RedirectResponse("/admin", status_code=302)


# ================= IMPORT CSV (TVÔJ FORMÁT) =================

@app.post("/admin/import")
def import_csv(request: Request,
               test_id: int = Form(...),
               file: UploadFile = File(...),
               db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        return RedirectResponse("/admin", status_code=302)

    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content), delimiter=";")

    questions_map = {}

    for row in reader:
        order_number = int(row["order_number"])
        question_text = row["question_text"]
        multiple_allowed = bool(int(row["multiple_allowed"]))
        answer_text = row["answer_text"]
        is_correct = bool(int(row["is_correct"]))

        if order_number not in questions_map:
            question = Question(
                text=question_text,
                test_id=test.id,
                order_number=order_number,
                multiple_allowed=multiple_allowed
            )
            db.add(question)
            db.commit()
            db.refresh(question)

            questions_map[order_number] = question

        db.add(Answer(
            text=answer_text,
            is_correct=is_correct,
            question_id=questions_map[order_number].id
        ))

    db.commit()

    return RedirectResponse("/admin", status_code=302)


# ================= DELETE TEST =================

@app.post("/admin/delete-test")
def delete_test(request: Request,
                test_id: int = Form(...),
                db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    db.query(Answer).filter(
        Answer.question_id.in_(
            db.query(Question.id).filter(Question.test_id == test_id)
        )
    ).delete(synchronize_session=False)

    db.query(Question).filter(Question.test_id == test_id).delete()
    db.query(Test).filter(Test.id == test_id).delete()

    db.commit()

    return RedirectResponse("/admin", status_code=302)


# ================= USER MANAGEMENT =================

@app.post("/admin/create-user")
def create_user_admin(username: str = Form(...),
                      password: str = Form(...),
                      db: Session = Depends(get_db)):

    if not db.query(User).filter(User.username == username).first():
        db.add(User(
            username=username,
            password_hash=pbkdf2_sha256.hash(password),
            is_admin=False
        ))
        db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/delete-user")
def delete_user_admin(user_id: int = Form(...),
                      db: Session = Depends(get_db)):

    db.query(UserAnswer).filter(UserAnswer.user_id == user_id).delete()
    db.delete(db.query(User).filter(User.id == user_id).first())
    db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/assign-test")
def assign_test(user_id: int = Form(...),
                test_id: int = Form(...),
                db: Session = Depends(get_db)):

    user = db.query(User).filter(User.id == user_id).first()
    user.assigned_test_id = test_id

    db.query(UserAnswer).filter(UserAnswer.user_id == user_id).delete()
    db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/unassign-test")
def unassign_test(user_id: int = Form(...),
                  db: Session = Depends(get_db)):

    user = db.query(User).filter(User.id == user_id).first()
    user.assigned_test_id = None

    db.query(UserAnswer).filter(UserAnswer.user_id == user_id).delete()
    db.commit()

    return RedirectResponse("/admin", status_code=302)
