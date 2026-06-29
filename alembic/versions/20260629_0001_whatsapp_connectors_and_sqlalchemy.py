from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260629_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_whatsapp_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.add_column("polls", sa.Column("provider", sa.Text(), nullable=True))
    op.add_column("polls", sa.Column("provider_message_id", sa.Text(), nullable=True))
    op.add_column("incoming_webhooks", sa.Column("provider_message_id", sa.Text(), nullable=True))
    op.add_column("incoming_webhooks", sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index("idx_polls_provider_message_id", "polls", ["provider_message_id"], unique=False)
    op.create_index("idx_incoming_webhooks_provider_message_id", "incoming_webhooks", ["provider_message_id"], unique=False)
    op.execute(
        """
        INSERT INTO tenant_whatsapp_connectors (tenant_id, provider, config_json, is_active, created_at, updated_at)
        SELECT
            id,
            'greenapi',
            json_build_object(
                'api_url', greenapi_api_url,
                'id_instance', greenapi_id_instance,
                'api_token_instance', greenapi_api_token_instance
            )::text,
            TRUE,
            created_at,
            updated_at
        FROM tenants
        """
    )
    op.execute(
        """
        UPDATE polls
        SET provider = 'greenapi',
            provider_message_id = greenapi_message_id
        WHERE greenapi_message_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE incoming_webhooks
        SET provider_message_id = greenapi_message_id
        WHERE greenapi_message_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_incoming_webhooks_provider_message_id", table_name="incoming_webhooks")
    op.drop_index("idx_polls_provider_message_id", table_name="polls")
    op.drop_column("incoming_webhooks", "provider_metadata_json")
    op.drop_column("incoming_webhooks", "provider_message_id")
    op.drop_column("polls", "provider_message_id")
    op.drop_column("polls", "provider")
    op.drop_table("tenant_whatsapp_connectors")
