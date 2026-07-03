from pydantic import BaseModel, EmailStr
from app.models.models import Role


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: Role = Role.patient  # admin creates doctor accounts separately via /admin/doctors


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
