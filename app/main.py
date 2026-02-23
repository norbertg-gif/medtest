from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from passlib.hash import pbkdf2_sha256
from typing import List
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


# ================= CREATE ADMIN =================

@app.get("/create-admin")
def create_admin(db: Session = Depends(get_db)):

    existing = db.query(User).filter(User.username == "admin").first()

    if existing:
        return {"status": "already exists"}

    db.add(User(
        username="admin",
        password_hash=pbkdf2_sha256.hash("admin123"),
        is_admin=True
    ))
    db.commit()

    return {"status": "admin created"}


# ================= ADMIN DASHBOARD =================

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    users = db.query(User).filter(User.is_admin == False).all()
    tests = db.query(Test).all()
    results = db.query(TestResult).order_by(TestResult.id.desc()).all()

    user_progress = {}

    for u in users:
        if u.assigned_test_id:
            total_questions = db.query(Question).filter(
                Question.test_id == u.assigned_test_id
            ).count()

            answered_count = db.query(UserAnswer).filter(
                UserAnswer.user_id == u.id,
                UserAnswer.status == "answered"
            ).count()

            user_progress[u.id] = {
                "answered": answered_count,
                "total": total_questions
            }
        else:
            user_progress[u.id] = None

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "admin": admin,
        "users": users,
        "tests": tests,
        "results": results,
        "user_progress": user_progress
    })
# ================= TEST MANAGEMENT =================

