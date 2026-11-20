import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.update(
    SYNC_INTERVAL_HOURS="12",
    SYNC_RECHECK_HOURS="24",
    SYNC_UNSUBSCRIBED_RECHECK_HOURS="168",
    SYNC_BATCH_SIZE="2",
    SYNC_DAILY_LIMIT="0",
    TOKEN_RETENTION_DAYS="30",
    CHANNEL_NAME_REFRESH_HOURS="24",
    TOKEN_ENCRYPTION_KEY="test",
)
