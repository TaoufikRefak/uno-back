from typing import Optional
from uuid import UUID
from app.repositories.session_repository import SessionRepository
from app.repositories.player_repository import PlayerRepository
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.database.database import get_db
from app.models import Player

class DBSessionManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = SessionRepository(db)
        self.player_repo = PlayerRepository(db)
    
    async def create_session(self, player: Player, table_id: str) -> str:
        return await self.session_repo.create_session(player, table_id)
    
    async def get_player_from_session(self, session_token: str) -> Optional[Player]:
        return await self.session_repo.get_player_from_session(session_token)
    
    async def get_table_from_session(self, session_token: str) -> Optional[str]:
        return await self.session_repo.get_table_from_session(session_token)
    
    async def remove_session(self, session_token: str):
        await self.session_repo.remove_session(session_token)
        

    async def update_player_online_status(self, player_id: UUID, is_online: bool):
        """Update a player's online status"""
        from app.repositories.player_repository import PlayerRepository
        player_repo = PlayerRepository(self.db)
        player = await player_repo.get_player(player_id)
        if player:
            player.is_online = is_online
            await player_repo.update_player(player)

# Factory function to get session manager
async def get_session_manager(db: AsyncSession = Depends(get_db)):
    return DBSessionManager(db)