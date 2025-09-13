from typing import Dict, Any, Optional
import uuid
from app.database.database import get_db
from app.repositories.game_state_repository import GameStateRepository
from app.repositories.player_repository import PlayerRepository
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import GameState, Table, Player, Card, CardColor, GameStatus, UnoDeclarationState, CardType
from app.websocket.connection_manager import manager
from app.session_manager import DBSessionManager as session_manager
from app.websocket.event_handler import (
    broadcast_card_played,
    broadcast_card_drawn,
    broadcast_turn_changed,
    broadcast_uno_declared,
    broadcast_uno_penalty,
    broadcast_uno_challenge_failed,
    broadcast_player_one_card
)
import time
from app.session_manager import DBSessionManager


from app.repositories.table_repository import TableRepository

class GameActionHandler:
    @staticmethod
    async def handle_play_card(
        table_id: str,
        player: Player,
        card_index: int,
        chosen_color: Optional[CardColor] = None,
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle a player playing a card - FIXED VERSION"""
        table_repo = TableRepository(db)
        game_state_repo = GameStateRepository(db)
        player_repo = PlayerRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
        
        if not table or not game_state:
            return {"success": False, "error": "Table or game state not found"}
        
        # Find the player in the table's player list
        table_player = next((p for p in table.players if p.id == player.id), None)
        if not table_player:
            return {"success": False, "error": "Player not found in table"}
        
        # Use the table_player instance instead of the session player
        player = table_player

        # Verify it's the player's turn
        current_player = game_state.get_current_player(table)
        if current_player.id != player.id:
            return {"success": False, "error": "Not your turn"}

        # Verify the card index is valid
        if card_index < 0 or card_index >= len(player.hand):
            return {"success": False, "error": "Invalid card index"}

        card_to_play: Card = player.hand[card_index]
        top_card = game_state.get_top_discard_card()

        # Verify the card can be played
        if not top_card:
            # First card of the game - any card can be played
            pass
        elif not card_to_play.is_playable_on(top_card):
            return {"success": False, "error": f"Cannot play {card_to_play} on {top_card}"}            

        # Handle wild card color choice (must provide chosen_color for wilds)
        if card_to_play.type in (CardType.WILD, CardType.WILD_DRAW_FOUR) and not chosen_color:
            return {"success": False, "error": "Wild card requires color choice"}

        # Play the card
        played_card = player.play_card(card_index)
        if not played_card:
            return {"success": False, "error": "Failed to play card"}

        # For wild cards, set the chosen color
        if played_card.type in (CardType.WILD, CardType.WILD_DRAW_FOUR) and chosen_color:
            played_card.color = chosen_color

        # Add to discard pile
        game_state.discard_pile.append(played_card)

        # Reset UNO declaration state after playing
        player.uno_declaration = UnoDeclarationState.NOT_REQUIRED

        # Broadcast card played event
        await broadcast_card_played(
            table_id, 
            str(player.id), 
            player.username, 
            played_card,
            len(player.hand)
        )
        
        # ========== KEY FIX: Handle special card effects properly ==========
        action_result = await GameActionHandler._handle_special_card(
            table, game_state, played_card, chosen_color
        )

        # Check if player has won
        if len(player.hand) == 0:
            game_state.winner = player.id
            game_state.status = GameStatus.COMPLETED
            action_result["game_ended"] = True
            action_result["winner"] = str(player.id)
            action_result["message"] = f"{player.username} wins the game!"
            
            # Broadcast game over message
            await manager.broadcast_to_table({
                "type": "game_over",
                "data": {
                    "winner_id": str(player.id),
                    "winner_name": player.username,
                    "message": f"{player.username} wins the game!"
                }
            }, str(table.id))

        # If player now has exactly 1 card, set PENDING (they must declare UNO)
        elif len(player.hand) == 1 and game_state.status != GameStatus.COMPLETED:
            player.uno_declaration = UnoDeclarationState.PENDING
            await broadcast_player_one_card(table_id, str(player.id), player.username)

        # ========== CRITICAL FIX: Only advance turn if not handled by special card ==========
        if (game_state.status != GameStatus.COMPLETED and 
            not action_result.get("turn_already_advanced", False)):
            
            game_state.next_turn(table)
            
            # Broadcast turn changed - only once per action
            new_current_player = game_state.get_current_player(table)
            await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)

        # Record last action
        game_state.last_action = {
            "type": "card_played",
            "player_id": str(player.id),
            "card": played_card.to_dict() if hasattr(played_card, "to_dict") else str(played_card),
            "timestamp": time.time()
        }

        # Update database - table first, then game state
        await table_repo.update_table(table)
        await game_state_repo.update_game_state(game_state)

        # Send the player's updated hand personally
        session_mgr = DBSessionManager(db)
        await manager.send_to_player({
            "type": "your_hand",
            "data": [card.to_dict() for card in player.hand]
        }, str(player.id), session_mgr)  # Add session_mgr here

        # Broadcast the updated game state
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": game_state.to_public_dict(table)
        }, str(table.id))

        return {"success": True, **action_result}

    @staticmethod
    async def _handle_special_card(
        table: Table,
        game_state: GameState,
        card: Card,
        chosen_color: Optional[CardColor] = None
    ) -> Dict[str, Any]:
        """Handle special card effects - COMPLETELY FIXED VERSION"""
        result: Dict[str, Any] = {"turn_already_advanced": False}
        
        if card.type == CardType.SKIP:
            # Skip the next player - advance twice total
            game_state.next_turn(table)  # Move to next player (who gets skipped)
            game_state.next_turn(table)  # Move to the player after the skipped one
            
            result["skipped_turn"] = True
            result["message"] = "Next player was skipped!"
            result["turn_already_advanced"] = True
            
            # Broadcast the turn change here since we handled it
            new_current_player = game_state.get_current_player(table)
            await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)

        elif card.type == CardType.REVERSE:
            # Reverse the game direction
            game_state.reverse_direction()
            result["direction_reversed"] = True
            
            if len(table.players) == 2:
                # In 2-player game, reverse acts like skip
                game_state.next_turn(table)  # Skip the other player
                result["skipped_turn"] = True
                result["message"] = "Reverse card acts as skip in 2-player game!"
                result["turn_already_advanced"] = True
                
                # Broadcast the turn change here since we handled it
                new_current_player = game_state.get_current_player(table)
                await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)
            else:
                # In >2 player game, just reverse direction - normal turn advance will happen
                result["message"] = "Game direction reversed!"
                result["turn_already_advanced"] = False

        elif card.type == CardType.DRAW_TWO:
            # Next player draws 2 cards and loses their turn
            next_player_idx = game_state.get_next_player_index(table)
            next_player = table.players[next_player_idx]
            drawn_cards = game_state.draw_cards_for_player(next_player, 2)
            
            # Skip the next player's turn (they drew cards, so they lose turn)
            game_state.next_turn(table)  # Move to next player (who drew cards)
            game_state.next_turn(table)  # Move to the player after them
            
            result["next_player_drew"] = len(drawn_cards)
            result["message"] = f"Next player drew 2 cards and lost their turn!"
            result["turn_already_advanced"] = True
            
            # Broadcast the turn change here since we handled it
            new_current_player = game_state.get_current_player(table)
            await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)

        elif card.type == CardType.WILD_DRAW_FOUR:
            # Next player draws 4 cards and loses their turn
            next_player_idx = game_state.get_next_player_index(table)
            next_player = table.players[next_player_idx]
            drawn_cards = game_state.draw_cards_for_player(next_player, 4)
            
            # Skip the next player's turn (they drew cards, so they lose turn)
            game_state.next_turn(table)  # Move to next player (who drew cards)
            game_state.next_turn(table)  # Move to the player after them
            
            result["next_player_drew"] = len(drawn_cards)
            result["message"] = f"Next player drew 4 cards and lost their turn!"
            result["chosen_color"] = chosen_color.value if chosen_color else "unknown"
            result["turn_already_advanced"] = True
            
            # Broadcast the turn change here since we handled it
            new_current_player = game_state.get_current_player(table)
            await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)

        # For regular number cards and wild cards (no special effect), 
        # turn_already_advanced remains False so normal turn advance happens

        return result
    
    @staticmethod
    async def handle_draw_card(
        table_id: str,
        player: Player,
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle a player drawing a card - FIXED VERSION"""
        table_repo = TableRepository(db)
        game_state_repo = GameStateRepository(db)
        player_repo = PlayerRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
        
        if not table or not game_state:
            return {"success": False, "error": "Table or game state not found"}
        
        # Find the player in the table's player list
        table_player = next((p for p in table.players if p.id == player.id), None)
        if not table_player:
            return {"success": False, "error": "Player not found in table"}
        
        # Use the table_player instance instead of the session player
        player = table_player
        
        # Verify it's the player's turn
        current_player = game_state.get_current_player(table)
        if current_player.id != player.id:
            return {"success": False, "error": "Not your turn"}

        # Draw a card
        drawn_cards = game_state.draw_cards_for_player(player, 1)
        if not drawn_cards:
            return {"success": False, "error": "No cards to draw"}

        # Broadcast card drawn event
        await broadcast_card_drawn(
            table_id, 
            str(player.id), 
            player.username, 
            len(drawn_cards),
            len(player.hand)
        )
        
        # Send the drawn card only to the player
        session_mgr = DBSessionManager(db)
        await manager.send_to_player({
            "type": "card_drawn",
            "data": {
                "cards": [card.to_dict() for card in drawn_cards],
                "new_hand_size": len(player.hand)
            }
        }, str(player.id), session_mgr)  # Add session_mgr here

        # ========== KEY FIX: Always advance turn after drawing ==========
        game_state.next_turn(table)
        
        # Broadcast turn changed
        new_current_player = game_state.get_current_player(table)
        await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)
        
        # Update database with all changes
        await table_repo.update_table(table)
        await game_state_repo.update_game_state(game_state)

        # Broadcast the updated game state to everyone
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": game_state.to_public_dict(table)
        }, str(table.id))

        return {"success": True, "drawn_count": len(drawn_cards)}

    @staticmethod
    async def handle_declare_uno(
        table_id: str, 
        player: Player,
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle a player declaring UNO - FIXED VERSION"""
        table_repo = TableRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        if not table:
            return {"success": False, "error": "Table not found"}

        # Find the player in the table's player list
        table_player = next((p for p in table.players if p.id == player.id), None)
        if not table_player:
            return {"success": False, "error": "Player not found in table"}
        
        player = table_player

        # Check if player has exactly 1 card
        if len(player.hand) != 1:
            return {"success": False, "error": "Can only declare UNO with exactly 1 card"}

        # Set UNO declaration state
        player.uno_declaration = UnoDeclarationState.DECLARED

        # Update database
        await table_repo.update_table(table)

        # Broadcast UNO declaration
        await broadcast_uno_declared(table_id, str(player.id), player.username)

        return {"success": True}

    @staticmethod
    async def handle_challenge_uno(
        table_id: str, 
        challenger: Player, 
        target_player_id: str,
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle a player challenging another player for not declaring UNO - FIXED VERSION"""
        table_repo = TableRepository(db)
        game_state_repo = GameStateRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
        
        if not table or not game_state:
            return {"success": False, "error": "Table or game state not found"}

        # Find the target player
        target_player = next((p for p in table.players if str(p.id) == target_player_id), None)
        if not target_player:
            return {"success": False, "error": "Target player not found"}

        # Find the challenger in the table
        table_challenger = next((p for p in table.players if p.id == challenger.id), None)
        if not table_challenger:
            return {"success": False, "error": "Challenger not found in table"}
        
        challenger = table_challenger

        # Check if target player has 1 card but didn't declare UNO
        if len(target_player.hand) == 1 and target_player.uno_declaration != UnoDeclarationState.DECLARED:
            # Penalize the target player - make them draw 2 cards
            drawn_cards = game_state.draw_cards_for_player(target_player, 2)
            target_player.uno_declaration = UnoDeclarationState.PENALIZED

            # Update database
            await table_repo.update_table(table)
            await game_state_repo.update_game_state(game_state)

            # Broadcast the penalty
            await broadcast_uno_penalty(
                table_id, 
                str(target_player.id), 
                target_player.username,
                str(challenger.id),
                challenger.username,
                len(drawn_cards)
            )

            return {"success": True, "penalty_applied": True, "cards_drawn": len(drawn_cards)}
        else:
            # Challenge failed - challenger draws 2 cards
            drawn_cards = game_state.draw_cards_for_player(challenger, 2)

            # Update database
            await table_repo.update_table(table)
            await game_state_repo.update_game_state(game_state)

            # Broadcast failed challenge
            await broadcast_uno_challenge_failed(
                table_id,
                str(challenger.id),
                challenger.username,
                len(drawn_cards)
            )

            return {"success": True, "penalty_applied": False, "cards_drawn": len(drawn_cards)}

    # Add this to your handle_start_game function to debug the issue

    @staticmethod
    async def handle_start_game(
        table_id: str, 
        player: Player, 
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle starting a game - DEBUG VERSION"""
        print(f"\n=== GAME START DEBUG ===")
        print(f"Table ID: {table_id}")
        print(f"Starting player: {player.username} ({str(player.id)[:8]}...)")
        
        table_repo = TableRepository(db)
        game_state_repo = GameStateRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        if not table:
            print(f"ERROR: Table not found")
            return {"success": False, "error": "Table not found"}

        print(f"Table found with {len(table.players)} players:")
        for i, p in enumerate(table.players):
            print(f"  Player {i}: {p.username} ({str(p.id)[:8]}...)")

        # Check if player is in the table
        if not any(p.id == player.id for p in table.players):
            print(f"ERROR: Player not in table")
            return {"success": False, "error": "Player not in table"}

        # Check if game is already in progress
        game_state = await game_state_repo.get_game_state(table.id)
        if game_state and game_state.status == GameStatus.IN_PROGRESS:
            print(f"ERROR: Game already in progress, current player: {game_state.current_player_index}")
            current_player = game_state.get_current_player(table)
            if current_player:
                print(f"Current player is: {current_player.username}")
            return {"success": False, "error": "Game already in progress"}

        # Check if there are enough players (at least 2)
        if len(table.players) < 2:
            print(f"ERROR: Not enough players ({len(table.players)})")
            return {"success": False, "error": "Need at least 2 players to start"}

        # Initialize the game
        if not game_state:
            print("Creating new game state...")
            game_state = GameState(table_id=table.id)
            await game_state_repo.create_game_state(game_state)
        else:
            print("Using existing game state...")

        print(f"BEFORE initialization:")
        print(f"  - Current player index: {game_state.current_player_index}")
        print(f"  - Game status: {game_state.status}")
        print(f"  - Draw pile size: {len(game_state.draw_pile)}")
        print(f"  - Discard pile size: {len(game_state.discard_pile)}")
        
        # Initialize the game
        print("Initializing game...")
        game_state.initialize_game(table)
        
        print(f"AFTER initialization:")
        print(f"  - Current player index: {game_state.current_player_index}")
        print(f"  - Game status: {game_state.status}")
        print(f"  - Draw pile size: {len(game_state.draw_pile)}")
        print(f"  - Discard pile size: {len(game_state.discard_pile)}")
        
        # FORCE set to player 0 and verify
        print("Forcing current player to index 0...")
        game_state.current_player_index = 0
        
        current_player = game_state.get_current_player(table)
        if current_player:
            print(f"Current player set to: {current_player.username} ({str(current_player.id)[:8]}...)")
        else:
            print("ERROR: Could not get current player!")
            return {"success": False, "error": "Failed to set current player"}

        # Record last action
        game_state.last_action = {
            "type": "game_started",
            "timestamp": time.time()
        }

        print("Updating database...")
        try:
            await game_state_repo.update_game_state(game_state)
            await table_repo.update_table(table)
            print("Database updated successfully")
        except Exception as e:
            print(f"ERROR updating database: {e}")
            return {"success": False, "error": "Database update failed"}

        # Verify game state after database update
        print("Verifying final state...")
        fresh_game_state = await game_state_repo.get_game_state(table.id)
        if fresh_game_state:
            print(f"VERIFIED: Current player index in DB: {fresh_game_state.current_player_index}")
            verified_player = fresh_game_state.get_current_player(table)
            if verified_player:
                print(f"VERIFIED: Current player in DB: {verified_player.username}")
        
        print("Broadcasting game state...")
        public_state = game_state.to_public_dict(table)
        print(f"Public state current player ID: {public_state.get('current_player_id')}")
        
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": public_state
        }, str(table.id))

        print("Sending hands to players...")
# Create a session manager instance
        session_mgr = DBSessionManager(db)
        for i, p in enumerate(table.players):
            hand_size = len(p.hand)
            print(f"  Sending {hand_size} cards to {p.username}")
            await manager.send_to_player({
                "type": "your_hand",
                "data": [card.to_dict() for card in p.hand]
            }, str(p.id), session_mgr)  # Add session_mgr parameter here

        # Broadcast turn for the current player - ONLY ONCE
        print("Broadcasting initial turn...")
        current_player = game_state.get_current_player(table)
        if current_player:
            print(f"Broadcasting turn to: {current_player.username} ({str(current_player.id)[:8]}...)")
            await broadcast_turn_changed(table_id, str(current_player.id), current_player.username)
        else:
            print("ERROR: No current player to broadcast turn to!")

        print(f"=== GAME START COMPLETE ===")
        print(f"Final current player: {current_player.username if current_player else 'NONE'}")
        print(f"Final game status: {game_state.status}")
        print(f"Final current player index: {game_state.current_player_index}\n")

        return {"success": True}