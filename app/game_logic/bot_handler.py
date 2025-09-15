import asyncio
import random
import traceback # <-- Add this import for detailed error logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.game_logic.bot_player import BotPlayer
from app.repositories.player_repository import PlayerRepository
from app.repositories.table_repository import TableRepository
from app.repositories.game_state_repository import GameStateRepository
from app.database.database import get_db_session_for_task # <-- IMPORT the new context manager
from app.schemas import  GameStatus
async def check_and_handle_bot_turn(table_id: str):
    """
    Checks if the current player is a bot. If so, initiates its turn.
    """
    # Import locally to prevent circular dependency
    from app.game_logic.game_actions import GameActionHandler

    # --- WRAP THE ENTIRE LOGIC IN A TRY/EXCEPT BLOCK ---
    async with get_db_session_for_task() as db:
        try:
            table_repo = TableRepository(db)
            game_state_repo = GameStateRepository(db)

            table = await table_repo.get_table(UUID(table_id))
            game_state = await game_state_repo.get_game_state(UUID(table_id))

            if not game_state or game_state.status != GameStatus.IN_PROGRESS:
                print(f"BOT HANDLER: Aborting for table {table_id}. Game is not in progress.")
                return
            
            if not table or not table.players:
                print(f"BOT HANDLER: Aborting for table {table_id}. No table, game state, or players found.")
                return

            current_player = game_state.get_current_player(table)
            if not current_player:
                print(f"BOT HANDLER: Aborting for table {table_id}. Could not determine current player.")
                return
                
            if not current_player.is_bot:
                # This is the expected outcome for human players, so no print needed.
                return

            print(f"BOT ACTION: It is bot '{current_player.username}'s turn.")
            
            await asyncio.sleep(random.uniform(1.5, 3.0))

            bot_agent = BotPlayer(current_player, game_state, table)
            decision = bot_agent.decide_action()
            
            action_type = decision.get("action")
            print(f"BOT ACTION: Bot '{current_player.username}' decided to '{action_type}'.")

            if action_type == "play_card":
                await GameActionHandler.handle_play_card(
                    table_id,
                    current_player,
                    decision["card_index"],
                    decision.get("chosen_color"),
                    db
                )
                if decision.get("declare_uno"):
                    await asyncio.sleep(0.5)
                    await GameActionHandler.handle_declare_uno(table_id, current_player, db)

            elif action_type == "draw_card":
                await GameActionHandler.handle_draw_card(
                    table_id,
                    current_player,
                    db
                )
                
            print(f"BOT HANDLER: Successfully completed action for '{current_player.username}'.")

        except Exception as e:
            print("\n--- BOT HANDLER EXCEPTION ---")
            print(f"An error occurred while handling bot turn for table {table_id}: {e}")
            traceback.print_exc()
            print("---------------------------\n")