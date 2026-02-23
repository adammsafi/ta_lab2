"""baseline

Revision ID: 25f2b3c90f65
Revises:
Create Date: 2026-02-23 12:47:18.933143

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "25f2b3c90f65"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass  # baseline no-op — existing schema unchanged


def downgrade() -> None:
    """Downgrade schema."""
    pass  # no rollback defined for baseline
