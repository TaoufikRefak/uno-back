import random
from typing import List, Optional, Dict, Any
from app.models import Player, Card, CardColor, GameState, Table, CardType

class BotPlayer:
    """
    Handles the decision-making logic for a bot player.
    """
    def __init__(self, bot_player: Player, game_state: GameState, table: Table):
        self.bot = bot_player
        self.game_state = game_state
        self.table = table

    def choose_card_to_play(self) -> Optional[Dict[str, Any]]:
        """
        Determines which card to play.
        Returns a dictionary with card_index and chosen_color if applicable.
        """
        top_card = self.game_state.get_top_discard_card()
        if not top_card:
            return None # Should not happen in a real game

        for i, card in enumerate(self.bot.hand):
            if card.is_playable_on(top_card):
                action = {"card_index": i}
                # If it's a wild card, choose a color
                if card.type in [CardType.WILD, CardType.WILD_DRAW_FOUR]:
                    action["chosen_color"] = self._choose_best_color()
                return action
        
        return None # No playable card found

    def _choose_best_color(self) -> CardColor:
        """
        A simple strategy for choosing a color for a wild card:
        Pick the color the bot has the most of in its hand (excluding wild).
        """
        color_counts = {color: 0 for color in [CardColor.RED, CardColor.BLUE, CardColor.GREEN, CardColor.YELLOW]}
        for card in self.bot.hand:
            if card.color in color_counts:
                color_counts[card.color] += 1
        
        # If no colors, pick one at random
        if not any(color_counts.values()):
            return random.choice(list(color_counts.keys()))
            
        # Return the color with the highest count
        return max(color_counts, key=color_counts.get)

    def decide_action(self) -> Dict[str, Any]:
        """
        Main decision function. Decides whether to play a card or draw.
        """
        playable_action = self.choose_card_to_play()

        # If bot has one card left and can play it, it should also declare uno
        if playable_action and len(self.bot.hand) == 2:
             playable_action["declare_uno"] = True

        if playable_action:
            return {"action": "play_card", **playable_action}
        else:
            return {"action": "draw_card"}