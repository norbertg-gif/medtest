from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from .database import Base


class Test(Base):
    __tablename__ = "tests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
    is_active = Column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    assigned_test_id = Column(Integer, ForeignKey("tests.id"), nullable=True)
    has_finished = Column(Boolean, default=False)


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_id = Column(Integer, ForeignKey("tests.id"))
    order_number = Column(Integer)
    text = Column(Text)
    multiple_allowed = Column(Boolean)


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id"))
    text = Column(Text)
    is_correct = Column(Boolean)


class UserAnswer(Base):
    __tablename__ = "user_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    question_id = Column(Integer)
    selected_answers = Column(Text)
    status = Column(String)


class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    username = Column(String)
    test_id = Column(Integer)
    test_name = Column(String)
    completed_at = Column(String)
    score_percent = Column(Integer)
    correct_answers = Column(Integer)
    total_questions = Column(Integer)
    snapshot = Column(Text)
