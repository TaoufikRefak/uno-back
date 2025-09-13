import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws/test"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            
            # Send a test message
            await websocket.send("Hello, WebSocket!")
            
            # Receive response
            response = await websocket.recv()
            print(f"Received: {response}")
            
    except Exception as e:
        print(f"WebSocket connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())
