from typing import Optional
import uuid
from app.repositories.session_repository import SessionRepository
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os
from app.websocket.connection_manager import manager
from app.session_manager import DBSessionManager
from sqlalchemy import select, update, delete

# Import from the new schemas file
from app.schemas import CardColor, GameStatus, OAuthProvider, PlayerRole
from app.models import Player, Token, TokenData, User, UserCreate, OAuthToken, create_refresh_token
from app.database.database import get_db
from app.repositories.table_repository import TableRepository
from app.repositories.player_repository import PlayerRepository
from app.repositories.game_state_repository import GameStateRepository
from app.repositories.user_repository import UserRepository
from app.database.models import UserModel, PlayerModel, TableModel
from sqlalchemy.ext.asyncio import AsyncSession
import uvicorn
import json
import time
from app.game_logic.game_actions import GameActionHandler
from app.utils.serialization import game_state_to_public_dict, card_to_dict
from app.auth import get_current_active_user, get_current_user_optional, router as auth_router, try_get_current_user


app = FastAPI(title="Uno Game API", version="1.0.0")
app.include_router(auth_router)

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
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "super-secret"),  # must be set in .env
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
        is_spectator = table_player.role == PlayerRole.SPECTATOR

    # Connect using the fixed connection manager
    table_player = None
    for p in table.players + table.spectators:
            if str(p.id) == str(player.id):
                table_player = p
                break
                
        
    # Check if player is a spectator
    is_spectator = table_player.role == PlayerRole.SPECTATOR

    # Connect using the fixed connection manager
    await manager.connect(websocket, session_token, table_id, db_session_manager)

    try:
        # ===== CRITICAL FIX: MINIMAL STATE SENDING =====
        # Only send essential state without triggering any events
        await manager.send_personal_message({
            "type": "role_assigned",
            "data": {"role": "spectator" if is_spectator else "player"}
        }, websocket)

        game_state_repo = GameStateRepository(db)
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
        
        # ONLY send state if game is actually in progress
        if game_state and game_state.status.value == "in_progress":
            print(f"WEBSOCKET: Sending game state to {player.username}")
            
            # Get fresh table data
            fresh_table = await table_repo.get_table(uuid.UUID(table_id))
            if is_spectator:
                # Spectators get public state only
                public_state = game_state.to_public_dict(fresh_table)
                await manager.send_personal_message({
                    "type": "game_state",
                    "data": public_state
                }, websocket)
            else:
                # Players get full state including their hand
                public_state = game_state.to_public_dict(fresh_table)
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
                    "spectator_count": len(table.spectators),
                    "players": [{"id": str(p.id), "username": p.username} for p in table.players],
                    "spectators": [{"id": str(s.id), "username": s.username} for s in table.spectators]
                }
            }, websocket)

        print(f"WEBSOCKET: {player.username} connected as {'spectator' if is_spectator else 'player'} to table {table_id}")

        # ===== MESSAGE HANDLING LOOP =====
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                message_type = message.get("type")
                
                # Prevent spectators from performing game actions
                if is_spectator and message_type in ["play_card", "draw_card", "start_game", "declare_uno", "challenge_uno"]:
                    await manager.send_personal_message({
                        "type": "error",
                        "data": {"message": "Spectators cannot perform game actions"}
                    }, websocket)
                    continue
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
                    print(f"DEBUG: Received start_game message from {player.username}")
                    if is_spectator:
                        await manager.send_personal_message({
                            "type": "error",
                            "data": {"message": "Spectators cannot start games"}
                        }, websocket)
                        continue
                    print(f"GAME ACTION: {player.username} starting game")
                    result = await db.execute(select(TableModel).where(TableModel.id == uuid.UUID(table_id)))
                    db_table = result.scalar_one_or_none()
                    
                    if not db_table or not player.user_id or db_table.creator_id != player.user_id:
                        await manager.send_personal_message({
                            "type": "start_game_result",
                            "data": {
                                "success": False, 
                                "error": "Only the table creator can start the game."
                            }
                        }, websocket)
                        continue
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
@app.get("/tables/{table_id}", response_model=dict)
async def get_table(table_id: str, db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    game_state_repo = GameStateRepository(db)

    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))

    # Create a response that excludes player hands
    table_response = {
        "id": str(table.id),
        "name": table.name,
        "creator_id": str(table.creator_id) if table.creator_id else None, # <-- ADD THIS
        "players": [{
            "id": str(p.id),
            "user_id": str(p.user_id) if p.user_id else None, # <-- ADD THIS
            "username": p.username,
            "hand_count": len(p.hand),
            "is_online": p.is_online,
            "role": p.role.value if hasattr(p, 'role') else "player"
        } for p in table.players],
        "spectators": [{
            "id": str(s.id),
            "username": s.username,
            "is_online": s.is_online,
            "role": "spectator"
        } for s in table.spectators],
        "max_players": table.max_players,
        "status": table.status.value,
        "created_at": table.created_at
    }

    return {
        "table": table_response,
        "game_state": game_state_to_public_dict(game_state, table) if game_state else {}
    }

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
async def join_table(
    table_id: str,
    username: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(try_get_current_user)
):
    # ===================================================================
    # 1. DETERMINE USER IDENTITY (Authenticated or Guest)
    # ===================================================================
    user_id = None
    is_guest = current_user is None # <--- Determine if user is a guest here

    if not is_guest:
        # Authenticated user
        username = current_user.username
        user_id = current_user.id
    elif not username:
        # Guest user without a username provided
        raise HTTPException(status_code=400, detail="Username is required for guest users")
    else:
        # Guest user with a username, find or create their UserModel
        user_repo = UserRepository(db)
        existing_user = await user_repo.get_user_by_username(username)
        if existing_user:
            user_id = existing_user.id
        else:
            guest_user = UserModel(
                id=uuid.uuid4(),
                username=username,
                email=f"{username.lower().replace(' ', '_')}@guest.uno",
                created_at=int(time.time())
            )
            db.add(guest_user)
            await db.commit()
            await db.refresh(guest_user)
            user_id = guest_user.id

    # ===================================================================
    # 2. LOAD REPOSITORIES AND TABLE DATA
    # ===================================================================
    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    session_repo = SessionRepository(db)
    game_state_repo = GameStateRepository(db)

    # ===================================================================
    # 3. HANDLE PLAYER LOGIC (Re-join or New Join)
    # ===================================================================
    
    existing_player = next((p for p in table.players + table.spectators if p.user_id == user_id), None)

    response_data = {}

    if existing_player:
        # --- SCENARIO A: PLAYER IS RE-JOINING ---
        print(f"Player '{existing_player.username}' is re-joining table '{table.name}'.")
        
        session_token = await session_repo.create_session(existing_player, table_id)
        
        response_data = {
            "player_id": str(existing_player.id),
            "user_id": str(user_id),
            "session_token": session_token,
            "table_id": table_id,
            "role": existing_player.role.value
        }
    else:
        # --- SCENARIO B: PLAYER IS JOINING FOR THE FIRST TIME ---
        print(f"New player '{username}' is joining table '{table.name}'.")
        game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))

        # --- MODIFIED ROLE ASSIGNMENT LOGIC ---
        role = PlayerRole.PLAYER # Default to player for authenticated users
        
        if is_guest:
            # ***************************************************************
            # ** RULE: Unauthenticated (guest) users can ONLY be spectators **
            # ***************************************************************
            role = PlayerRole.SPECTATOR
        elif game_state and game_state.status == GameStatus.IN_PROGRESS:
            # RULE: Any authenticated user joining a game in progress is a spectator
            role = PlayerRole.SPECTATOR
        elif len(table.players) >= table.max_players:
            # RULE: Any authenticated user joining a full (but not started) game is a spectator
            role = PlayerRole.SPECTATOR
        
        # Create a new Player object
        new_player = Player(
            id=uuid.uuid4(),
            username=username,
            hand=[],
            is_online=True,
            role=role
        )

        # Persist the new player to the database
        player_repo = PlayerRepository(db)
        await player_repo.create_player(new_player, uuid.UUID(table_id), user_id)
        
        # Add the player to the local table object
        if role == PlayerRole.SPECTATOR:
            table.spectators.append(new_player)
        else:
            table.players.append(new_player)
        
        await table_repo.update_table(table)
        
        session_token = await session_repo.create_session(new_player, table_id)
        
        response_data = {
            "player_id": str(new_player.id),
            "user_id": str(user_id),
            "session_token": session_token,
            "table_id": table_id,
            "role": role.value
        }

    # ===================================================================
    # 4. UNIFIED BROADCAST AND RESPONSE
    # ===================================================================
    
    fresh_table = await table_repo.get_table(uuid.UUID(table_id))
    fresh_game_state = await game_state_repo.get_game_state(uuid.UUID(table_id))
    
    if fresh_game_state:
        print(f"Broadcasting updated game state to table {table_id}.")
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": fresh_game_state.to_public_dict(fresh_table)
        }, table_id)

    return response_data


