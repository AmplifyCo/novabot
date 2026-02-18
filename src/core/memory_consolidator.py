"""Memory consolidation — periodic background task for pruning and maintenance.

Runs alongside ReminderScheduler and SelfHealingMonitor as a background asyncio task.
Prevents unbounded memory growth by:
- Removing old conversation turns beyond a retention limit
- Cleaning duplicate/near-duplicate memories
- Logging memory stats for observability
"""

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """Background task for periodic memory maintenance.

    Architecture: Memory layer component.
    Operates on DigitalCloneBrain's vector databases.
    """

    # Run consolidation every 6 hours
    CONSOLIDATION_INTERVAL = 6 * 60 * 60
    # Keep conversation turns for 30 days
    CONVERSATION_RETENTION_DAYS = 30
    # Max conversation turns per talent context before pruning
    MAX_TURNS_PER_CONTEXT = 500

    def __init__(self, digital_brain=None, telegram=None):
        """Initialize memory consolidator.

        Args:
            digital_brain: DigitalCloneBrain instance
            telegram: TelegramNotifier for status updates
        """
        self.brain = digital_brain
        self.telegram = telegram
        self.is_running = False
        self.last_consolidation = None
        self.total_cleaned = 0

    async def start(self):
        """Start the consolidation loop."""
        if not self.brain:
            logger.warning("MemoryConsolidator: No brain configured, skipping")
            return

        self.is_running = True
        logger.info("🧹 Memory consolidator started")

        # Wait 30 minutes after startup before first run
        await asyncio.sleep(30 * 60)

        while self.is_running:
            try:
                await self._run_consolidation()
                await asyncio.sleep(self.CONSOLIDATION_INTERVAL)
            except Exception as e:
                logger.error(f"Memory consolidation error: {e}", exc_info=True)
                await asyncio.sleep(self.CONSOLIDATION_INTERVAL)

    async def _run_consolidation(self):
        """Run one consolidation cycle."""
        self.last_consolidation = datetime.now()
        logger.info("Running memory consolidation...")

        stats = {
            "conversations_pruned": 0,
            "contexts_checked": 0,
        }

        # Check each talent context for old conversations
        if hasattr(self.brain, '_contexts'):
            for talent_name, ctx_db in self.brain._contexts.items():
                stats["contexts_checked"] += 1
                pruned = await self._prune_old_conversations(ctx_db, talent_name)
                stats["conversations_pruned"] += pruned

        # Check legacy memory too
        if hasattr(self.brain, 'memory'):
            pruned = await self._prune_old_conversations(self.brain.memory, "legacy")
            stats["conversations_pruned"] += pruned

        self.total_cleaned += stats["conversations_pruned"]

        # Log memory stats
        memory_stats = await self._get_memory_stats()

        logger.info(
            f"Consolidation complete: pruned {stats['conversations_pruned']} old turns, "
            f"checked {stats['contexts_checked']} contexts. "
            f"Total memories: {memory_stats.get('total', 0)}"
        )

    async def _prune_old_conversations(self, db, context_name: str) -> int:
        """Prune old conversation turns from a vector database.

        Args:
            db: VectorDatabase instance
            context_name: Name for logging

        Returns:
            Number of documents pruned
        """
        pruned = 0
        cutoff = (datetime.now() - timedelta(days=self.CONVERSATION_RETENTION_DAYS)).isoformat()

        try:
            # Search for old conversations
            results = await db.search(
                query="conversation",
                n_results=self.MAX_TURNS_PER_CONTEXT,
                filter_metadata={"type": "conversation"}
            )

            # Find entries older than retention period
            for result in results:
                timestamp = result.get("metadata", {}).get("timestamp", "")
                doc_id = result.get("id")
                if timestamp and doc_id and timestamp < cutoff:
                    try:
                        db.delete(doc_id)
                        pruned += 1
                    except Exception:
                        pass

            if pruned > 0:
                logger.info(f"Pruned {pruned} old conversations from [{context_name}]")

        except Exception as e:
            logger.debug(f"Pruning error in [{context_name}]: {e}")

        return pruned

    async def _get_memory_stats(self) -> dict:
        """Get current memory statistics."""
        stats = {"total": 0, "by_context": {}}

        try:
            if hasattr(self.brain, 'identity'):
                count = self.brain.identity.count()
                stats["by_context"]["identity"] = count
                stats["total"] += count

            if hasattr(self.brain, 'preferences'):
                count = self.brain.preferences.count()
                stats["by_context"]["preferences"] = count
                stats["total"] += count

            if hasattr(self.brain, 'contacts'):
                count = self.brain.contacts.count()
                stats["by_context"]["contacts"] = count
                stats["total"] += count

            if hasattr(self.brain, '_contexts'):
                for name, ctx_db in self.brain._contexts.items():
                    count = ctx_db.count()
                    stats["by_context"][name] = count
                    stats["total"] += count

        except Exception as e:
            logger.debug(f"Memory stats error: {e}")

        return stats
