from sqlalchemy import Column, Integer, String, Boolean, JSON, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
import uuid

Base = declarative_base()

class CardColor(str, enum.Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    WILD = "wild"

class CardType(str, enum.Enum):
    NUMBER = "number"
    SKIP = "skip"
    REVERSE = "reverse"
    DRAW_TWO = "draw_two"
    WILD = "wild"
    WILD_DRAW_FOUR = "wild_draw_four"

class GameStatus(str, enum.Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class GameDirection(str, enum.Enum):
    CLOCKWISE = "clockwise"
    COUNTER_CLOCKWISE = "counter_clockwise"

class UnoDeclarationState(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    DECLARED = "declared"
    PENALIZED = "penalized"

class TableModel(Base):
    __tablename__ = "tables"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    max_players = Column(Integer, default=10)
    status = Column(Enum(GameStatus), default=GameStatus.WAITING)
    created_at = Column(Integer, nullable=False)
    
    players = relationship("PlayerModel", back_populates="table")
    game_state = relationship("GameStateModel", uselist=False, back_populates="table")

class PlayerModel(Base):
    __tablename__ = "players"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, nullable=False)
    hand = Column(JSON, default=[])  
    is_online = Column(Boolean, default=True)
    uno_declaration = Column(Enum(UnoDeclarationState), default=UnoDeclarationState.NOT_REQUIRED)
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"))
    
    table = relationship("TableModel", back_populates="players")
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