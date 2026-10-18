# app/schemas/user_schemas.py
"""Admin account management."""

from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth_schemas import UserRow

SystemRole = Literal["user", "admin"]


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: SystemRole = "user"


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[SystemRole] = None
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserPage(BaseModel):
    items: List[UserRow]
    total: int
    page: int
    per_page: int
