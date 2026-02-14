"""Main entry point for the autonomous agent."""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import load_config
from src.core.brain.core_brain import CoreBrain
from src.core.brain.digital_clone_brain import DigitalCloneBrain

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the autonomous agent."""

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = load_config()

        logger.info(f"🤖 Autonomous Claude Agent v1.0.0")
        logger.info(f"Model: {config.default_model}")
        logger.info(f"Self-build mode: {config.self_build_mode}")

        # Initialize appropriate brain
        if config.self_build_mode:
            logger.info("🧠 Initializing coreBrain for self-building...")
            brain = CoreBrain(config.core_brain_path)

            #TODO: Implement self-building logic
            logger.info("✅ coreBrain initialized")
            logger.info("⚠️  Self-building logic not yet implemented")
            logger.info("📝 Next: Implement meta-agent builder")

        else:
            logger.info("🧠 Initializing DigitalCloneBrain for production...")
            brain = DigitalCloneBrain(config.digital_clone_brain_path)

            logger.info("✅ DigitalCloneBrain initialized")
            logger.info("⚠️  Production mode not yet fully implemented")

        logger.info("\n✅ Bootstrap complete! Core components ready.")
        logger.info("\nImplemented so far:")
        logger.info("  ✓ Configuration system")
        logger.info("  ✓ Anthropic API client")
        logger.info("  ✓ Tool system (Bash, File, Web)")
        logger.info("  ✓ Dual brain architecture")
        logger.info("\nStill needed:")
        logger.info("  • Core agent execution loop")
        logger.info("  • Sub-agent spawner")
        logger.info("  • Meta-agent self-builder")
        logger.info("  • Monitoring (Telegram + Dashboard)")
        logger.info("  • EC2 deployment scripts")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
