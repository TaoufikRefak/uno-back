import uuid
from app.repositories.session_repository import SessionRepository
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.websocket.connection_manager import manager
from app.session_manager import DBSessionManager
from app.models import Table, Player, GameState, CardDeck, CardColor
from app.database.database import get_db
from app.repositories.table_repository import TableRepository
from app.repositories.player_repository import PlayerRepository
from app.repositories.game_state_repository import GameStateRepository
from sqlalchemy.ext.asyncio import AsyncSession
import uvicorn
import json
import time
from app.game_logic.game_actions import GameActionHandler
from app.utils.serialization import game_state_to_public_dict, card_to_dict


app = FastAPI(title="Uno Game API", version="1.0.0")

@app.on_event("startup")
async def on_startup():
    from app.database.init_db import init_db
    await init_db()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Update the WebSocket test endpoint to handle CORS
@app.websocket("/ws/test")
async def websocket_test_endpoint(websocket: WebSocket):
    # Allow all origins for testing
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message received: {data}")
    except WebSocketDisconnect:
        print("Client disconnected")

@app.websocket("/ws/table/{table_id}")
async def websocket_table_endpoint(
    websocket: WebSocket, 
    table_id: str, 
    session_token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    # Create session manager instance
    db_session_manager = DBSessionManager(db)
    
    # Validate session token
    player = await db_session_manager.get_player_from_session(session_token)
    if not player:
        await websocket.close(code=1008, reason="Invalid session token")
        return

    # Validate table
    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        await websocket.close(code=1008, reason="Table not found")
        return

    # Check player in table
    if not any(p.id == player.id for p in table.players):
        await websocket.close(code=1008, reason="Player not in this table")
        return

    # Connect using the fixed connection manager
    await manager.connect(websocket, session_token, table_id, db_session_manager)

    try:
        # ===== CRITICAL FIX: MINIMAL STATE SENDING =====
        # Only send essential state without triggering any events
        
        game_state_repo = GameStateRepository(db)
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
        
        # ONLY send state if game is actually in progress
        if game_state and game_state.status.value == "in_progress":
            print(f"WEBSOCKET: Sending game state to {player.username}")
            
            # Get fresh table data
            fresh_table = await table_repo.get_table(uuid.UUID(table_id))
            
            # Send current game state
            public_state = game_state_to_public_dict(game_state, fresh_table)
            await manager.send_personal_message({
                "type": "game_state",
                "data": public_state
            }, websocket)

            # Send player's current hand
            player_repo = PlayerRepository(db)
            fresh_player = await player_repo.get_player(player.id)
            if fresh_player and fresh_player.hand:
                await manager.send_personal_message({
                    "type": "your_hand", 
                    "data": [card_to_dict(card) for card in fresh_player.hand]
                }, websocket)
        else:
            print(f"WEBSOCKET: Game not in progress, sending minimal state to {player.username}")
            
            # For waiting games, send minimal info
            await manager.send_personal_message({
                "type": "table_info",
                "data": {
                    "table_id": table_id,
                    "status": "waiting",
                    "player_count": len(table.players),
                    "players": [{"id": str(p.id), "username": p.username} for p in table.players]
                }
            }, websocket)

        print(f"WEBSOCKET: {player.username} connected successfully to table {table_id}")

        # ===== MESSAGE HANDLING LOOP =====
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                message_type = message.get("type")
                
                print(f"WEBSOCKET: Received {message_type} from {player.username}")

                if message_type == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "data": {"timestamp": time.time()}
                    }, websocket)

                elif message_type == "play_card":
                    card_index = message.get("card_index")
                    chosen_color = message.get("chosen_color")
                    
                    if card_index is None:
                        await manager.send_personal_message({
                            "type": "error",
                            "data": {"message": "Missing card_index"}
                        }, websocket)
                        continue

                    print(f"GAME ACTION: {player.username} playing card {card_index}")
                    
                    result = await GameActionHandler.handle_play_card(
                        table_id, player, card_index,
                        CardColor(chosen_color) if chosen_color else None,
                        db=db
                    )
                    
                    await manager.send_personal_message({
                        "type": "play_card_result",
                        "data": result
                    }, websocket)
                    
                    print(f"GAME ACTION: Play card result: {result.get('success', False)}")

                elif message_type == "draw_card":
                    print(f"GAME ACTION: {player.username} drawing card")
                    
                    result = await GameActionHandler.handle_draw_card(table_id, player, db=db)
                    
                    await manager.send_personal_message({
                        "type": "draw_card_result",
                        "data": result
                    }, websocket)
                    
                    print(f"GAME ACTION: Draw card result: {result.get('success', False)}")

                elif message_type == "start_game":
                    print(f"GAME ACTION: {player.username} starting game")
                    
                    result = await GameActionHandler.handle_start_game(table_id, player, db=db)
                    
                    await manager.send_personal_message({
                        "type": "start_game_result",
                        "data": result
                    }, websocket)
                    
                    print(f"GAME ACTION: Start game result: {result.get('success', False)}")

                elif message_type == "declare_uno":
                    print(f"GAME ACTION: {player.username} declaring UNO")
                    
                    result = await GameActionHandler.handle_declare_uno(table_id, player, db=db)
                    
                    await manager.send_personal_message({
                        "type": "declare_uno_result",
                        "data": result
                    }, websocket)

                elif message_type == "challenge_uno":
                    target_player_id = message.get("target_player_id")
                    if not target_player_id:
                        await manager.send_personal_message({
                            "type": "error",
                            "data": {"message": "Missing target_player_id"}
                        }, websocket)
                        continue

                    print(f"GAME ACTION: {player.username} challenging UNO")
                    
                    result = await GameActionHandler.handle_challenge_uno(
                        table_id, player, target_player_id, db=db
                    )
                    
                    await manager.send_personal_message({
                        "type": "challenge_uno_result",
                        "data": result
                    }, websocket)

                else:
                    print(f"WEBSOCKET: Unknown message type: {message_type}")

            except WebSocketDisconnect:
                print(f"WEBSOCKET: {player.username} disconnected normally")
                break
            except json.JSONDecodeError as e:
                print(f"WEBSOCKET: JSON decode error from {player.username}: {e}")
                continue
            except Exception as e:
                print(f"WEBSOCKET: Error processing message from {player.username}: {e}")
                continue

    except WebSocketDisconnect:
        print(f"WEBSOCKET: {player.username} connection lost")
    except Exception as e:
        print(f"WEBSOCKET: Unexpected error with {player.username}: {e}")
    finally:
        print(f"WEBSOCKET: Cleaning up connection for {player.username}")
        await manager.disconnect(websocket, db_session_manager)

