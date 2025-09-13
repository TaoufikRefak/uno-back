from typing import Dict, List, Optional
from app.models import Card, Player
from fastapi import WebSocket
import json
from app.session_manager import DBSessionManager as session_manager
import time
from app.websocket.connection_manager import manager

class EventHandler:
    @staticmethod
    async def broadcast_game_event(table_id: str, event_type: str, data: dict, exclude=None):
        event_message = {
            "type": event_type,
            "data": data,
            "timestamp": time.time()
        }
        await manager.broadcast_to_table(event_message, table_id, exclude=exclude)

# Specific event functions
async def broadcast_card_played(table_id: str, player_id: str, username: str, card, hand_count: int):
    await EventHandler.broadcast_game_event(
        table_id,
        "card_played",
        {
            "player_id": player_id,
            "player_name": username,
            "card": card.to_dict() if hasattr(card, 'to_dict') else card,
            "hand_count": hand_count
        }
    )

async def broadcast_card_drawn(table_id: str, player_id: str, username: str, count: int, hand_count: int):
    await EventHandler.broadcast_game_event(
        table_id,
        "card_drawn",
        {
            "player_id": player_id,
            "player_name": username,
            "count": count,
            "hand_count": hand_count
        }
    )

async def broadcast_turn_changed(table_id: str, player_id: str, username: str):
    await EventHandler.broadcast_game_event(
        table_id,
        "turn_changed",
        {
            "player_id": player_id,
            "player_name": username
        }
    )

async def broadcast_player_joined(table_id: str, player, hand_count: int):
    await EventHandler.broadcast_game_event(
        table_id,
        "player_joined",
        {
            "player_id": str(player.id),
            "username": player.username,
            "hand_count": hand_count,
            "is_online": player.is_online
        }
    )

async def broadcast_player_left(table_id: str, player_id: str, username: str):
    await EventHandler.broadcast_game_event(
        table_id,
        "player_left",
        {
            "player_id": player_id,
            "username": username
        }
    )

async def broadcast_uno_declared(table_id: str, player_id: str, username: str):
    await EventHandler.broadcast_game_event(
        table_id,
        "uno_declared",
        {
            "player_id": player_id,
            "player_name": username
        }
    )

async def broadcast_uno_penalty(table_id: str, target_player_id: str, target_player_name: str, challenger_id: str, challenger_name: str, cards_drawn: int):
    await EventHandler.broadcast_game_event(
        table_id,
        "uno_penalty",
        {
            "target_player_id": target_player_id,
            "target_player_name": target_player_name,
            "challenger_id": challenger_id,
            "challenger_name": challenger_name,
            "cards_drawn": cards_drawn
        }
    )

async def broadcast_uno_challenge_failed(table_id: str, challenger_id: str, challenger_name: str, cards_drawn: int):
    await EventHandler.broadcast_game_event(
        table_id,
        "uno_challenge_failed",
        {
            "challenger_id": challenger_id,
            "challenger_name": challenger_name,
            "cards_drawn": cards_drawn
        }
    )

async def broadcast_player_one_card(table_id: str, player_id: str, username: str):
    await EventHandler.broadcast_game_event(
        table_id,
        "player_one_card",
        {
            "player_id": player_id,
            "player_name": username
        }
    )