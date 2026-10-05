from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, EmailStr
from uuid import UUID

class Message(BaseModel):
    message: str

class UserSchema(BaseModel):
    email: EmailStr = Field(max_length=254)
    name: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)



class UserResponseSchema(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    model_config = ConfigDict(from_attributes=True)


class ProfileUpdateResponseSchema(BaseModel):
    user: UserResponseSchema
    access_token: str
    refresh_token: str
    token_type: str


class TokenSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class UserUpdateSchema(BaseModel):
    email: EmailStr = Field(max_length=254)
    name: str = Field(max_length=255)

class PasswordResetRequestSchema(BaseModel):
    email: EmailStr = Field(max_length=254)


class PasswordResetRequestResponseSchema(BaseModel):
    message: str
    reset_token: str | None = None


class PasswordResetSchema(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

class UserLoginSchema(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

class PatchUserSchema(BaseModel):
    email: EmailStr | None = Field(default=None, max_length=254)
    name: str | None = Field(default=None, max_length=255)


class IdentificationResponseSchema(BaseModel):
    id: UUID
    plant_name: str
    plant_slug: str | None
    confidence: float = Field(ge=0, le=1)
    recognized: bool
    created_at: datetime
    in_library: bool
    image_url: str
    thumbnail_url: str | None = None
