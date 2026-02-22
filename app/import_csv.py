from .database import SessionLocal, engine
from .models import Base, Question, Answer, Test
import csv

Base.metadata.create_all(bind=engine)

db = SessionLocal()

TEST_NAME = "Test Medicína 2026"

test = db.query(Test).filter(Test.name == TEST_NAME).first()

if not test:
    test = Test(name=TEST_NAME)
    db.add(test)
    db.commit()

# zmaž otázky len pre tento test
questions = db.query(Question).filter(Question.test_id == test.id).all()
for q in questions:
    db.query(Answer).filter(Answer.question_id == q.id).delete()

db.query(Question).filter(Question.test_id == test.id).delete()
db.commit()

questions_cache = {}

with open("questions.csv", newline="", encoding="utf-8") as csvfile:
    reader = csv.DictReader(csvfile, delimiter=";")

    for row in reader:
        order = int(row["order_number"])

        if order not in questions_cache:
            q = Question(
                test_id=test.id,
                order_number=order,
                text=row["question_text"],
                multiple_allowed=bool(int(row["multiple_allowed"]))
            )
            db.add(q)
            db.commit()
            questions_cache[order] = q.id

        answer = Answer(
            question_id=questions_cache[order],
            text=row["answer_text"],
            is_correct=bool(int(row["is_correct"]))
        )

        db.add(answer)

    db.commit()

db.close()
print("Import hotový pre test:", TEST_NAME)
