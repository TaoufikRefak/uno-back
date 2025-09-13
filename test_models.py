from app.models import Card, CardColor, CardType, CardDeck, Player, Table, GameState

# Test card creation
def test_cards():
    red_five = Card(color=CardColor.RED, type=CardType.NUMBER, value=5)
    wild_card = Card(color=CardColor.WILD, type=CardType.WILD)
    
    print(f"Red five: {red_five}")
    print(f"Wild card: {wild_card}")
    
    # Test playability
    blue_five = Card(color=CardColor.BLUE, type=CardType.NUMBER, value=5)
    print(f"Can play blue five on red five: {blue_five.is_playable_on(red_five)}")
    
    green_skip = Card(color=CardColor.GREEN, type=CardType.SKIP)
    print(f"Can play green skip on red five: {green_skip.is_playable_on(red_five)}")

# Test deck creation
def test_deck():
    deck = CardDeck.create_deck()
    print(f"Deck has {len(deck)} cards")
    
    shuffled = CardDeck.shuffle(deck)
    print("Deck shuffled")
    
    drawn, remaining = CardDeck.draw_cards(shuffled, 7)
    print(f"Drew {len(drawn)} cards, {len(remaining)} remaining")

# Test player and table
def test_player_table():
    player = Player(username="test_user")
    print(f"Player: {player.username}, ID: {player.id}")
    
    table = Table(name="Test Table")
    table.add_player(player)
    print(f"Table: {table.name}, Players: {len(table.players)}")

if __name__ == "__main__":
    test_cards()
    test_deck()
    test_player_table()