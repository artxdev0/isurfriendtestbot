
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from typing import List

####


class Base(DeclarativeBase):
    pass

####


class Test(Base):
    __tablename__ = 'tests'
    
    id: Mapped[int]          = mapped_column(autoincrement=True, primary_key=True)
    test_link: Mapped[str]   = mapped_column()
    creator_id: Mapped[int]  = mapped_column()  
    name: Mapped[str]        = mapped_column()
    
    questions: Mapped[List['TestQuestion']] = relationship(
        back_populates='test', cascade='all, delete-orphan',
    )


class TestQuestion(Base):
    __tablename__ = 'test_questions'
    
    id: Mapped[int]       = mapped_column(autoincrement=True, primary_key=True)
    name: Mapped[str]     = mapped_column()
    test_id: Mapped[int]  = mapped_column(ForeignKey('tests.id'))

    variants: Mapped[List['TestQuestionVariant']] = relationship(
        back_populates='question', cascade='all, delete-orphan',
    )

    test: Mapped['Test'] = relationship(back_populates='questions')


class TestQuestionVariant(Base):
    __tablename__ = 'test_questions_variants'
    
    id: Mapped[int]           = mapped_column(autoincrement=True, primary_key=True)
    value: Mapped[str]        = mapped_column()
    correct: Mapped[bool]     = mapped_column()
    question_id: Mapped[int]  = mapped_column(ForeignKey('test_questions.id'))

    question: Mapped['TestQuestion'] = relationship(back_populates='variants')


class Tester(Base):
    __tablename__ = 'testers'
    
    id: Mapped[int]           = mapped_column(autoincrement=True, primary_key=True)
    test_id: Mapped[int]      = mapped_column()
    tester_id: Mapped[int]    = mapped_column()
    percents: Mapped[float]   = mapped_column()