@app.post("/admin/create-test")
def create_test(request: Request,
                name: str = Form(...),
                db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    db.add(Test(name=name))
    db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/import")
def import_csv(request: Request,
               test_id: int = Form(...),
               file: UploadFile = File(...),
               db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        return RedirectResponse("/admin", status_code=302)

    test.source_csv = file.filename
    db.commit()

    # zmaž staré otázky
    db.query(Answer).filter(
        Answer.question_id.in_(
            db.query(Question.id).filter(Question.test_id == test.id)
        )
    ).delete(synchronize_session=False)

    db.query(Question).filter(Question.test_id == test.id).delete()
    db.commit()

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

# ================= RENAME TEST =================

@app.post("/admin/rename-test")
def rename_test(request: Request,
                test_id: int = Form(...),
                new_name: str = Form(...),
                db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    test = db.query(Test).filter(Test.id == test_id).first()

    if not test:
        return RedirectResponse("/admin", status_code=302)

    # ochrana proti prázdnemu názvu
    if new_name.strip():
        test.name = new_name.strip()
        db.commit()

    return RedirectResponse("/admin", status_code=302)
# ================= USER MANAGEMENT =================

@app.post("/admin/create-user")
def create_user(username: str = Form(...),
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


@app.post("/admin/delete-result")
def delete_result(request: Request,
                  result_id: int = Form(...),
                  db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    db.query(TestResult).filter(TestResult.id == result_id).delete()
    db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/reset-user")
def reset_user(user_id: int = Form(...),
               db: Session = Depends(get_db)):

    db.query(UserAnswer).filter(UserAnswer.user_id == user_id).delete()

    user = db.query(User).filter(User.id == user_id).first()
    user.has_finished = False

    db.commit()

    return RedirectResponse("/admin", status_code=302)
                   # ================= ASSIGN / UNASSIGN TEST =================

@app.post("/admin/assign-test")
def assign_test(request: Request,
                user_id: int = Form(...),
                test_id: int = Form(...),
                db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return RedirectResponse("/admin", status_code=302)

    user.assigned_test_id = test_id
    user.has_finished = False

    # vymaž staré odpovede
    db.query(UserAnswer).filter(
        UserAnswer.user_id == user_id
    ).delete()

    db.commit()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/unassign-test")
def unassign_test(request: Request,
                  user_id: int = Form(...),
                  db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return RedirectResponse("/admin", status_code=302)

    user.assigned_test_id = None
    user.has_finished = False

    db.query(UserAnswer).filter(
        UserAnswer.user_id == user_id
    ).delete()

    db.commit()

    return RedirectResponse("/admin", status_code=302)

# ================= DELETE USER =================

@app.post("/admin/delete-user")
def delete_user(request: Request,
                user_id: int = Form(...),
                db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return RedirectResponse("/admin", status_code=302)

    # vymažeme jeho odpovede
    db.query(UserAnswer).filter(
        UserAnswer.user_id == user.id
    ).delete()

    # vymažeme jeho výsledky v archíve
    db.query(TestResult).filter(
        TestResult.user_id == user.id
    ).delete()

    # zmažeme používateľa
    db.delete(user)
    db.commit()

    return RedirectResponse("/admin", status_code=302)
# ================= TEST FLOW =================

@app.get("/question", response_class=HTMLResponse)
def get_question(request: Request, db: Session = Depends(get_db)):

    user = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()

    if not user or not user.assigned_test_id:
        return RedirectResponse("/", status_code=302)

    questions = db.query(Question)\
        .filter(Question.test_id == user.assigned_test_id)\
        .order_by(Question.order_number)\
        .all()

    total_questions = len(questions)

    user_answers = db.query(UserAnswer)\
        .filter(UserAnswer.user_id == user.id)\
        .all()

    answered_ids = {
        ua.question_id for ua in user_answers
        if ua.status == "answered"
    }

    skipped_ids = [
        ua.question_id for ua in user_answers
        if ua.status == "skipped"
    ]

    # prevedieme skipped na poradové čísla
    skipped_orders = []
    for qid in skipped_ids:
        q_obj = db.query(Question).filter(
            Question.id == qid
        ).first()
        if q_obj:
            skipped_orders.append(q_obj.order_number)

    # 1️⃣ nové otázky
    for q in questions:
        if q.id not in answered_ids and q.id not in skipped_ids:
            return render_question(
                q,
                skipped_orders,
                request,
                db,
                current_number=q.order_number,
                total_questions=total_questions
            )

    # 2️⃣ preskočené
    if skipped_ids:
        q = db.query(Question).filter(
            Question.id == skipped_ids[0]
        ).first()

        return render_question(
            q,
            skipped_orders,
            request,
            db,
            current_number=q.order_number,
            total_questions=total_questions
        )

    # 3️⃣ archivuj
    return archive_test(user, questions, db)


@app.post("/answer")
def submit_answer(request: Request,
                  action: str = Form(...),
                  answer_ids: List[str] = Form(default=[]),
                  db: Session = Depends(get_db)):

    user = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()

    questions = db.query(Question)\
        .filter(Question.test_id == user.assigned_test_id)\
        .order_by(Question.order_number)\
        .all()

    user_answers = db.query(UserAnswer)\
        .filter(UserAnswer.user_id == user.id)\
        .all()

    answered_ids = {ua.question_id for ua in user_answers if ua.status == "answered"}
    skipped_ids = [ua.question_id for ua in user_answers if ua.status == "skipped"]

    current = None

    for q in questions:
        if q.id not in answered_ids and q.id not in skipped_ids:
            current = q
            break

    if not current:
        if skipped_ids:
            current = db.query(Question).filter(
                Question.id == skipped_ids[0]
            ).first()
        else:
            return RedirectResponse("/question", status_code=302)

    if action == "next" and not answer_ids:

        total_questions = len(questions)

        return render_question(
        current,
        skipped_ids,
        request,
        db,
        current_number=current.order_number,
        total_questions=total_questions,
        error="Vyplňte odpoveď alebo použite Preskočiť."
    )

    status = "skipped" if action == "skip" else "answered"

    existing = db.query(UserAnswer).filter(
        UserAnswer.user_id == user.id,
        UserAnswer.question_id == current.id
    ).first()

    if existing:
        existing.selected_answers = json.dumps(answer_ids)
        existing.status = status
    else:
        db.add(UserAnswer(
            user_id=user.id,
            question_id=current.id,
            selected_answers=json.dumps(answer_ids),
            status=status
        ))

    db.commit()

    return RedirectResponse("/question", status_code=302)


def render_question(question, skipped, request, db,
                    current_number=None,
                    total_questions=None,
                    error=None):

    user = db.query(User).filter(
        User.id == request.session.get("user_id")
    ).first()

    test_name = ""
    if user and user.assigned_test_id:
        test = db.query(Test).filter(
            Test.id == user.assigned_test_id
        ).first()
        if test:
            test_name = test.name

    answers = db.query(Answer).filter(
        Answer.question_id == question.id
    ).all()

    return templates.TemplateResponse("question.html", {
        "request": request,
        "question": question,
        "answers": answers,
        "skipped": skipped,
        "error": error,
        "current_number": current_number,
        "total_questions": total_questions,
        "username": user.username if user else "",
        "test_name": test_name
    })


def archive_test(user, questions, db):

    # 1️⃣ ochrana proti dvojitému spusteniu
    if user.has_finished:
        return HTMLResponse("<h2>Test už bol uložený.</h2>")

    if not user.assigned_test_id:
        return HTMLResponse("<h2>Chyba: test nie je priradený.</h2>")

    test = db.query(Test).filter(
        Test.id == user.assigned_test_id
    ).first()

    if not test:
        return HTMLResponse("<h2>Chyba: test neexistuje.</h2>")

    correct_count = 0
    snapshot = []

    for q in questions:

        answers = db.query(Answer).filter(
            Answer.question_id == q.id
        ).all()

        ua = db.query(UserAnswer).filter(
            UserAnswer.user_id == user.id,
            UserAnswer.question_id == q.id
        ).first()

        if ua and ua.selected_answers:
            selected = json.loads(ua.selected_answers)
        else:
            selected = []

        correct_ids = [str(a.id) for a in answers if a.is_correct]
        is_correct = set(selected) == set(correct_ids)

        if is_correct:
            correct_count += 1

        answers_snapshot = []
        for a in answers:
            answers_snapshot.append({
                "text": a.text,
                "is_correct": a.is_correct,
                "is_selected": str(a.id) in selected
            })

        snapshot.append({
    "order_number": q.order_number,
    "question": q.text,
    "answers": answers_snapshot
})

    # ochrana proti deleniu nulou
    if len(questions) == 0:
        percent = 0
    else:
        percent = round((correct_count / len(questions)) * 100, 2)

    db.add(TestResult(
        user_id=user.id,
        username=user.username,
        test_id=test.id,
        test_name=test.name,
        completed_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        score_percent=percent,
        correct_answers=correct_count,
        total_questions=len(questions),
        snapshot=json.dumps(snapshot)
    ))

    # nastav stav až PO vytvorení výsledku
    user.has_finished = True
    user.assigned_test_id = None

    db.query(UserAnswer).filter(
        UserAnswer.user_id == user.id
    ).delete()

    db.commit()

    return HTMLResponse("<h2>Test uložený do archívu.</h2>")

# ================= ARCHIVE REVIEW =================

@app.get("/admin/result/{result_id}", response_class=HTMLResponse)
def review_result(result_id: int,
                  request: Request,
                  db: Session = Depends(get_db)):

    admin = require_admin(request, db)
    if not admin:
        return RedirectResponse("/", status_code=302)

    result = db.query(TestResult).filter(
        TestResult.id == result_id
    ).first()

    if not result:
        return HTMLResponse("<h2>Výsledok neexistuje.</h2>")

    snapshot = json.loads(result.snapshot)

    return templates.TemplateResponse(
        "result_review.html",
        {
            "request": request,
            "result": result,
            "snapshot": snapshot
        }
    )
# ================= DELETE TEST =================

@app.post("/admin/delete-test")
def delete_test(request: Request,
                test_id: int = Form(...),
                db: Session = Depends(get_db)):

    if not require_admin(request, db):
        return RedirectResponse("/", status_code=302)

    test = db.query(Test).filter(Test.id == test_id).first()

    if not test:
        return RedirectResponse("/admin", status_code=302)

    # zmaž odpovede k otázkam
    db.query(Answer).filter(
        Answer.question_id.in_(
            db.query(Question.id).filter(Question.test_id == test_id)
        )
    ).delete(synchronize_session=False)

    # zmaž otázky
    db.query(Question).filter(
        Question.test_id == test_id
    ).delete()

    # zmaž test
    db.delete(test)

    db.commit()

    return RedirectResponse("/admin", status_code=302)
