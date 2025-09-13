import requests
import websockets
import asyncio
import json
import time

BASE_URL = "http://localhost:8000"

def test_game_setup():
    # Create a table
    response = requests.post(f"{BASE_URL}/tables", params={"name": "Game Test Table", "max_players": 4})
    table_data = response.json()
    print("Created table:", table_data)
    
    # Join two players
    players = []
    for i in range(2):
        response = requests.post(
            f"{BASE_URL}/tables/{table_data['table_id']}/join", 
            params={"username": f"Player {i+1}"}
        )
        join_data = response.json()
        players.append(join_data)
        print(f"Player {i+1} joined:", join_data)
    
    return table_data, players

async def test_game_actions(table_id, session_token):
    try:
        async with websockets.connect(f"ws://localhost:8000/ws/table/{table_id}?session_token={session_token}") as websocket:
            print("Connected to table WebSocket")
            
            # Listen for initial messages
            initial_message = await websocket.recv()
            print("Initial message:", initial_message)
            
            # Send a ping to check connection
            await websocket.send(json.dumps({"type": "ping"}))
            ping_response = await websocket.recv()
            print("Ping response:", ping_response)
            
            # Start the game
            await websocket.send(json.dumps({"type": "start_game"}))
            
            # Wait for responses
            for _ in range(3):  # Expect multiple responses
                response = await websocket.recv()
                print("Response:", response)
                
                data = json.loads(response)
                if data.get("type") == "game_state" and data["data"]["status"] == "in_progress":
                    print("Game started successfully!")
                    break
                    
    except Exception as e:
        print(f"WebSocket connection failed: {e}")

if __name__ == "__main__":
    # Test game setup
    table_data, players = test_game_setup()
    
    # Test starting the game with the first player
    asyncio.run(test_game_actions(table_data["table_id"], players[0]["session_token"]))