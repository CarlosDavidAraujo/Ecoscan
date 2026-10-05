from datetime import datetime
from uuid import uuid4, UUID

from sqlalchemy import DateTime, LargeBinary, ForeignKey, func

from sqlalchemy.orm import (Mapped, 
                            mapped_column, relationship, 
                            mapped_as_dataclass, registry
                        )


table_registry = registry()



@mapped_as_dataclass(table_registry)
class User:
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(nullable=False, unique=True)
    email: Mapped[str] = mapped_column(nullable=False, unique=True)
    password: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid4)


    plants: Mapped[list["Plant"]] = relationship(init=False, 
                                                 cascade="all, delete-orphan",
                                                 lazy="selectin"
                                                 )
    identifications: Mapped[list["Identification"]] = relationship(
        init=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    



@mapped_as_dataclass(table_registry)
class Plant:
    __tablename__ = "plants"   

    name: Mapped[str] = mapped_column(nullable=False)
    care_information: Mapped[str] = mapped_column(nullable=False)
    characteristics: Mapped[str] = mapped_column(nullable=False)
    botanical_family: Mapped[str] = mapped_column(nullable=False)
    image_url: Mapped[str] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid4)


@mapped_as_dataclass(table_registry)
class Identification:
    __tablename__ = "identifications"

    plant_name: Mapped[str] = mapped_column(nullable=False)
    plant_slug: Mapped[str | None] = mapped_column(nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    recognized: Mapped[bool] = mapped_column(nullable=False)
    image_url: Mapped[str] = mapped_column(nullable=False, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(nullable=True, default=None)
    image_content_type: Mapped[str] = mapped_column(nullable=False)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, default=None)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    in_library: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        init=False,
        index=True,
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid4)


@mapped_as_dataclass(table_registry)
class PasswordResetToken:
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        init=False,
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid4)
