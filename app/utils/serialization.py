from typing import Dict
from app.models import Player


from app.models import GameState, Table



def player_to_public_dict(player: Player) -> Dict:
    return {
        "id": str(player.id),
        "username": player.username,
        "hand_count": len(player.hand),
        "is_online": player.is_online,
        "has_played_this_turn": getattr(player, "has_played_this_turn", False),
        "uno_declaration": player.uno_declaration.value
    }

def card_to_dict(card) -> dict:
    return {
        "type": card.type.value if hasattr(card.type, 'value') else card.type,
        "color": card.color.value if hasattr(card.color, 'value') else str(card.color),
        "value": getattr(card, "value", None) # Changed "number" to "value"
    }

def card_to_str(card) -> str:
    if card.type in ["wild", "wild_draw_four"]:
        return card.type.capitalize()
    elif card.type in ["number", "skip", "reverse", "draw_two"]:
        return f"{card.color.value if hasattr(card.color, 'value') else str(card.color)} {getattr(card, 'number', '')}{card.type if card.type != 'number' else ''}"
    return str(card)

def game_state_to_public_dict(game_state: GameState, table: Table) -> dict:
    return {
        "table_id": str(game_state.table_id),
        "status": game_state.status.value,
        "current_player_id": str(game_state.get_current_player(table).id),
        "direction": game_state.direction,
        "discard_pile": [card_to_dict(card) for card in game_state.discard_pile],
        "last_action": game_state.last_action or {},
        "winner": str(game_state.winner) if game_state.winner else None,
        "players": [player_to_public_dict(p) for p in table.players]
    }
