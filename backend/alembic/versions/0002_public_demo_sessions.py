"""public demo sessions

Additive and backward compatible: a boolean with a server default; existing sessions become
regular (non-demo) sessions. Downgrade only drops the flag.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 12:45:19.961730
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('is_public_demo', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('sessions', 'is_public_demo')
