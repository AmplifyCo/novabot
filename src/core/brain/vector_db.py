"""ChromaDB vector database wrapper."""

import chromadb
from chromadb.config import Settings
import logging
import uuid
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class VectorDatabase:
    """Wrapper for ChromaDB to store and retrieve semantic memories."""

    def __init__(
        self,
        path: str,
        collection_name: str = "agent_memory",
        embedding_model: str = "all-MiniLM-L6-v2"
    ):
        """Initialize vector database.

        Args:
            path: Path to store ChromaDB data
            collection_name: Name of the collection
            embedding_model: Sentence transformer model for embeddings
        """
        self.path = path
        self.collection_name = collection_name

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"embedding_model": embedding_model}
        )

        logger.info(f"Initialized vector DB at {path}, collection: {collection_name}")

    async def store(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        """Store text with embeddings.

        Args:
            text: Text to store
            metadata: Optional metadata dict
            doc_id: Optional document ID (generated if not provided)

        Returns:
            Document ID
        """
        if not doc_id:
            doc_id = str(uuid.uuid4())

        self.collection.add(
            documents=[text],
            metadatas=[metadata or {}],
            ids=[doc_id]
        )

        logger.debug(f"Stored document {doc_id}")
        return doc_id

    async def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Semantic search for relevant memories.

        Args:
            query: Search query
            n_results: Number of results to return
            filter_metadata: Optional metadata filter

        Returns:
            List of matching documents with metadata and distances
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=filter_metadata
        )

        # Format results
        matches = []
        if results['documents'] and results['documents'][0]:
            for idx, doc in enumerate(results['documents'][0]):
                matches.append({
                    "text": doc,
                    "metadata": results['metadatas'][0][idx] if results['metadatas'] else {},
                    "distance": results['distances'][0][idx] if results['distances'] else 0.0,
                    "id": results['ids'][0][idx] if results['ids'] else None
                })

        logger.debug(f"Found {len(matches)} matches for query")
        return matches

    def count(self) -> int:
        """Get total number of documents in collection.

        Returns:
            Document count
        """
        return self.collection.count()

    def delete(self, doc_id: str):
        """Delete a document by ID.

        Args:
            doc_id: Document ID to delete
        """
        self.collection.delete(ids=[doc_id])
        logger.debug(f"Deleted document {doc_id}")

    def clear(self):
        """Clear all documents from collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name
        )
        logger.info(f"Cleared collection {self.collection_name}")
