from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.models import UserModel
from typing import Optional
import uuid

class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_username(self, username: str) -> Optional[UserModel]:
        result = await self.db.execute(
            select(UserModel).where(UserModel.username == username)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[UserModel]:
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        return result.scalar_one_or_none()