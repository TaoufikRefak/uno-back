import requests
import websockets
import asyncio
import json

BASE_URL = "http://localhost:8000"

def test_table_management():
    # Create a table
    response = requests.post(f"{BASE_URL}/tables", params={"name": "Test Table", "max_players": 4})
    table_data = response.json()
    print("Created table:", table_data)
    
    # List tables
    response = requests.get(f"{BASE_URL}/tables")
    tables = response.json()
    print("Available tables:", tables)
    
    # Join the table
    response = requests.post(
        f"{BASE_URL}/tables/{table_data['table_id']}/join", 
        params={"username": "Test Player"}
    )
    join_data = response.json()
    print("Joined table:", join_data)
    
    # Get table details
    response = requests.get(f"{BASE_URL}/tables/{table_data['table_id']}")
    table_details = response.json()
    print("Table details:", table_details)
    
    return join_data

async def test_websocket_connection(session_token, table_id):
    try:
        async with websockets.connect(f"ws://localhost:8000/ws/table/{table_id}?session_token={session_token}") as websocket:
            print("Connected to table WebSocket")
            
            # Send a ping message
            await websocket.send(json.dumps({"type": "ping"}))
            
            # Receive response
            response = await websocket.recv()
            print("Received:", response)
            
    except Exception as e:
        print(f"WebSocket connection failed: {e}")

if __name__ == "__main__":
    # Test REST API
    join_data = test_table_management()
    
    # Test WebSocket connection
    asyncio.run(test_websocket_connection(join_data["session_token"], join_data["table_id"]))