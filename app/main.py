from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from passlib.hash import pbkdf2_sha256

from .database import SessionLocal, engine
from .models import Base, User, Question, Answer, UserAnswer, Test, TestResult

import csv
import io
import json
from datetime import datetime

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecret")
templates = Jinja2Templates(directory="app/templates")


# ================= DATABASE =================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


# ================= ADMIN =================

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):

    admin = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()

    if not admin or not admin.is_admin:
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

    questions = db.query(Question)\
        .filter(Question.test_id == user.assigned_test_id)\
        .order_by(Question.order_number)\
        .all()

    user_answers = db.query(UserAnswer)\
        .filter(UserAnswer.user_id == user_id)\
        .all()

    answered = {ua.question_id for ua in user_answers if ua.status == "answered"}
    skipped = [ua.question_id for ua in user_answers if ua.status == "skipped"]
    existing = {ua.question_id for ua in user_answers}

    # nové otázky
    for q in questions:
        if q.id not in existing:
            return render_question(q, skipped, request, db)

    # preskočené
    if skipped:
        q = db.query(Question).filter(Question.id == skipped[0]).first()
        return render_question(q, skipped, request, db)

    # archivovať
    return archive_test(user, questions, user_id, db)


def render_question(question, skipped, request, db):
    answers = db.query(Answer)\
        .filter(Answer.question_id == question.id)\
        .all()

    return templates.TemplateResponse("question.html", {
        "request": request,
        "question": question,
        "answers": answers,
        "skipped": skipped,
        "error": None
    })


def archive_test(user, questions, user_id, db):

    correct_count = 0
    snapshot = []

    for q in questions:
        answers = db.query(Answer)\
            .filter(Answer.question_id == q.id)\
            .all()

        ua = db.query(UserAnswer).filter(
            UserAnswer.user_id == user_id,
            UserAnswer.question_id == q.id
        ).first()

        selected = json.loads(ua.selected_answers)

        correct_ids = [str(a.id) for a in answers if a.is_correct]
        is_question_correct = set(selected) == set(correct_ids)

        if is_question_correct:
            correct_count += 1

        answers_snapshot = []

        for a in answers:
            answers_snapshot.append({
                "text": a.text,
                "is_correct": a.is_correct,
                "is_selected": str(a.id) in selected
            })

        snapshot.append({
            "question": q.text,
            "answers": answers_snapshot
        })

    percent = round((correct_count / len(questions)) * 100, 2)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    test = db.query(Test).filter(Test.id == user.assigned_test_id).first()

    db.add(TestResult(
        user_id=user.id,
        username=user.username,
        test_id=test.id,
        test_name=test.name,
        completed_at=timestamp,
        score_percent=percent,
        correct_answers=correct_count,
        total_questions=len(questions),
        snapshot=json.dumps(snapshot)
    ))

    db.query(UserAnswer).filter(UserAnswer.user_id == user.id).delete()
    user.assigned_test_id = None

    db.commit()

    return HTMLResponse("<h2>Test uložený do archívu.</h2>")


@app.post("/answer")
def submit_answer(request: Request,
                  action: str = Form(...),
                  answer_ids: list[str] = Form([]),
                  db: Session = Depends(get_db)):

    user_id = request.session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()

    questions = db.query(Question)\
        .filter(Question.test_id == user.assigned_test_id)\
        .order_by(Question.order_number)\
        .all()

    user_answers = db.query(UserAnswer)\
        .filter(UserAnswer.user_id == user_id)\
        .all()

    existing = {ua.question_id for ua in user_answers}
    skipped = [ua.question_id for ua in user_answers if ua.status == "skipped"]

    current = None

    for q in questions:
        if q.id not in existing:
            current = q
            break

    if not current and skipped:
        current = db.query(Question).filter(
            Question.id == skipped[0]
        ).first()

    if action == "next" and not answer_ids:
        return render_question(current, skipped, request, db)

    status = "skipped" if action == "skip" else "answered"

    existing_record = db.query(UserAnswer).filter(
        UserAnswer.user_id == user_id,
        UserAnswer.question_id == current.id
    ).first()

    if existing_record:
        existing_record.selected_answers = json.dumps(answer_ids)
        existing_record.status = status
    else:
        db.add(UserAnswer(
            user_id=user_id,
            question_id=current.id,
            selected_answers=json.dumps(answer_ids),
            status=status
        ))

    db.commit()

    return RedirectResponse("/question", status_code=302)


# ================= ARCHIVE REVIEW =================

@app.get("/admin/result/{result_id}", response_class=HTMLResponse)
def view_result(result_id: int,
                request: Request,
                db: Session = Depends(get_db)):

    admin = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()

    if not admin or not admin.is_admin:
        return RedirectResponse("/", status_code=302)

    result = db.query(TestResult).filter(
        TestResult.id == result_id
    ).first()

    snapshot = json.loads(result.snapshot)

    return templates.TemplateResponse("result_review.html", {
        "request": request,
        "result": result,
        "snapshot": snapshot
    })
