"""connection onboarding mode

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('odoo_connections', sa.Column('mode', sa.String(length=16), server_default='new', nullable=False))


def downgrade() -> None:
    op.drop_column('odoo_connections', 'mode')
