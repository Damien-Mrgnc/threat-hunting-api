from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # User fetch from DB
    result = db.execute(text("SELECT id, username, role, is_active FROM users WHERE username = :u"), {"u": username}).mappings().first()
    
    if result is None:
        raise credentials_exception
        
    user = dict(result)
    
    if not user["is_active"]:
        raise HTTPException(status_code=400, detail="Inactive user")
        
    return user

def get_current_active_analyst(current_user: dict = Depends(get_current_user)):
    """Allow any active user (Analyst or Admin)."""
    return current_user

def get_current_admin(current_user: dict = Depends(get_current_user)):
    """Restrict to Admin role only."""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user
