from enum import Enum
import enum

class OAuthProvider(str, Enum):
    GOOGLE = "google"
    FACEBOOK = "facebook"
    GITHUB = "github"

class PlayerRole(str, Enum):
    PLAYER = "player"
    SPECTATOR = "spectator"


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