@app.get("/")
async def root():
    return {"message": "Uno Game Server is running"}

@app.get("/tables", response_model=list)
async def list_tables(db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    tables = await table_repo.get_all_tables()  

    return [{
        "id": str(table.id),
        "name": table.name,
        "player_count": len(table.players),
        "max_players": table.max_players,
        "status": table.status.value
    } for table in tables]

@app.post("/tables/{table_id}/join", response_model=dict)
async def join_table(table_id: str, username: str, db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))
    
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    
    # Check if table is full
    if len(table.players) >= table.max_players:
        raise HTTPException(status_code=400, detail="Table is full")
    
    # Create a new player
    player = Player(username=username)
    
    # Add player to table
    table.add_player(player)
    
    # Update database
    player_repo = PlayerRepository(db)
    await player_repo.create_player(player, uuid.UUID(table_id))
    await table_repo.update_table(table)
    
    # Create a session for the player
    session_repo = SessionRepository(db)
    session_token = await session_repo.create_session(player, table_id)
    
    return {
        "player_id": str(player.id),
        "session_token": session_token,
        "table_id": table_id
    }

@app.get("/tables/{table_id}", response_model=dict)
async def get_table(table_id: str, db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    game_state_repo = GameStateRepository(db)

    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))

    return {
        "table": table.dict(exclude={"players": {"__all__": {"hand"}}}),
        "game_state": game_state_to_public_dict(game_state, table)
    }

@app.post("/tables", response_model=dict)
async def create_table(name: str, max_players: int = 10, db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    table = await table_repo.create_table(name, max_players)
    
    return {
        "table_id": str(table.id),
        "table_name": table.name,
        "max_players": table.max_players
    }

@app.post("/tables/{table_id}/leave")
async def leave_table(table_id: str, session_token: str, db: AsyncSession = Depends(get_db)):
    session_repo = SessionRepository(db)
    player = await session_repo.get_player_from_session(session_token)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid session token")

    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if not table.remove_player(player.id):
        raise HTTPException(status_code=400, detail="Player not in table")

    await table_repo.update_table(table)
    await session_repo.remove_session(session_token)

    # Broadcast via WebSocket
    await manager.broadcast_to_table({
        "type": "player_left",
        "data": {"player_id": str(player.id)}
    }, table_id)

    return {"message": "Left table successfully"}

@app.post("/tables/{table_id}/start")
async def start_game(table_id: str, session_token: str = Query(...), db: AsyncSession = Depends(get_db)):
    session_repo = SessionRepository(db)
    player = await session_repo.get_player_from_session(session_token)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid session token")

    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    # Check creator
    if table.players and player.id != table.players[0].id:
        raise HTTPException(status_code=403, detail="Only the table creator can start the game")

    if len(table.players) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 players to start")

    print(f"Starting game for table {table_id} by player {player.username}")
    
    result = await GameActionHandler.handle_start_game(table_id, player, db=db)
    
    print(f"Game start result: {result}")
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)