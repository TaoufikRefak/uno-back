from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid
from pydantic import BaseModel, Field
import random
from uuid import UUID, uuid4
from typing import Set
import time
from pydantic import ConfigDict
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.schemas import CardColor, CardType, OAuthProvider, PlayerRole,GameDirection, GameStatus, PlayerRole, UnoDeclarationState


SECRET_KEY = "your-secret-key-here"  # Change this in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")



class Card(BaseModel):
    color: CardColor
    type: CardType
    value: Optional[int] = Field(None, ge=0, le=9)  # Only for number cards
    
    def __str__(self):
        if self.type == CardType.NUMBER:
            return f"{self.color.value}_{self.value}"
        return f"{self.color.value}_{self.type.value}"
    
    def to_dict(self):
        """Convert card to a JSON-serializable dictionary"""
        return {
            "color": self.color.value,
            "type": self.type.value,
            "value": self.value
        }
    
    
    def is_playable_on(self, other_card: 'Card') -> bool:
    # Wild cards can always be played
        if self.type in [CardType.WILD, CardType.WILD_DRAW_FOUR]:
            print(f"Card {self} is playable because it's wild")
            return True
            
        # Same color cards can always be played
        if self.color == other_card.color:
            print(f"Card {self} is playable because same color as {other_card}")
            return True
            
        # Same type handling
        if self.type == other_card.type:
            # For number cards, values must match
            if self.type == CardType.NUMBER:
                if self.value == other_card.value:
                    print(f"Card {self} is playable because same value as {other_card}")
                    return True
                else:
                    print(f"Card {self} is NOT playable because different value from {other_card}")
                    return False
            # For action cards, same type is sufficient
            else:
                print(f"Card {self} is playable because same type as {other_card}")
                return True
                
        print(f"Card {self} is NOT playable on {other_card}")
        return False

class CardDeck:
    """
    Utility class to manage a deck of Uno cards
    """
    @staticmethod
    def create_deck() -> List[Card]:
        deck = []
        
        # Add number cards (1-9 for each color, two of each except 0)
        for color in [c for c in CardColor if c != CardColor.WILD]:
            # One zero card per color
            deck.append(Card(color=color, type=CardType.NUMBER, value=0))
            
            # Two of each 1-9 per color
            for value in range(1, 10):
                deck.append(Card(color=color, type=CardType.NUMBER, value=value))
                deck.append(Card(color=color, type=CardType.NUMBER, value=value))
            
            # Two of each special card per color
            for special_type in [CardType.SKIP, CardType.REVERSE, CardType.DRAW_TWO]:
                deck.append(Card(color=color, type=special_type))
                deck.append(Card(color=color, type=special_type))
        
        # Add wild cards (4 of each)
        for _ in range(4):
            deck.append(Card(color=CardColor.WILD, type=CardType.WILD))
            deck.append(Card(color=CardColor.WILD, type=CardType.WILD_DRAW_FOUR))
            
        return deck
    
    @staticmethod
    def shuffle(deck: List[Card]) -> List[Card]:
        """Shuffle a deck of cards"""
        random.shuffle(deck)
        return deck
    
    @staticmethod
    def draw_cards(deck: List[Card], count: int = 1) -> tuple[List[Card], List[Card]]:
        """Draw cards from the deck, returning the drawn cards and the remaining deck"""
        if count > len(deck):
            # In a real game, we'd reshuffle the discard pile, but for now we'll just draw what's available
            count = len(deck)
        
        drawn = deck[:count]
        remaining = deck[count:]
        
        return drawn, remaining
    


# Pydantic models
class UserBase(BaseModel):
    email: str
    username: str
    is_active: Optional[bool] = True

class UserCreate(UserBase):
    password: Optional[str] = None  # For local registration

class User(UserBase):
    id: UUID
    created_at: float
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None

class TokenData(BaseModel):
    username: Optional[str] = None

class OAuthToken(BaseModel):
    provider: OAuthProvider
    token: str

# Utility functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token():
    return str(uuid.uuid4())


