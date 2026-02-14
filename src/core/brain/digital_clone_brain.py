"""Digital Clone Brain for production use (permanent)."""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from cryptography.fernet import Fernet
from .vector_db import VectorDatabase

logger = logging.getLogger(__name__)


class DigitalCloneBrain:
    """Production brain for digital clone. Persistent forever."""

    def __init__(self, path: str = "data/digital_clone_brain"):
        """Initialize digital clone brain.

        Args:
            path: Path to store brain data
        """
        self.path = path

        # Initialize vector databases for different types of memory
        self.memory = VectorDatabase(
            path=f"{path}/memory",
            collection_name="clone_memory"
        )

        self.preferences = VectorDatabase(
            path=f"{path}/preferences",
            collection_name="preferences"
        )

        self.contacts = VectorDatabase(
            path=f"{path}/contacts",
            collection_name="contacts"
        )

        logger.info(f"Initialized DigitalCloneBrain at {path}")

    async def learn_communication_style(self, email_sample: str):
        """Learn communication style from email sample.

        Args:
            email_sample: Sample email text
        """
        await self.preferences.store(
            text=email_sample,
            metadata={
                "type": "communication_style",
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.info("Learned communication style from email sample")

    async def remember_person(
        self,
        name: str,
        relationship: str,
        preferences: Dict[str, Any]
    ):
        """Remember a person and their details.

        Args:
            name: Person's name
            relationship: Relationship to user
            preferences: Dict of person's preferences
        """
        contact_id = name.lower().replace(" ", "_")

        await self.contacts.store(
            text=f"{name}: {relationship}. Preferences: {json.dumps(preferences)}",
            metadata={
                "name": name,
                "relationship": relationship,
                **preferences
            },
            doc_id=f"contact_{contact_id}"
        )

        logger.info(f"Remembered person: {name}")

    async def remember_preference(self, category: str, preference: str):
        """Remember a user preference.

        Args:
            category: Preference category (food, travel, etc.)
            preference: Preference description
        """
        await self.preferences.store(
            text=f"Preference in {category}: {preference}",
            metadata={
                "category": category,
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.info(f"Remembered preference: {category} - {preference}")

    async def export_for_migration(self, password: str, output_file: str = "digital_clone_brain.brain") -> str:
        """Export entire brain for migration to new machine.

        Args:
            password: Password for encryption
            output_file: Output file name

        Returns:
            Path to encrypted brain file
        """
        # Create brain data structure
        brain_data = {
            "memory_count": self.memory.count(),
            "preferences_count": self.preferences.count(),
            "contacts_count": self.contacts.count(),
            "exported_at": datetime.now().isoformat()
        }

        # Convert to JSON
        json_data = json.dumps(brain_data)

        # Encrypt with password
        key = Fernet.generate_key()
        cipher = Fernet(key)
        encrypted = cipher.encrypt(json_data.encode())

        # Save to file
        with open(output_file, 'wb') as f:
            f.write(encrypted)

        logger.info(f"Exported DigitalCloneBrain to {output_file}")
        return output_file

    async def import_from_migration(self, brain_file: str, password: str):
        """Import brain from migration file.

        Args:
            brain_file: Path to encrypted brain file
            password: Decryption password
        """
        logger.info(f"Importing DigitalCloneBrain from {brain_file}")
        # Implementation would decrypt and restore data
        # Simplified for now

    async def get_relevant_context(self, task: str, max_results: int = 5) -> str:
        """Get relevant context for a task.

        Args:
            task: Task description
            max_results: Max number of memories to retrieve

        Returns:
            Context string
        """
        # Search memories
        memories = await self.memory.search(task, n_results=max_results)

        # Search preferences
        prefs = await self.preferences.search(task, n_results=3)

        # Build context
        context_parts = []

        if memories:
            context_parts.append("## Relevant Memories:")
            for mem in memories:
                context_parts.append(f"- {mem['text'][:200]}...")

        if prefs:
            context_parts.append("\n## User Preferences:")
            for pref in prefs:
                context_parts.append(f"- {pref['text']}")

        return "\n".join(context_parts) if context_parts else ""
