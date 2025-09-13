from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.database.models import TableModel, PlayerModel, GameStateModel
from app.models import PlayerRole, Table, Player, GameState, Card
from typing import List, Optional
import uuid
import time

class TableRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_table(self, name: str, max_players: int = 10) -> Table:
        table_id = uuid.uuid4()
        table_model = TableModel(
            id=table_id,
            name=name,
            max_players=max_players,
            created_at=time.time()
        )
        self.db.add(table_model)
        
        # Create empty game state
        game_state_model = GameStateModel(table_id=table_id)
        self.db.add(game_state_model)
        
        await self.db.commit()
        
        return Table(
            id=table_id,
            name=name,
            players=[],
            spectators=[],  # Initialize empty spectators list
            max_players=max_players,
            status=table_model.status,
            created_at=table_model.created_at
        )
    
    async def get_table(self, table_id: uuid.UUID) -> Optional[Table]:
        result = await self.db.execute(
            select(TableModel).where(TableModel.id == table_id)
        )
        table_model = result.scalar_one_or_none()
        
        if not table_model:
            return None
        
        # Get all players for this table
        result = await self.db.execute(
            select(PlayerModel).where(PlayerModel.table_id == table_id)
        )
        player_models = result.scalars().all()
        
        players = []
        spectators = []
        for player_model in player_models:
            hand = [Card(**card) for card in player_model.hand]
            player = Player(
                id=player_model.id,
                username=player_model.username,
                hand=hand,
                is_online=player_model.is_online,
                uno_declaration=player_model.uno_declaration,
                role=player_model.role  # Make sure to include role
            )
            
            # Separate players and spectators based on role
            if player_model.role == PlayerRole.SPECTATOR:
                spectators.append(player)
            else:
                players.append(player)
        
        return Table(
            id=table_model.id,
            name=table_model.name,
            players=players,
            spectators=spectators,  # Include spectators
            max_players=table_model.max_players,
            status=table_model.status,
            created_at=table_model.created_at
        )
    
    async def update_table(self, table: Table):
        # Update table metadata
        await self.db.execute(
            update(TableModel)
            .where(TableModel.id == table.id)
            .values(
                status=table.status,
                max_players=table.max_players
            )
        )
        
        # Update players (both regular players and spectators)
        for player in table.players + table.spectators:
            hand_data = [card.dict() for card in player.hand]
            await self.db.execute(
                update(PlayerModel)
                .where(PlayerModel.id == player.id)
                .values(
                    hand=hand_data,
                    is_online=player.is_online,
                    uno_declaration=player.uno_declaration,
                    role=player.role  # Update role as well
                )
            )
        
        await self.db.commit()
    
    async def delete_table(self, table_id: uuid.UUID):
        await self.db.execute(
            delete(TableModel).where(TableModel.id == table_id)
        )
        await self.db.commit()
    async def get_all_tables(self) -> List[Table]:
        result = await self.db.execute(select(TableModel))
        table_models = result.scalars().all()

        tables: List[Table] = []
        for table_model in table_models:
            # Fetch players for this table
            result = await self.db.execute(
                select(PlayerModel).where(PlayerModel.table_id == table_model.id)
            )
            player_models = result.scalars().all()

            players = [
                Player(
                    id=player.id,
                    username=player.username,
                    hand=[Card(**card) for card in player.hand],
                    is_online=player.is_online,
                    uno_declaration=player.uno_declaration,
                )
                for player in player_models
            ]

            tables.append(
                Table(
                    id=table_model.id,
                    name=table_model.name,
                    players=players,
                    max_players=table_model.max_players,
                    status=table_model.status,
                    created_at=table_model.created_at,
                )
            )

        return tables

    
    async def list_tables(self) -> List[dict]:
        result = await self.db.execute(select(TableModel))
        table_models = result.scalars().all()
        
        tables = []
        for table_model in table_models:
            # Get player count
            result = await self.db.execute(
                select(PlayerModel).where(PlayerModel.table_id == table_model.id)
            )
            player_count = len(result.scalars().all())
            
            tables.append({
                "id": str(table_model.id),
                "name": table_model.name,
                "player_count": player_count,
                "max_players": table_model.max_players,
                "status": table_model.status.value
            })
        
        return tables