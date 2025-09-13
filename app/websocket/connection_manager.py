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
        # CRITICAL FIX: Track connection states to prevent duplicate processing
        self.connection_states: Dict[WebSocket, str] = {}  # websocket -> "connecting"|"connected"|"disconnecting"
    
    async def get_session_manager(self):
        # Create a new session manager instance with a database session
        async for db in get_db():
            return session_manager(db)
        
    async def connect(self, websocket: WebSocket, session_token: str, table_id: str, session_manager: session_manager):
        # CRITICAL FIX: Prevent duplicate connections
        if websocket in self.connection_states:
            print(f"WebSocket already in connection state: {self.connection_states[websocket]}")
            return
            
        print(f"CONNECT: Setting up connection for session {session_token[:8]}... to table {table_id}")
        self.connection_states[websocket] = "connecting"
        
        await websocket.accept()
        
        # CRITICAL FIX: Remove any existing connection for this session WITHOUT triggering events
        await self._silent_remove_session_connections(session_token, session_manager)
        
        # Store the connection
        if table_id not in self.active_connections:
            self.active_connections[table_id] = []
        
        # Check if this websocket is already in the connections
        if websocket not in self.active_connections[table_id]:
            self.active_connections[table_id].append(websocket)
        
        # Map WebSocket to session token and table
        self.websocket_to_session[websocket] = session_token
        self.websocket_to_table[websocket] = table_id
        
        # CRITICAL FIX: Only mark as online, don't broadcast anything yet
        player = await session_manager.get_player_from_session(session_token)
        if player:
            await session_manager.update_player_online_status(player.id, True)
        
        # Mark as connected
        self.connection_states[websocket] = "connected"
        print(f"CONNECT: Successfully connected session {session_token[:8]}...")
        
    async def _silent_remove_session_connections(self, session_token: str, session_manager: session_manager):
        """Remove all connections for a session silently (no broadcasts)"""
        websockets_to_remove = []
        
        for ws, token in list(self.websocket_to_session.items()):
            if token == session_token and ws in self.connection_states:
                print(f"CLEANUP: Found existing connection for session {token[:8]}...")
                websockets_to_remove.append(ws)
        
        for ws in websockets_to_remove:
            await self._silent_disconnect(ws, session_manager)

    async def disconnect(self, websocket: WebSocket, session_manager: session_manager):
        """Public disconnect method"""
        if websocket not in self.connection_states:
            return
            
        if self.connection_states[websocket] == "disconnecting":
            print("Already disconnecting this WebSocket")
            return
            
        self.connection_states[websocket] = "disconnecting"
        
        # Get session info before cleanup
        session_token = self.websocket_to_session.get(websocket)
        table_id = self.websocket_to_table.get(websocket)
        
        if session_token:
            print(f"DISCONNECT: Disconnecting session {session_token[:8]}... from table {table_id}")
        
        await self._cleanup_connection(websocket, session_manager)
        
        # Remove from connection states last
        if websocket in self.connection_states:
            del self.connection_states[websocket]

    async def _silent_disconnect(self, websocket: WebSocket, session_manager: session_manager):
        """Silent disconnect (no broadcasts, used for cleanup)"""
        if websocket not in self.connection_states:
            return
            
        self.connection_states[websocket] = "disconnecting"
        await self._cleanup_connection(websocket, session_manager)
        
        if websocket in self.connection_states:
            del self.connection_states[websocket]
    
    async def _cleanup_connection(self, websocket: WebSocket, session_manager: session_manager):
        """Clean up connection mappings and update player status"""
        session_token = self.websocket_to_session.get(websocket)
        table_id = self.websocket_to_table.get(websocket)
        
        # Remove from active connections
        if table_id and table_id in self.active_connections:
            if websocket in self.active_connections[table_id]:
                self.active_connections[table_id].remove(websocket)
            if not self.active_connections[table_id]:
                del self.active_connections[table_id]
        
        # Remove from mappings
        if websocket in self.websocket_to_session:
            del self.websocket_to_session[websocket]
        if websocket in self.websocket_to_table:
            del self.websocket_to_table[websocket]
        
        # CRITICAL FIX: Only mark as offline if no other connections exist for this session
        if session_token:
            has_other_connections = any(
                token == session_token and ws != websocket 
                for ws, token in self.websocket_to_session.items()
            )
            
            if not has_other_connections:
                print(f"CLEANUP: Marking player offline for session {session_token[:8]}...")
                player = await session_manager.get_player_from_session(session_token)
                if player:
                    await session_manager.update_player_online_status(player.id, False)
            else:
                print(f"CLEANUP: Player still has other connections, keeping online")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            # CRITICAL FIX: Check connection state before sending
            if websocket not in self.connection_states:
                print("SEND: WebSocket not in connection states, skipping")
                return
                
            if self.connection_states[websocket] == "disconnecting":
                print("SEND: WebSocket is disconnecting, skipping message")
                return
                
            if hasattr(websocket, 'client_state') and websocket.client_state == WebSocketState.DISCONNECTED:
                print("SEND: WebSocket client disconnected, cleaning up")
                # Don't call disconnect here to avoid recursion
                return
            
            # Ensure all objects in the message are JSON serializable
            serializable_message = self._make_serializable(message)
            await websocket.send_text(json.dumps(serializable_message))
            
        except (RuntimeError, WebSocketDisconnect):
            print("SEND: Connection closed during send")
            # Don't call disconnect here to avoid recursion issues
        except Exception as e:
            print(f"SEND: Error sending message: {e}")

    async def broadcast_to_table(self, message: dict, table_id: str, exclude: WebSocket = None):
        if table_id not in self.active_connections:
            return
            
        # Ensure all objects in the message are JSON serializable
        serializable_message = self._make_serializable(message)
        
        # Create a list of connections to remove if they fail
        connections_to_remove = []
        
        for connection in self.active_connections[table_id]:
            if connection != exclude:
                # CRITICAL FIX: Check connection state before broadcasting
                if (connection in self.connection_states and 
                    self.connection_states[connection] == "connected"):
                    try:
                        await connection.send_text(json.dumps(serializable_message))
                    except (RuntimeError, WebSocketDisconnect):
                        print("BROADCAST: Connection failed, marking for removal")
                        connections_to_remove.append(connection)
                    except Exception as e:
                        print(f"BROADCAST: Error broadcasting message: {e}")
                        connections_to_remove.append(connection)

        # CRITICAL FIX: Clean up failed connections without causing cascading disconnects
        for connection in connections_to_remove:
            if connection in self.connection_states:
                self.connection_states[connection] = "disconnecting"

    async def get_table_connections(self, table_id: str) -> List[WebSocket]:
        """Get all WebSocket connections for a table"""
        connections = self.active_connections.get(table_id, [])
        # Only return connections that are actually connected
        return [ws for ws in connections if ws in self.connection_states and self.connection_states[ws] == "connected"]

    

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
        
    async def get_player_connection(self, player_id: str, session_manager) -> Optional[WebSocket]:
        """Get WebSocket connection for a specific player"""
        for websocket, session_token in self.websocket_to_session.items():
            if (websocket in self.connection_states and 
                self.connection_states[websocket] == "connected"):
                player = await session_manager.get_player_from_session(session_token)
                if player and str(player.id) == player_id:
                    return websocket
        return None

    # And update the send_to_player method:
    async def send_to_player(self, message: dict, player_id: str, session_manager):
        """Send a message to a specific player across all their connections"""
        for websocket, session_token in self.websocket_to_session.items():
            if (websocket in self.connection_states and 
                self.connection_states[websocket] == "connected"):
                player = await session_manager.get_player_from_session(session_token)
                if player and str(player.id) == player_id:
                    await self.send_personal_message(message, websocket)
# Create a global instance
manager = ConnectionManager()