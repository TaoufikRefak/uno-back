from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database.models import GameStateModel
from app.models import GameState, Card
from typing import Optional
import uuid

class GameStateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_game_state(self, table_id: uuid.UUID) -> Optional[GameState]:
        result = await self.db.execute(
            select(GameStateModel).where(GameStateModel.table_id == table_id)
        )
        game_state_model = result.scalar_one_or_none()
        
        if not game_state_model:
            return None
        
        # Convert database model to domain model
        return GameState(
            table_id=game_state_model.table_id,
            draw_pile=[Card(**card) for card in game_state_model.draw_pile],
            discard_pile=[Card(**card) for card in game_state_model.discard_pile],
            current_player_index=game_state_model.current_player_index,
            direction=game_state_model.direction,
            status=game_state_model.status,
            winner=game_state_model.winner,
            last_action=game_state_model.last_action
        )
    
    async def update_game_state(self, game_state: GameState):
        # Convert domain model to database model format
        draw_pile_data = [card.dict() for card in game_state.draw_pile]
        discard_pile_data = [card.dict() for card in game_state.discard_pile]
        
        await self.db.execute(
            update(GameStateModel)
            .where(GameStateModel.table_id == game_state.table_id)
            .values(
                draw_pile=draw_pile_data,
                discard_pile=discard_pile_data,
                current_player_index=game_state.current_player_index,
                direction=game_state.direction,
                status=game_state.status,
                winner=game_state.winner,
                last_action=game_state.last_action
            )
        )
        await self.db.commit()
    
    async def create_game_state(self, game_state: GameState):
        # Convert domain model to database model
        draw_pile_data = [card.dict() for card in game_state.draw_pile]
        discard_pile_data = [card.dict() for card in game_state.discard_pile]
        
        game_state_model = GameStateModel(
            table_id=game_state.table_id,
            draw_pile=draw_pile_data,
            discard_pile=discard_pile_data,
            current_player_index=game_state.current_player_index,
            direction=game_state.direction,
            status=game_state.status,
            winner=game_state.winner,
            last_action=game_state.last_action
        )
        
        self.db.add(game_state_model)
        await self.db.commit()