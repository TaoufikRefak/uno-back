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
        """Handle a player playing a card"""
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
            # Return the error instead of trying to send it directly
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
            len(player.hand)  # Pass the hand count here
        )
        
        # Handle special card effects
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
        await manager.send_to_player({
            "type": "your_hand",
            "data": [card.to_dict() for card in player.hand]
        }, str(player.id))

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
        """Handle special card effects"""
        result: Dict[str, Any] = {}
        
        if card.type == CardType.SKIP:
            # Skip the next player
            game_state.next_turn(table)  # Skip to next player
            result["skipped_turn"] = True
            result["message"] = "Next player was skipped!"

        elif card.type == CardType.REVERSE:
            # Reverse the game direction
            game_state.reverse_direction()
            result["direction_reversed"] = True
            result["message"] = "Game direction reversed!"

            # In 2-player game, reverse acts as a skip
            if len(table.players) == 2:
                game_state.next_turn(table)  # Skip the next player
                result["skipped_turn"] = True
                result["message"] = "Reverse card acts as skip in 2-player game!"

        elif card.type == CardType.DRAW_TWO:
            # Next player draws 2 cards
            next_player_idx = game_state.get_next_player_index(table)
            next_player = table.players[next_player_idx]
            drawn_cards = game_state.draw_cards_for_player(next_player, 2)
            result["next_player_drew"] = len(drawn_cards)
            result["message"] = "Next player drew 2 cards!"

        elif card.type == CardType.WILD_DRAW_FOUR:
            # Next player draws 4 cards
            next_player_idx = game_state.get_next_player_index(table)
            next_player = table.players[next_player_idx]
            drawn_cards = game_state.draw_cards_for_player(next_player, 4)
            result["next_player_drew"] = len(drawn_cards)
            result["message"] = "Next player drew 4 cards!"
            result["chosen_color"] = chosen_color.value if chosen_color else "unknown"

        # For all cards except reverse in >2 player game, advance to next turn
        if not (card.type == CardType.REVERSE and len(table.players) > 2):
            game_state.next_turn(table)

        # Broadcast turn changed - only once per action
        new_current_player = game_state.get_current_player(table)
        await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)

        return result
    

    @staticmethod
    async def handle_draw_card(
        table_id: str,
        player: Player,
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle a player drawing a card"""
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

        # Update database FIRST
        await table_repo.update_table(table)
        await game_state_repo.update_game_state(game_state)

        # Then broadcast events
        await broadcast_card_drawn(
            table_id, 
            str(player.id), 
            player.username, 
            len(drawn_cards),
            len(player.hand)
        )
        
        # Send the drawn card only to the player
        await manager.send_to_player({
            "type": "card_drawn",
            "data": {
                "cards": [card.to_dict() for card in drawn_cards],
                "new_hand_size": len(player.hand)
            }
        }, str(player.id))

        # Advance to next turn after drawing
        game_state.next_turn(table)
        
        # Broadcast turn changed
        new_current_player = game_state.get_current_player(table)
        await broadcast_turn_changed(str(table.id), str(new_current_player.id), new_current_player.username)
        
        # Update database again with new turn
        await game_state_repo.update_game_state(game_state)

        # Broadcast the updated game state to everyone
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": game_state.to_public_dict(table)
        }, str(table.id))

        return {"success": True, "drawn_count": len(drawn_cards)}
        
    


    @staticmethod
    async def handle_declare_uno(table_id: str, player: Player) -> Dict[str, Any]:
        """Handle a player declaring UNO"""
        from app.main import tables, game_states

        if table_id not in tables or table_id not in game_states:
            return {"success": False, "error": "Table or game state not found"}

        table = tables[table_id]
        game_state = game_states[table_id]

        # Check if player has exactly 1 card
        if len(player.hand) != 1:
            return {"success": False, "error": "Can only declare UNO with exactly 1 card"}

        # Set UNO declaration state
        player.uno_declaration = UnoDeclarationState.DECLARED

        # Broadcast UNO declaration
        await broadcast_uno_declared(table_id, str(player.id), player.username)

        return {"success": True}

    @staticmethod
    async def handle_challenge_uno(table_id: str, challenger: Player, target_player_id: str) -> Dict[str, Any]:
        """Handle a player challenging another player for not declaring UNO"""
        from app.main import tables, game_states

        if table_id not in tables or table_id not in game_states:
            return {"success": False, "error": "Table or game state not found"}

        table = tables[table_id]
        game_state = game_states[table_id]

        # Find the target player
        target_player = next((p for p in table.players if str(p.id) == target_player_id), None)
        if not target_player:
            return {"success": False, "error": "Target player not found"}

        # Check if target player has 1 card but didn't declare UNO
        if len(target_player.hand) == 1 and target_player.uno_declaration != UnoDeclarationState.DECLARED:
            # Penalize the target player - make them draw 2 cards
            drawn_cards = game_state.draw_cards_for_player(target_player, 2)
            target_player.uno_declaration = UnoDeclarationState.PENALIZED

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

            # Broadcast failed challenge
            await broadcast_uno_challenge_failed(
                table_id,
                str(challenger.id),
                challenger.username,
                len(drawn_cards)
            )

            return {"success": True, "penalty_applied": False, "cards_drawn": len(drawn_cards)}

    @staticmethod
    async def handle_start_game(
        table_id: str, 
        player: Player, 
        db: AsyncSession = Depends(get_db)
    ) -> Dict[str, Any]:
        """Handle starting a game"""
        table_repo = TableRepository(db)
        game_state_repo = GameStateRepository(db)
        player_repo = PlayerRepository(db)
        
        table = await table_repo.get_table(uuid.UUID(table_id))
        if not table:
            return {"success": False, "error": "Table not found"}

        # Check if player is in the table
        if not any(p.id == player.id for p in table.players):
            return {"success": False, "error": "Player not in table"}

        # Check if game is already in progress
        game_state = await game_state_repo.get_game_state(table.id)
        if game_state and game_state.status == GameStatus.IN_PROGRESS:
            return {"success": False, "error": "Game already in progress"}

        # Check if there are enough players (at least 2)
        if len(table.players) < 2:
            return {"success": False, "error": "Need at least 2 players to start"}

        # Initialize the game
        if not game_state:
            game_state = GameState(table_id=table.id)
            await game_state_repo.create_game_state(game_state)

        game_state.initialize_game(table)

        # Record last action
        game_state.last_action = {
            "type": "game_started",
            "timestamp": time.time()
        }

        # Update database
        await game_state_repo.update_game_state(game_state)
        await table_repo.update_table(table)

        # Broadcast the new game state to ALL players
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": game_state.to_public_dict(table)
        }, str(table.id))

        # Send each player their hand
        for p in table.players:
            await manager.send_to_player({
                "type": "your_hand",
                "data": [card.to_dict() for card in p.hand]
            }, str(p.id))

        # Broadcast turn changed for the first player
        first_player = game_state.get_current_player(table)
        await broadcast_turn_changed(table_id, str(first_player.id), first_player.username)

        return {"success": True}