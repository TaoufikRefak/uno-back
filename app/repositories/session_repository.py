from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.database.models import SessionModel
from app.models import Player
from typing import Optional
import uuid
import time

class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_session(self, player: Player, table_id: str) -> str:
        session_token = str(uuid.uuid4())
        session_model = SessionModel(
            session_token=session_token,
            player_id=player.id,
            table_id=uuid.UUID(table_id),
            created_at=time.time()
        )
        
        self.db.add(session_model)
        await self.db.commit()
        return session_token
    
    async def get_player_from_session(self, session_token: str) -> Optional[Player]:
        result = await self.db.execute(
            select(SessionModel).where(SessionModel.session_token == session_token)
        )
        session_model = result.scalar_one_or_none()
        
        if not session_model:
            return None
        
        # Get player from player repository
        from app.repositories.player_repository import PlayerRepository
        player_repo = PlayerRepository(self.db)
        return await player_repo.get_player(session_model.player_id)
    
    async def get_table_from_session(self, session_token: str) -> Optional[str]:
        result = await self.db.execute(
            select(SessionModel).where(SessionModel.session_token == session_token)
        )
        session_model = result.scalar_one_or_none()
        
        if not session_model:
            return None
        
        return str(session_model.table_id)
    
    async def remove_session(self, session_token: str):
        await self.db.execute(
            delete(SessionModel).where(SessionModel.session_token == session_token)
        )
        await self.db.commit()