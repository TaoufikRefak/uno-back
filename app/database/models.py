from time import time
from sqlalchemy import Column, Integer, String, Boolean, JSON, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
import uuid
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from app.schemas import OAuthProvider, PlayerRole,GameDirection, GameStatus, PlayerRole, UnoDeclarationState

Base = declarative_base()

# JWT settings
SECRET_KEY = "your-secret-key-here"  # Change this in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")



class UserModel(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)  # For local authentication
    is_active = Column(Boolean, default=True)
    is_bot = Column(Boolean, default=False, nullable=False) # <-- ADD THIS LINE
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    
    # OAuth2 fields
    oauth_provider = Column(Enum(OAuthProvider), nullable=True)
    oauth_id = Column(String, nullable=True)
    
    # Relationships
    players = relationship("PlayerModel", back_populates="user")
    sessions = relationship("UserSessionModel", back_populates="user")

class UserSessionModel(Base):
    __tablename__ = "user_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expires_at = Column(Integer, nullable=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    
    user = relationship("UserModel", back_populates="sessions")



class TableModel(Base):
    __tablename__ = "tables"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    max_players = Column(Integer, default=10)
    status = Column(Enum(GameStatus), default=GameStatus.WAITING)
    created_at = Column(Integer, nullable=False)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True) # <-- ADD THIS

    players = relationship("PlayerModel", back_populates="table")
    game_state = relationship("GameStateModel", uselist=False, back_populates="table")

class PlayerModel(Base):
    __tablename__ = "players"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # Link to user
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"))
    hand = Column(JSON, default=[])  
    is_online = Column(Boolean, default=True)
    uno_declaration = Column(Enum(UnoDeclarationState), default=UnoDeclarationState.NOT_REQUIRED)
    role = Column(Enum(PlayerRole), default=PlayerRole.PLAYER)
    
    table = relationship("TableModel", back_populates="players")
    user = relationship("UserModel", back_populates="players")  # Add relationship
    sessions = relationship("SessionModel", back_populates="player")

class GameStateModel(Base):
    __tablename__ = "game_states"
    
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"), primary_key=True)
    draw_pile = Column(JSON, default=[])
    discard_pile = Column(JSON, default=[])
    current_player_index = Column(Integer, default=0)
    direction = Column(Enum(GameDirection), default=GameDirection.CLOCKWISE)
    status = Column(Enum(GameStatus), default=GameStatus.WAITING)
    winner = Column(UUID(as_uuid=True), nullable=True)
    last_action = Column(JSON, nullable=True)
    
    table = relationship("TableModel", back_populates="game_state")

class SessionModel(Base):
    __tablename__ = "sessions"
    
    session_token = Column(String, primary_key=True)
    player_id = Column(UUID(as_uuid=True), ForeignKey("players.id"))
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"))
    created_at = Column(Integer, nullable=False)
    
    player = relationship("PlayerModel", back_populates="sessions")