from typing import Dict, List, Optional
from app.models import Card, Player
from app.database.database import get_db
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
import json
from app.session_manager import DBSessionManager as session_manager
import time
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.websocket_to_session: Dict[WebSocket, str] = {}
        self.websocket_to_table: Dict[WebSocket, str] = {}
    
    async def get_session_manager(self):
        # Create a new session manager instance with a database session
        async for db in get_db():
            return session_manager(db)
        
    async def connect(self, websocket: WebSocket, session_token: str, table_id: str, session_manager: session_manager):
        await websocket.accept()
        
        # Remove any existing connection for this session
        await self.remove_session_connections(session_token, session_manager)
        
        # Store the connection
        if table_id not in self.active_connections:
            self.active_connections[table_id] = []
        
        # Check if this websocket is already in the connections
        if websocket not in self.active_connections[table_id]:
            self.active_connections[table_id].append(websocket)
        
        # Map WebSocket to session token and table
        self.websocket_to_session[websocket] = session_token
        self.websocket_to_table[websocket] = table_id
        
        # Mark player as online using the passed session manager
        player = await session_manager.get_player_from_session(session_token)
        if player:
            await session_manager.update_player_online_status(player.id, True)
        
    async def remove_session_connections(self, session_token: str, session_manager: session_manager):
        """Remove all connections for a session. Now an async function."""
        websockets_to_remove = []
        # Iterate over a copy of the items to avoid runtime errors if the dict changes
        for ws, token in list(self.websocket_to_session.items()):
            if token == session_token:
                websockets_to_remove.append(ws)
        
        for ws in websockets_to_remove:
            # Await the async disconnect function
            await self.disconnect(ws, session_manager)

    async def disconnect(self, websocket: WebSocket, session_manager: session_manager):
    # Get session token and table ID
        session_token = self.websocket_to_session.get(websocket)
        table_id = self.websocket_to_table.get(websocket)
        
        if not session_token or not table_id:
            return
            
        # Remove from active connections
        if table_id in self.active_connections:
            if websocket in self.active_connections[table_id]:
                self.active_connections[table_id].remove(websocket)
            if not self.active_connections[table_id]:
                del self.active_connections[table_id]
        
        # Remove from mappings
        if websocket in self.websocket_to_session:
            del self.websocket_to_session[websocket]
        if websocket in self.websocket_to_table:
            del self.websocket_to_table[websocket]
        
        # Mark player as offline - await the coroutine to get the player object
        player = await session_manager.get_player_from_session(session_token)
        if player:
            await session_manager.update_player_online_status(player.id, False)
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            if websocket.client_state == WebSocketState.DISCONNECTED:
                self.disconnect(websocket)
                return
            # Check if connection is still open
            if hasattr(websocket, 'client_state') and websocket.client_state == WebSocketState.DISCONNECTED:
                self.disconnect(websocket)
                return
            
            # Ensure all objects in the message are JSON serializable
            serializable_message = self._make_serializable(message)
            await websocket.send_text(json.dumps(serializable_message))
        except (RuntimeError, WebSocketDisconnect):
            # Connection is closed, remove it
            self.disconnect(websocket)
        except Exception as e:
            print(f"Error sending message: {e}")
            self.disconnect(websocket)

    async def broadcast_to_table(self, message: dict, table_id: str, exclude: WebSocket = None):
        if table_id not in self.active_connections:
            return
        # Ensure all objects in the message are JSON serializable
        serializable_message = self._make_serializable(message)
        
        # Create a list of connections to remove if they fail
        connections_to_remove = []
        
        for connection in self.active_connections[table_id]:
            if connection != exclude:
                try:
                    await connection.send_text(json.dumps(serializable_message))
                except (RuntimeError, WebSocketDisconnect):
                    # Mark this connection for removal
                    connections_to_remove.append(connection)
                except Exception as e:
                    print(f"Error broadcasting message: {e}")
                    connections_to_remove.append(connection)
        
        # Remove any failed connections
        for connection in connections_to_remove:
            self.disconnect(connection)


    async def get_table_connections(self, table_id: str) -> List[WebSocket]:
        """Get all WebSocket connections for a table"""
        return self.active_connections.get(table_id, [])

    async def get_player_connection(self, player_id: str) -> Optional[WebSocket]:
        """Get WebSocket connection for a specific player"""
        for websocket, session_token in self.websocket_to_session.items():
            player = session_manager.get_player_from_session(session_token)
            if player and str(player.id) == player_id:
                return websocket
        return None

    async def is_player_connected(self, player_id: str) -> bool:
        """Check if a player is currently connected"""
        return await self.get_player_connection(player_id) is not None


    def _make_serializable(self, obj):
        """Recursively convert objects to JSON-serializable forms"""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif hasattr(obj, 'dict'):
            return obj.dict()
        elif hasattr(obj, '__dict__'):
            return self._make_serializable(obj.__dict__)
        else:
            return str(obj)  # Fallback to string representation
        
    async def send_to_player(self, message: dict, player_id: str):
        """Send a message to a specific player across all their connections"""
        for websocket, session_token in self.websocket_to_session.items():
            player = session_manager.get_player_from_session(session_token)
            if player and str(player.id) == player_id:
                await self.send_personal_message(message, websocket)

# Create a global instance
manager = ConnectionManager()

