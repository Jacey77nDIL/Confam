"""
Schema reference for tools and docs.

The running application imports ORM classes from the ``models`` **package**
(``models/saved_recipient.py``, etc.). When both ``models/`` and this file exist,
``import models`` resolves to the **package**, not this module — so this file must
not define a second ``SavedRecipient`` mapper.

``saved_recipients`` — bring the live DB in line with the ORM (see
``database/migrations/ensure_saved_recipients_orm_columns.sql``). At minimum you may need::

    ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS aliases JSONB;
    ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS usage_frequency INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ;
    ALTER TABLE saved_recipients ADD COLUMN IF NOT EXISTS account_name VARCHAR(255);

SQLAlchemy 1.x style equivalent (nullable optional name on the account)::

    from sqlalchemy import Column, String
    account_name = Column(String, nullable=True)
    bank_name = Column(String, nullable=True)

The canonical 2.0 mapping is ``models.saved_recipient.SavedRecipient``.
"""

__all__: list[str] = []
