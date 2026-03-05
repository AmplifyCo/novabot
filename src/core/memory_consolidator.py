"""Memory consolidation — periodic background task for pruning and maintenance.

Runs alongside ReminderScheduler and SelfHealingMonitor as a background asyncio task.
Prevents unbounded memory growth by:
- Smart two-tier pruning: keep important old entries, drop trivial ones
- Episodic memory pruning (old failures, low-value strategies)
- Logging memory stats for observability
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Keywords that signal an important memory worth keeping longer
_IMPORTANCE_KEYWORDS = re.compile(
    r"(preference|decision|correction|approved|rejected|learned|registered|"
    r"joined|created|important|critical|password|key|secret|birthday|"
    r"calibration|identity|style|never|always)",
    re.IGNORECASE,
)


class MemoryConsolidator:
    """Background task for periodic memory maintenance.

    Architecture: Memory layer component.
    Operates on DigitalCloneBrain's vector databases.

    Two-tier pruning:
    - Trivial conversations (greetings, acks) → pruned after 7 days
    - Important memories (decisions, preferences, corrections) → kept 90 days
    - Episodic memory: failed episodes pruned after 14 days
    """

    # Run consolidation every 6 hours
    CONSOLIDATION_INTERVAL = 6 * 60 * 60
    # Tier 1: Trivial conversations pruned after 7 days
    TRIVIAL_RETENTION_DAYS = 7
    # Tier 2: Important conversations kept for 90 days
    IMPORTANT_RETENTION_DAYS = 90
    # Episodic: failed episodes pruned after 14 days
    EPISODE_FAILURE_RETENTION_DAYS = 14
    # Max conversation turns per talent context before pruning
    MAX_TURNS_PER_CONTEXT = 500

    def __init__(self, digital_brain=None, episodic_memory=None, telegram=None):
        """Initialize memory consolidator.

        Args:
            digital_brain: DigitalCloneBrain instance
            episodic_memory: EpisodicMemory instance for episode pruning
            telegram: TelegramNotifier for status updates
        """
        self.brain = digital_brain
        self.episodic_memory = episodic_memory
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
            "episodes_pruned": 0,
            "contexts_checked": 0,
        }

        # Check each talent context for old conversations (two-tier pruning)
        if hasattr(self.brain, '_contexts'):
            for talent_name, ctx_db in self.brain._contexts.items():
                stats["contexts_checked"] += 1
                pruned = await self._prune_old_conversations(ctx_db, talent_name)
                stats["conversations_pruned"] += pruned

        # Check legacy memory too
        if hasattr(self.brain, 'memory'):
            pruned = await self._prune_old_conversations(self.brain.memory, "legacy")
            stats["conversations_pruned"] += pruned

        # Prune old failed episodes from episodic memory
        if self.episodic_memory:
            ep_pruned = await self._prune_old_episodes()
            stats["episodes_pruned"] = ep_pruned

        self.total_cleaned += stats["conversations_pruned"] + stats["episodes_pruned"]

        # Log memory stats
        memory_stats = await self._get_memory_stats()

        logger.info(
            f"Consolidation complete: pruned {stats['conversations_pruned']} conversations + "
            f"{stats['episodes_pruned']} episodes, "
            f"checked {stats['contexts_checked']} contexts. "
            f"Total memories: {memory_stats.get('total', 0)}"
        )

    @staticmethod
    def _is_important(text: str) -> bool:
        """Check if a memory contains important content worth keeping longer."""
        return bool(_IMPORTANCE_KEYWORDS.search(text))

    async def _prune_old_conversations(self, db, context_name: str) -> int:
        """Two-tier pruning of old conversation turns from a vector database.

        Tier 1 (trivial): Greetings, acks, short exchanges → pruned after 7 days
        Tier 2 (important): Decisions, preferences, corrections → kept 90 days

        Args:
            db: VectorDatabase instance
            context_name: Name for logging

        Returns:
            Number of documents pruned
        """
        pruned = 0
        trivial_cutoff = (datetime.now() - timedelta(days=self.TRIVIAL_RETENTION_DAYS)).isoformat()
        important_cutoff = (datetime.now() - timedelta(days=self.IMPORTANT_RETENTION_DAYS)).isoformat()

        try:
            results = await db.search(
                query="conversation",
                n_results=self.MAX_TURNS_PER_CONTEXT,
                filter_metadata={"type": "conversation"}
            )

            for result in results:
                timestamp = result.get("metadata", {}).get("timestamp", "")
                doc_id = result.get("id")
                text = result.get("text", "")

                if not timestamp or not doc_id:
                    continue

                is_important = self._is_important(text)

                # Important memories: only prune after 90 days
                if is_important and timestamp < important_cutoff:
                    try:
                        db.delete(doc_id)
                        pruned += 1
                    except Exception:
                        pass
                # Trivial memories: prune after 7 days
                elif not is_important and timestamp < trivial_cutoff:
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

    async def _prune_old_episodes(self) -> int:
        """Prune old failed episodes from episodic memory.

        Successful episodes and strategies are kept longer (90 days).
        Failed episodes are pruned after 14 days — prevents the hallucination
        loop where Nova recalls and repeats its own old failures.

        Returns:
            Number of episodes pruned
        """
        pruned = 0
        failure_cutoff = (datetime.now() - timedelta(days=self.EPISODE_FAILURE_RETENTION_DAYS)).isoformat()
        success_cutoff = (datetime.now() - timedelta(days=self.IMPORTANT_RETENTION_DAYS)).isoformat()

        try:
            results = await self.episodic_memory.db.search(
                query="episode task action",
                n_results=500,
                filter_metadata={"type": "episode"}
            )

            for result in results:
                meta = result.get("metadata", {})
                timestamp = meta.get("timestamp", "")
                doc_id = result.get("id")
                success = meta.get("success", True)

                if not timestamp or not doc_id:
                    continue

                # Failed episodes: prune after 14 days
                if not success and timestamp < failure_cutoff:
                    try:
                        self.episodic_memory.db.delete(doc_id)
                        pruned += 1
                    except Exception:
                        pass
                # Successful episodes: prune after 90 days
                elif success and timestamp < success_cutoff:
                    try:
                        self.episodic_memory.db.delete(doc_id)
                        pruned += 1
                    except Exception:
                        pass

            if pruned > 0:
                logger.info(f"Pruned {pruned} old episodes from episodic memory")

        except Exception as e:
            logger.debug(f"Episode pruning error: {e}")

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
