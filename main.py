import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from models import Show, User, Token, TokenData, PartnerCreate, PasswordUpdate, ShowUpdate
from sqlclient import SqlClient
from auth import create_access_token, verify_password, SECRET_KEY, ALGORITHM

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Evergreen Podcasts API",
    description="API for managing podcasts and partners with JWT authentication.",
    version="2.0.0"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- Authentication & Authorization ---

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    client = SqlClient()
    user, _ = client.get_user_by_email(email=token_data.email)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    # In a real app, you might check if the user is active
    return current_user

async def get_admin_user(current_user: User = Depends(get_current_active_user)):
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user

# --- API Endpoints ---

@app.post("/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    client = SqlClient()
    user, _ = client.get_user_by_email(email=form_data.username)
    if not user or not verify_password(form_data.password, user.get('password_hash')):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.get('email')})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

# --- Admin Endpoints ---

@app.get("/podcasts", response_model=list[Show], dependencies=[Depends(get_admin_user)])
def get_all_podcasts():
    client = SqlClient()
    return client.get_all_podcasts()

@app.put("/podcasts/{show_id}", response_model=Show, dependencies=[Depends(get_admin_user)])
def update_podcast(show_id: str, show_data: ShowUpdate):
    client = SqlClient()
    updated_show, error = client.update_podcast(show_id, show_data)
    if error:
        raise HTTPException(status_code=404, detail=error)
    return updated_show

@app.delete("/podcasts/{show_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_admin_user)])
def delete_podcast(show_id: str):
    client = SqlClient()
    success, error = client.delete_podcast(show_id)
    if not success:
        raise HTTPException(status_code=404, detail=error)

@app.post("/partners", response_model=User, status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_admin_user)])
def create_partner(partner_data: PartnerCreate):
    client = SqlClient()
    new_user, error = client.create_partner(partner_data)
    if error:
        raise HTTPException(status_code=409, detail=error)
    return new_user

@app.put("/partners/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_admin_user)])
def update_partner_password(user_id: str, password_data: PasswordUpdate):
    client = SqlClient()
    success, error = client.update_password(user_id, password_data.password)
    if not success:
        raise HTTPException(status_code=404, detail=error)

@app.post("/podcasts/{show_id}/partners/{partner_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_admin_user)])
def associate_partner_with_show(show_id: str, partner_id: str):
    client = SqlClient()
    result, error = client.associate_partner_with_show(show_id, partner_id)
    if error:
        raise HTTPException(status_code=404, detail=error)
    return result

# --- Partner & Admin Endpoints ---

@app.get("/partners/{partner_id}/podcasts", response_model=list[Show], dependencies=[Depends(get_current_active_user)])
def get_podcasts_for_partner(partner_id: str):
    client = SqlClient()
    podcasts, error = client.get_podcasts_for_partner(partner_id)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return podcasts

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

