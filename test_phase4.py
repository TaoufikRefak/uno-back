import requests
import websockets
import asyncio
import json

BASE_URL = "http://localhost:8000"


def test_game_setup():
    # Create a table
    response = requests.post(
        f"{BASE_URL}/tables", params={"name": "Game Test Table", "max_players": 4}
    )
    table_data = response.json()
    print("Created table:", table_data)

    # Join two players
    players = []
    for i in range(2):
        response = requests.post(
            f"{BASE_URL}/tables/{table_data['table_id']}/join",
            params={"username": f"Player {i+1}"},
        )
        join_data = response.json()
        players.append(join_data)
        print(f"Player {i+1} joined:", join_data)

    return table_data, players


async def drain_messages(ws, label, max_count=5, timeout=1):
    """Read up to max_count messages with a timeout per message."""
    for _ in range(max_count):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
            print(f"{label}: {msg}")
        except asyncio.TimeoutError:
            break


async def test_game_actions(table_id, players):
    try:
        async with websockets.connect(
            f"ws://localhost:8000/ws/table/{table_id}?session_token={players[0]['session_token']}"
        ) as ws1, websockets.connect(
            f"ws://localhost:8000/ws/table/{table_id}?session_token={players[1]['session_token']}"
        ) as ws2:
            print("✅ Both players connected")

            # Drain initial messages
            await drain_messages(ws1, "P1 init")
            await drain_messages(ws2, "P2 init")

            # Player 1 starts the game
            await ws1.send(json.dumps({"type": "start_game"}))
            await drain_messages(ws1, "P1 after start")
            await drain_messages(ws2, "P2 after start")

            # Player 1 draws a card
            await ws1.send(json.dumps({"type": "draw_card"}))
            await drain_messages(ws1, "P1 after draw")
            await drain_messages(ws2, "P2 sees draw")

            # Player 1 declares UNO
            await ws1.send(json.dumps({"type": "declare_uno"}))
            await drain_messages(ws1, "P1 declare")
            await drain_messages(ws2, "P2 sees declare")

            # Player 2 challenges Player 1
            await ws2.send(
                json.dumps(
                    {"type": "challenge_uno", "target_player_id": players[0]["player_id"]}
                )
            )
            await drain_messages(ws2, "P2 challenge")
            await drain_messages(ws1, "P1 sees challenge")

    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")


if __name__ == "__main__":
    table_data, players = test_game_setup()
    asyncio.run(test_game_actions(table_data["table_id"], players))