@app.post("/tables", response_model=dict)
async def create_table(
    name: str, 
    max_players: int = 10, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    creator_id = current_user.id if current_user else None # Get creator_id

    table_repo = TableRepository(db)
    table = await table_repo.create_table(name, max_players, creator_id)
    
    # If user is authenticated, mark them as the creator
    creator_name = current_user.username if current_user else "guest"
    
    return {
        "table_id": str(table.id),
        "table_name": table.name,
        "max_players": table.max_players,
        "creator_id": str(creator_id) if creator_id else None,
        "creator_name": creator_name
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



@app.post("/tables/{table_id}/add_bot", response_model=dict)
async def add_bot_to_table(table_id: str, db: AsyncSession = Depends(get_db)):
    table_repo = TableRepository(db)
    table = await table_repo.get_table(uuid.UUID(table_id))

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    if table.status != GameStatus.WAITING:
        raise HTTPException(status_code=400, detail="Cannot add a bot to a game in progress.")
    if len(table.players) >= table.max_players:
        raise HTTPException(status_code=400, detail="Table is full.")

    # Find a unique name for the bot *for this table*
    bot_names = ["Bot Alpha", "Bot Bravo", "Bot Charlie", "Bot Delta", "Bot Echo"]
    
    # Get the usernames of players already in the current table
    existing_player_names = {p.username for p in table.players}
    
    bot_name = next((name for name in bot_names if name not in existing_player_names), "Bot Omega")

    # --- START OF MODIFIED LOGIC ---
    # Find an existing UserModel for the bot, or create a new one.
    user_repo = UserRepository(db)
    bot_user = await user_repo.get_user_by_username(bot_name)

    if not bot_user:
        print(f"Creating a new persistent user for bot: {bot_name}")
        bot_user = UserModel(
            id=uuid.uuid4(),
            username=bot_name,
            email=f"{bot_name.lower().replace(' ', '_')}@bot.uno",
            is_bot=True,
            created_at=int(time.time())
        )
        db.add(bot_user)
        # We commit here to ensure the user exists before creating the player
        await db.commit() 
        await db.refresh(bot_user)
    else:
        print(f"Found existing user for bot: {bot_name}")
    # --- END OF MODIFIED LOGIC ---

    # Create the Player instance for the bot
    bot_player = Player(
        id=uuid.uuid4(),
        username=bot_user.username,
        is_bot=True,
        role=PlayerRole.PLAYER
    )

    player_repo = PlayerRepository(db)
    # The `create_player` function will now link to the found-or-created bot_user.id
    await player_repo.create_player(bot_player, table.id, bot_user.id)

    # Broadcast the updated state
    fresh_table = await table_repo.get_table(table.id)
    fresh_game_state = await GameStateRepository(db).get_game_state(table.id)
    if fresh_game_state:
        await manager.broadcast_to_table({
            "type": "game_state",
            "data": fresh_game_state.to_public_dict(fresh_table)
        }, table_id)

    return {"message": f"'{bot_name}' has been added to the table."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)