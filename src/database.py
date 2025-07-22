from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP, JSON, DateTime
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.sql import func
from src import config
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True)
    source_url = Column(Text, unique=True, nullable=False)
    publication_date = Column(TIMESTAMP(timezone=True), nullable=True)
    raw_markdown_content = Column(Text)
    processed_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class UserQuery(Base):
    __tablename__ = 'userqueries'
    id = Column(Integer, primary_key=True)
    query_text = Column(Text, nullable=False)
    is_subscribed = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    language = Column(String(10), default='en', nullable=False)
    
    # answer_template_text artık JSON tipi olacak
    # Eğer PostgreSQL kullanıyorsanız, JSON tipi doğrudan desteklenir
    answer_template_text = Column(MutableList.as_mutable(JSON), nullable=True) 
    final_answer = Column(Text, nullable=True)
    answer_last_updated = Column(DateTime(timezone=True), nullable=True)

    predictions = relationship("TemplatePredictionsLink", back_populates="user_query", cascade="all, delete-orphan")

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    base_language_code = Column(String(8), nullable=False, default="en")    
    prediction_prompt = Column(String, nullable=False, unique=True)
    predicted_value = Column(MutableDict.as_mutable(JSON), nullable=True)
    status = Column(String, nullable=True)
    last_updated = Column(DateTime(timezone=True), nullable=True)
    
    keywords = Column(MutableList.as_mutable(JSON), nullable=True)
    
    incremental_update_count = Column(Integer, default=0, nullable=False)
    
    user_queries = relationship("TemplatePredictionsLink", back_populates="prediction")


class TemplatePredictionsLink(Base):
    __tablename__ = 'template_predictions_link'
    id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey('userqueries.id', ondelete="CASCADE"), nullable=False)
    prediction_id = Column(Integer, ForeignKey('predictions.id', ondelete="CASCADE"), nullable=False)
    placeholder_name = Column(String(255), nullable=False)
    
    user_query = relationship("UserQuery", back_populates="predictions")
    prediction = relationship("Prediction", back_populates="user_queries")

engine = create_engine(config.POSTGRES_DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created or already exist.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()