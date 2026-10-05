"""Add s3 image_url and thumbnail_url to identifications, make image_data nullable."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "identifications",
        sa.Column("image_url", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "identifications",
        sa.Column("thumbnail_url", sa.String(), nullable=True),
    )
    op.alter_column(
        "identifications",
        "image_data",
        existing_type=sa.LargeBinary(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "identifications",
        "image_data",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
    op.drop_column("identifications", "thumbnail_url")
    op.drop_column("identifications", "image_url")
