"""Create catalog_species table and seed initial botanical species into RDS."""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

from ecoscan.plant_catalog import PLANT_CARE_CATALOG


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    catalog_table = op.create_table(
        "catalog_species",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("common_name", sa.String(length=100), nullable=False),
        sa.Column("scientific_name", sa.String(length=150), nullable=False),
        sa.Column("family", sa.String(length=100), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("abundance", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sunlight", sa.Text(), nullable=False),
        sa.Column("watering", sa.Text(), nullable=False),
        sa.Column("fertilizing", sa.Text(), nullable=False),
        sa.Column("soil", sa.Text(), nullable=False),
        sa.Column("climate", sa.Text(), nullable=False),
        sa.Column("pruning", sa.Text(), nullable=False),
    )
    op.create_index(
        op.f("ix_catalog_species_slug"),
        "catalog_species",
        ["slug"],
        unique=True,
    )

    # Seed inicial das espécies diretamente no RDS
    seed_records = []
    for item in PLANT_CARE_CATALOG.values():
        seed_records.append(
            {
                "id": uuid4(),
                "slug": item["slug"],
                "common_name": item["common_name"],
                "scientific_name": item["scientific_name"],
                "family": item["family"],
                "origin": item["origin"],
                "abundance": item["abundance"],
                "description": item["description"],
                "sunlight": item["sunlight"],
                "watering": item["watering"],
                "fertilizing": item["fertilizing"],
                "soil": item["soil"],
                "climate": item["climate"],
                "pruning": item["pruning"],
            }
        )

    op.bulk_insert(catalog_table, seed_records)


def downgrade() -> None:
    op.drop_index(op.f("ix_catalog_species_slug"), table_name="catalog_species")
    op.drop_table("catalog_species")
