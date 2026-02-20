
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.brain.digital_clone_brain import DigitalCloneBrain
from src.core.tools.contacts import ContactsTool

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def debug_contacts():
    print("\n--- 1. Initialize Brain ---")
    brain_path = "data/debug_brain"
    brain = DigitalCloneBrain(path=brain_path)
    print(f"Brain initialized at: {brain_path}")
    
    contacts_tool = ContactsTool(digital_brain=brain)
    
    print("\n--- 2. Save Contact (Pallavi) ---")
    result = await contacts_tool.execute(
        operation="save_contact",
        name="Pallavi",
        relationship="friend",
        phone="5551234567",
        email="pallavi@example.com",
        notes="Test contact"
    )
    print(f"Save Result: {result.output}")
    if not result.success:
        print(f"ERROR: {result.error}")
        return

    print("\n--- 3. Search Contact ---")
    # Immediate search
    search_result = await contacts_tool.execute(
        operation="search_contacts",
        name="Pallavi"
    )
    print(f"Search Result:\n{search_result.output}")
    
    # Reload to test persistence
    print("\n--- 4. Persistence Check (Reload Brain) ---")
    new_brain = DigitalCloneBrain(path=brain_path)
    new_tool = ContactsTool(digital_brain=new_brain)
    
    persist_result = await new_tool.execute(
        operation="search_contacts",
        name="Pallavi"
    )
    print(f"Persistence Result:\n{persist_result.output}")

if __name__ == "__main__":
    asyncio.run(debug_contacts())
