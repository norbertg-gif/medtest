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

@app.get("/admin/create-test", response_class=HTMLResponse)
def create_test_form(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    return templates.TemplateResponse("create_test.html", {"request": request})


@app.post("/admin/create-test")
def create_test(
        request: Request,
        name: str = Form(...),
        csv_file: UploadFile = File(None),
        db: Session = Depends(get_db)
):
    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    new_test = Test(name=name)
    db.add(new_test)
    db.commit()
    db.refresh(new_test)

    # CSV import otázok (voliteľné)
    if csv_file:
        content = csv_file.file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))

        order = 1

        for row in reader:
            question = Question(
                text=row["question"],
                test_id=new_test.id,
                order_number=order
            )
            db.add(question)
            db.commit()
            db.refresh(question)

            answers = json.loads(row["answers"])

            for ans in answers:
                db.add(Answer(
                    text=ans["text"],
                    is_correct=ans["is_correct"],
                    question_id=question.id
                ))

            order += 1

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


@app.post("/admin/reset-user")
def reset_user(user_id: int = Form(...),
               db: Session = Depends(get_db)):

    db.query(UserAnswer).filter(UserAnswer.user_id == user_id).delete()
    db.commit()

    return RedirectResponse("/admin", status_code=302)


# ================= TEST FLOW =================

@app.get("/question", response_class=HTMLResponse)
def get_question(request: Request, db: Session = Depends(get_db)):

    user_id = request.session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()

    if not user or not user.assigned_test_id:
        return RedirectResponse("/", status_code=302)

    questions = db.query(Question)\
        .filter(Question.test_id == user.assigned_test_id)\
        .order_by(Question.order_number)\
        .all()

    user_answers = db.query(UserAnswer)\
        .filter(UserAnswer.user_id == user_id)\
        .all()

    existing = {ua.question_id for ua in user_answers}
    skipped = [ua.question_id for ua in user_answers if ua.status == "skipped"]

    for q in questions:
        if q.id not in existing:
            return render_question(q, skipped, request, db)

    if skipped:
        q = db.query(Question).filter(Question.id == skipped[0]).first()
        return render_question(q, skipped, request, db)

    return archive_test(user, questions, user_id, db)
