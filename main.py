import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import os

from models import Show, User
from sqlclient import SqlClient

# --- Configuration ---
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "admin-secret-key")

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Evergreen Podcasts API",
    description="API for managing podcasts and partners.",
    version="1.0.0"
)

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=True)

# --- Authentication Dependency ---
async def get_admin_user(api_key: str = Depends(api_key_header)):
    if api_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key for admin access",
        )
    return {"username": "admin", "role": "admin"}

# --- API Endpoints ---

@app.get("/podcasts", response_model=list[Show], dependencies=[Depends(get_admin_user)])
def get_all_podcasts():
    """Retrieve all podcasts from the catalog."""
    client = SqlClient()
    return client.get_all_podcasts()

@app.put("/podcasts/{show_id}", response_model=Show, dependencies=[Depends(get_admin_user)])
def update_podcast(show_id: str, show_data: Show):
    """Update an existing podcast's details."""
    client = SqlClient()
    updated_show, error = client.update_podcast(show_id, show_data)
    if error:
        if "not found" in error:
            raise HTTPException(status_code=404, detail=error)
        else:
            raise HTTPException(status_code=400, detail=error)
    return updated_show

@app.delete("/podcasts/{show_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_admin_user)])
def delete_podcast(show_id: str):
    """Delete a podcast from the catalog."""
    client = SqlClient()
    success, error = client.delete_podcast(show_id)
    if not success:
        raise HTTPException(status_code=404, detail=error)
    return

class PartnerCreate(BaseModel):
    name: str
    email: str
    password: str

class PasswordUpdate(BaseModel):
    password: str

@app.post("/partners", response_model=User, status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_admin_user)])
def create_partner(partner_data: PartnerCreate):
    """Create a new partner (user with 'partner' role)."""
    client = SqlClient()
    new_user, error = client.create_partner(partner_data)
    if error:
        raise HTTPException(status_code=409, detail=error)
    return new_user

@app.post("/podcasts/{show_id}/partners/{partner_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_admin_user)])
def associate_partner_with_show(show_id: str, partner_id: str):
    """Associate a partner with a specific podcast."""
    client = SqlClient()
    result, error = client.associate_partner_with_show(show_id, partner_id)
    if error:
        raise HTTPException(status_code=404, detail=error)
    return result

@app.get("/partners/{partner_id}/podcasts", response_model=list[Show], dependencies=[Depends(get_admin_user)])
def get_podcasts_for_partner(partner_id: str):
    """Retrieve all podcasts associated with a specific partner."""
    client = SqlClient()
    podcasts, error = client.get_podcasts_for_partner(partner_id)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return podcasts

@app.put("/partners/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_admin_user)])
def update_partner_password(user_id: str, password_data: PasswordUpdate):
    """Update a partner's password."""
    client = SqlClient()
    success, error = client.update_password(user_id, password_data.password)
    if not success:
        raise HTTPException(status_code=404, detail=error)
    return

@app.post("/login", response_model=User)
def login(login_data: UserLogin):
    """Authenticate a user and return their details."""
    client = SqlClient()
    user, error = client.validate_user(login_data.email, login_data.password)
    if error:
        raise HTTPException(status_code=500, detail=error)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user

if __name__ == "__main__":
    # For local development
    uvicorn.run(app, host="0.0.0.0", port=8000)
