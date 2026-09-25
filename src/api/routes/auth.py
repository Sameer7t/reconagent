import jwt
import bcrypt
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from api.dependencies import get_user_db
from agent.user_db import UserDatabase

router = APIRouter(tags=["Authentication"])

SECRET_KEY = "reconagent-super-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 1 day

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

class UserCreate(BaseModel):
    email: str
    password: str
    role: str

class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    created_at: Union[str, datetime]
    is_active: bool

class Token(BaseModel):
    access_token: str
    token_type: str

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), user_db: UserDatabase = Depends(get_user_db)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    user = user_db.get_user_by_id(user_id)
    if user is None or not user.get("is_active"):
        raise credentials_exception
    return dict(user)

def require_role(allowed_roles: List[str]):
    def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return current_user
    return role_checker

@router.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), user_db: UserDatabase = Depends(get_user_db)):
    # OAuth2PasswordRequestForm uses 'username' field, which we treat as email
    user = user_db.get_user_by_email(form_data.username)
        
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active"):
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token = create_access_token(data={"sub": user["id"], "role": user["role"]})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

@router.post("/users", response_model=UserResponse)
def create_user(user: UserCreate, current_user: dict = Depends(require_role(["Admin"])), user_db: UserDatabase = Depends(get_user_db)):
    if user.role not in ["Admin", "Reviewer", "Viewer"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be Admin, Reviewer, or Viewer")
    
    existing = user_db.get_user_by_email(user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    hashed = get_password_hash(user.password)
    created_user = user_db.create_user(user.email, hashed, user.role)
    return created_user

@router.get("/users", response_model=List[UserResponse])
def get_users(current_user: dict = Depends(require_role(["Admin"])), user_db: UserDatabase = Depends(get_user_db)):
    return user_db.list_users()

@router.delete("/users/{user_id}")
def delete_user(user_id: str, current_user: dict = Depends(require_role(["Admin"])), user_db: UserDatabase = Depends(get_user_db)):
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    user = user_db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    deleted = user_db.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    return {"message": f"User '{user['email']}' deleted successfully"}
