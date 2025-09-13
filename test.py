# Test cases for is_playable_on method
from app.models import Card, CardColor, CardType


def test_card_validation():
    # Test cases for number cards
    red5 = Card(color=CardColor.RED, type=CardType.NUMBER, value=5)
    red7 = Card(color=CardColor.RED, type=CardType.NUMBER, value=7)
    blue5 = Card(color=CardColor.BLUE, type=CardType.NUMBER, value=5)
    blue7 = Card(color=CardColor.BLUE, type=CardType.NUMBER, value=7)
    
    # Same color, different numbers - should be playable
    assert red7.is_playable_on(red5) == True, "Same color cards should be playable"
    
    # Different color, same number - should be playable
    assert blue5.is_playable_on(red5) == True, "Same value cards should be playable"
    
    # Different color, different number - should NOT be playable
    assert blue7.is_playable_on(red5) == False, "Different color and value cards should not be playable"
    
    # Test cases for action cards
    red_skip = Card(color=CardColor.RED, type=CardType.SKIP)
    blue_skip = Card(color=CardColor.BLUE, type=CardType.SKIP)
    red_reverse = Card(color=CardColor.RED, type=CardType.REVERSE)
    
    # Same type action cards - should be playable
    assert blue_skip.is_playable_on(red_skip) == True, "Same type action cards should be playable"
    
    # Different type action cards - should NOT be playable
    assert red_reverse.is_playable_on(red_skip) == False, "Different type action cards should not be playable"
    
    # Action card on number card of same color - should be playable
    assert red_skip.is_playable_on(red5) == True, "Action card on same color number card should be playable"
    
    # Wild card on anything - should be playable
    wild = Card(color=CardColor.WILD, type=CardType.WILD)
    assert wild.is_playable_on(red5) == True, "Wild cards should be playable on anything"
    
    print("All tests passed!")

# Run the tests
test_card_validation()