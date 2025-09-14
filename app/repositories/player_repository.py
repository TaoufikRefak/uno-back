from time import time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.database.models import PlayerModel, UserModel
from app.models import Player, Card
from typing import List, Optional
import uuid
from app.schemas import PlayerRole, UnoDeclarationState
from app.repositories.user_repository import UserRepository  # You'll need to create this
class PlayerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_player(self, player_id: uuid.UUID) -> Optional[Player]:
        result = await self.db.execute(
            select(PlayerModel).where(PlayerModel.id == player_id)
        )
        player_model = result.scalar_one_or_none()
        
        if not player_model:
            return None
        
        # Get the user associated with this player
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == player_model.user_id)
        )
        user_model = result.scalar_one_or_none()
        
        if not user_model:
            return None
        
        # Convert hand from JSON to Card objects
        hand = [Card(**card) for card in player_model.hand]
        
        return Player(
            id=player_model.id,
            username=user_model.username,  # Get username from UserModel
            hand=hand,
            is_online=player_model.is_online,
            uno_declaration=player_model.uno_declaration,
            role=player_model.role
        )
    
    async def update_player(self, player: Player):
        hand_data = [card.dict() for card in player.hand]
        
        await self.db.execute(
            update(PlayerModel)
            .where(PlayerModel.id == player.id)
            .values(
                hand=hand_data,
                is_online=player.is_online,
                uno_declaration=player.uno_declaration
            )
        )
        await self.db.commit()
    
    async def create_player(self, player: Player, table_id: uuid.UUID, user_id: uuid.UUID):
    # Convert hand to JSON-serializable format
        hand_data = [card.dict() for card in player.hand]
        
        player_model = PlayerModel(
            id=player.id,
            user_id=user_id,  # Use the user_id instead of username
            table_id=table_id,
            hand=hand_data,
            is_online=player.is_online,
            uno_declaration=player.uno_declaration if hasattr(player, 'uno_declaration') else UnoDeclarationState.NOT_REQUIRED,
            role=player.role if hasattr(player, 'role') else PlayerRole.PLAYER
        )
        
        self.db.add(player_model)
        await self.db.commit()
    async def delete_player(self, player_id: uuid.UUID):
        await self.db.execute(
            delete(PlayerModel).where(PlayerModel.id == player_id)
        )
        await self.db.commit()