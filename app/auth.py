from datetime import datetime, timedelta
from time import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import requests
from jose import JWTError, jwt
from sqlalchemy import select, update, delete
import uuid
from app.models import create_access_token, verify_password, get_password_hash
from app.database.database import get_db
from app.database.models import (
    UserModel, UserSessionModel, OAuthProvider, 
      
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.models import Token, TokenData, User, UserCreate, OAuthToken, create_refresh_token

import os
from fastapi import HTTPException
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse


router = APIRouter(prefix="/auth", tags=["authentication"])

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Initialize OAuth
oauth = OAuth()

# Configure Google OAuth
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# Add the missing authentication functions
async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # First, try to decode the JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError as e:
        print(f"JWT Error: {e}")
        raise credentials_exception
        
    # Check if token is still valid in database
    result = await db.execute(
        select(UserSessionModel).where(
            UserSessionModel.access_token == token,
            UserSessionModel.expires_at > int(time())
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        print(f"Session not found for token: {token}")
        # Let's check if the token exists at all, regardless of expiration
        result = await db.execute(
            select(UserSessionModel).where(
                UserSessionModel.access_token == token
            )
        )
        session = result.scalar_one_or_none()
        if session:
            print(f"Token found but expired. Expires at: {session.expires_at}, Current time: {int(time())}")
        else:
            print("Token not found in database at all")
        raise credentials_exception
        
    # Get user from database
    result = await db.execute(
        select(UserModel).where(UserModel.username == token_data.username)
    )
    user = result.scalar_one_or_none()
    if user is None:
        print(f"User not found for username: {token_data.username}")
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# Add the missing generate_unique_username function
async def generate_unique_username(db: AsyncSession, base_username: str):
    """
    Generate a unique username by appending numbers if the base username is taken
    """
    username = base_username
    counter = 1
    
    # Clean the base username (remove special characters, limit length)
    username = "".join(c for c in base_username if c.isalnum() or c in ['_', '-']).lower()
    username = username[:20]  # Limit to 20 characters
    
    while True:
        result = await db.execute(
            select(UserModel).where(UserModel.username == username)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return username
        
        # If username exists, try with a number appended
        username = f"{base_username[:15]}{counter}"
        counter += 1

# Add Google OAuth routes
@router.get("/google/login")
async def google_login(request: Request, redirect_url: str = "http://localhost:3000"):
    redirect_uri = request.url_for('google_callback')
    # Store the redirect URL in session
    request.session['oauth_redirect'] = redirect_url
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        userinfo = token.get('userinfo')
        
        if not userinfo:
            raise HTTPException(status_code=400, detail="Could not get user info")
        
        email = userinfo.get('email')
        if not email:
            raise HTTPException(status_code=400, detail="Email not provided by Google")
        
        # Find or create user
        result = await db.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Create new user
            username = await generate_unique_username(db, userinfo.get('name', email.split('@')[0]))
            
            user = UserModel(
                id=uuid.uuid4(),
                email=email,
                username=username,
                oauth_provider="google",
                oauth_id=userinfo.get('sub'),
                created_at=int(time())
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        
        # Create session
        session = UserSessionModel(
            id=uuid.uuid4(),
            user_id=user.id,
            access_token=access_token,
            expires_at=int((datetime.utcnow() + access_token_expires).timestamp()),
            created_at=int(time())
        )
        
        db.add(session)
        await db.commit()
        
        # Redirect to frontend with token
        redirect_url = "http://localhost:3000"  # Your frontend URL
        return RedirectResponse(
            url=f"{redirect_url}?access_token={access_token}&token_type=bearer&expires_in={ACCESS_TOKEN_EXPIRE_MINUTES * 60}"
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

async def get_current_user_optional(
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
):
    if token is None:
        return None
        
    try:
        return await get_current_user(token, db)
    except:
        return None