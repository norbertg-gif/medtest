from .database import SessionLocal, engine
from .models import Base, Question, Answer

Base.metadata.create_all(bind=engine)

db = SessionLocal()

questions_data = [
    {
        "order": 1,
        "text": "Koľko má človek komôr srdca?",
        "multiple": False,
        "answers": [
            ("2", False),
            ("4", True),
            ("6", False),
        ]
    },
    {
        "order": 2,
        "text": "Ktoré sú nepárové orgány?",
        "multiple": True,
        "answers": [
            ("Pečeň", True),
            ("Oblička", False),
            ("Srdce", True),
        ]
    },
    {
        "order": 3,
        "text": "Koľko má človek chromozómov?",
        "multiple": False,
        "answers": [
            ("23", False),
            ("46", True),
            ("48", False),
        ]
    }
]

for qdata in questions_data:
    q = Question(
        order_number=qdata["order"],
        text=qdata["text"],
        multiple_allowed=qdata["multiple"]
    )
    db.add(q)
    db.commit()

    for text, correct in qdata["answers"]:
        a = Answer(
            question_id=q.id,
            text=text,
            is_correct=correct
        )
        db.add(a)

    db.commit()

db.close()

print("Questions added.")