class Player(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: Optional[UUID] = None # <-- ADD THIS LINE to link player to user

    username: str
    hand: List[Card] = Field(default_factory=list)
    session_token: Optional[str] = None
    is_online: bool = True    
    is_bot: bool = False # <-- ADD THIS LINE

    has_uno: bool = Field(default=False)
    uno_declaration: UnoDeclarationState = UnoDeclarationState.NOT_REQUIRED
    role: PlayerRole = PlayerRole.PLAYER  # Add this field
    # Updated config for Pydantic V2
    model_config = ConfigDict(extra='ignore')
    
    def to_public_dict(self) -> Dict[str, Any]:
        """Return a public representation of the player (without revealing hand contents)"""
        return {
            "id": str(self.id),
            "username": self.username,
            "hand_size": self.get_hand_size(),
            "is_online": self.is_online,
            "has_uno": self.has_uno
        }
    

    def add_cards(self, cards: List[Card]):
        """Add cards to player's hand"""
        self.hand.extend(cards)
    
    def play_card(self, card_index: int) -> Optional[Card]:
        """Remove and return a card from player's hand"""
        if 0 <= card_index < len(self.hand):
            return self.hand.pop(card_index)
        return None
    
    def get_hand_size(self) -> int:
        """Get number of cards in hand"""
        return len(self.hand)
    
    





class Table(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    players: List[Player] = Field(default_factory=list)
    spectators: List[Player] = Field(default_factory=list)  # Add spectators list
    max_players: int = Field(default=10, ge=2, le=10)
    status: GameStatus = GameStatus.WAITING
    created_at: float = Field(default_factory=lambda: time.time())
    creator_id: Optional[UUID] = None # <-- ADD THIS LINE

    def add_player(self, player: Player) -> bool:
        """Add a player to the table if there's space"""
        if len(self.players) < self.max_players and self.status == GameStatus.WAITING:
            self.players.append(player)
            return True
        return False
    
    def add_spectator(self, player: Player) -> bool:
        """Add a spectator to the table"""
        self.spectators.append(player)
        return True
    
    def remove_player(self, player_id: UUID) -> bool:
        """Remove a player from the table"""
        for i, player in enumerate(self.players):
            if player.id == player_id:
                self.players.pop(i)
                return True
        return False
    
    def remove_spectator(self, player_id: UUID) -> bool:
        """Remove a spectator from the table"""
        for i, spectator in enumerate(self.spectators):
            if spectator.id == player_id:
                self.spectators.pop(i)
                return True
        return False
    
    def get_player(self, player_id: str) -> Optional[Player]:
        """Get a player by ID string (checks both players and spectators)"""
        try:
            player_uuid = UUID(player_id)
        except ValueError:
            return None
            
        # Check players first
        for player in self.players:
            if player.id == player_uuid:
                return player
                
        # Check spectators
        for spectator in self.spectators:
            if spectator.id == player_uuid:
                return spectator
                
        return None

class GameState(BaseModel):
    """Represents the current state of a game at a table"""
    table_id: UUID
    draw_pile: List[Card] = Field(default_factory=list)
    discard_pile: List[Card] = Field(default_factory=list)
    current_player_index: int = 0
    direction: GameDirection = GameDirection.CLOCKWISE
    status: GameStatus = GameStatus.WAITING
    winner: Optional[UUID] = None
    last_action: Optional[Dict[str, Any]] = None
    
    def initialize_game(self, table: Table):
        """Initialize a new game - only deal cards to players, not spectators"""
        self.status = GameStatus.IN_PROGRESS
        self.winner = None
        self.current_player_index = 0
        self.direction = GameDirection.CLOCKWISE
        
        # Create and shuffle the deck
        self.draw_pile = CardDeck.shuffle(CardDeck.create_deck())
        
        # Deal 7 cards to each player (not spectators)
        for player in table.players:
            drawn_cards, self.draw_pile = CardDeck.draw_cards(self.draw_pile, 7)
            player.hand = drawn_cards
            player.has_uno = False
        
        # Place the first card on the discard pile (must be a non-wild card)
        first_card = None
        while self.draw_pile and (not first_card or first_card.color == CardColor.WILD):
            drawn_cards, self.draw_pile = CardDeck.draw_cards(self.draw_pile, 1)
            if drawn_cards:
                first_card = drawn_cards[0]
        
        if first_card:
            self.discard_pile = [first_card]
        else:
            # Fallback if no valid card found - create a red zero
            self.discard_pile = [Card(color=CardColor.RED, type=CardType.NUMBER, value=0)]
        
        # Make sure to set the game status to in progress
        self.status = GameStatus.IN_PROGRESS

    

    def get_next_player_index(self, table: Table) -> int:
        """Get the index of the next player"""
        if self.direction == GameDirection.CLOCKWISE:
            return (self.current_player_index + 1) % len(table.players)
        else:
            return (self.current_player_index - 1) % len(table.players)
    
    def get_current_player(self, table: Table) -> Optional[Player]:
        """Get the current player based on the table"""
        if not table.players:
            return None
        return table.players[self.current_player_index]
    
    def next_turn(self, table: Table) -> UUID:
        """Advance to the next player and return their ID"""
        if self.direction == GameDirection.CLOCKWISE:
            self.current_player_index = (self.current_player_index + 1) % len(table.players)
        else:
            self.current_player_index = (self.current_player_index - 1) % len(table.players)
        
        return table.players[self.current_player_index].id
    
    def reverse_direction(self):
        """Reverse the game direction"""
        self.direction = (
            GameDirection.CLOCKWISE 
            if self.direction == GameDirection.COUNTER_CLOCKWISE 
            else GameDirection.COUNTER_CLOCKWISE
        )
    
    def get_top_discard_card(self) -> Optional[Card]:
        """Get the top card from the discard pile"""
        if not self.discard_pile:
            return None
        return self.discard_pile[-1]
    
    def draw_cards_for_player(self, player: Player, count: int = 1) -> List[Card]:
        """Draw cards for a player from the draw pile"""
        if count <= 0:
            return []
            
        # If draw pile is empty, reshuffle discard pile (except top card)
        if len(self.draw_pile) < count:
            if len(self.discard_pile) > 1:
                # Save the top card
                top_card = self.discard_pile.pop()
                # Shuffle the rest and use as new draw pile
                self.draw_pile = CardDeck.shuffle(self.discard_pile)
                # Put the top card back
                self.discard_pile = [top_card]
            else:
                # Not enough cards to draw
                count = len(self.draw_pile)
        
        drawn_cards, self.draw_pile = CardDeck.draw_cards(self.draw_pile, count)
        player.add_cards(drawn_cards)
        return drawn_cards
    
    def check_win_condition(self, player: Player) -> bool:
        """Check if a player has won (empty hand)"""
        return len(player.hand) == 0
    
    def to_public_dict(self, table: Table, requesting_player: Optional[Player] = None) -> Dict[str, Any]:
        """Return a public representation of the game state"""
        current_player = self.get_current_player(table)
        top_card = self.get_top_discard_card()
        
        # Create player info
        players_info = []
        for player in table.players:
            player_info = {
                "id": str(player.id),
                "username": player.username,
                "hand_count": len(player.hand),
                "is_online": player.is_online,
                "is_bot": player.is_bot, 
                "is_you": requesting_player and player.id == requesting_player.id,
                "uno_declaration": player.uno_declaration.value,
                "role": player.role.value if hasattr(player, 'role') else "player"
            }
            players_info.append(player_info)
        
        # Create spectator info (limited details)
        spectators_info = []
        for spectator in table.spectators:
            spectator_info = {
                "id": str(spectator.id),
                "username": spectator.username,
                "is_online": spectator.is_online,
                "is_you": requesting_player and spectator.id == requesting_player.id,
                "role": "spectator"
            }
            spectators_info.append(spectator_info)
        
        return {
            "table_id": str(self.table_id),
            "discard_top": top_card.to_dict() if top_card else None,
            "draw_pile_count": len(self.draw_pile),
            "current_player_id": str(current_player.id) if current_player else None,
            "direction": self.direction.value,
            "status": self.status.value,
            "winner_id": str(self.winner) if self.winner else None,
            "players": players_info,
            "spectators": spectators_info,
            "last_action": self.last_action
        }