"""Chroma-based vector store for semantic code search.

Indexes code files as embeddings for natural language search.
Uses the LLM provider's embedding API via LiteLLM.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("mahe.vector")

# Default code file extensions to index
DEFAULT_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".vue", ".svelte", ".sol", ".r", ".scala", ".clj", ".ex", ".exs",
}


@dataclass
class SearchResult:
    """A single semantic search result."""
    path: str
    content: str
    score: float
    start_line: int = 0
    metadata: dict = None


class VectorStore:
    """Chroma-based vector store for codebase semantic search.

    Usage:
        store = VectorStore(persist_dir=".mahe/vectors", embedding_fn=embed)
        store.index_project(".", globs=["**/*.py"])
        results = store.search("how does authentication work?", top_k=10)
    """

    def __init__(
        self,
        persist_dir: str,
        embedding_fn: Callable[[List[str]], List[List[float]]] = None,
        collection_name: str = "codebase",
    ):
        self.persist_dir = persist_dir
        self.embedding_fn = embedding_fn
        self.collection_name = collection_name
        self._collection = None
        self._enabled = False

        self._init_chroma()

    def _init_chroma(self) -> None:
        """Initialize Chroma client and get/create collection."""
        try:
            import chromadb
            os.makedirs(self.persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._enabled = True
            logger.info("Vector store initialized at %s", self.persist_dir)
        except ImportError:
            logger.warning("chromadb not installed. Vector search disabled.")
            self._enabled = False
        except Exception as e:
            logger.warning("Vector store init failed: %s. Disabling.", e)
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self.embedding_fn is not None

    def index_project(
        self,
        root: str,
        glob_patterns: List[str] = None,
        batch_size: int = 20,
    ) -> int:
        """Index all code files in a project directory.

        Args:
            root: Project root directory
            glob_patterns: Glob patterns for files (default: code files)
            batch_size: Number of files per embedding batch

        Returns:
            Number of files indexed
        """
        if not self.enabled:
            logger.warning("Vector store not enabled. Cannot index.")
            return 0

        if glob_patterns is None:
            glob_patterns = ["**/*"]

        # Collect code files
        files = []
        root_path = Path(root)
        for pattern in glob_patterns:
            for fpath in root_path.glob(pattern):
                if fpath.is_file() and fpath.suffix.lower() in DEFAULT_CODE_EXTS:
                    # Skip hidden, node_modules, etc.
                    parts = fpath.parts
                    if any(p.startswith(".") for p in parts if p != "."):
                        continue
                    if any(p in ("node_modules", "__pycache__", "venv", ".git", "dist", "build") for p in parts):
                        continue
                    files.append(fpath)

        if not files:
            logger.info("No code files found to index.")
            return 0

        logger.info("Indexing %d code files...", len(files))

        indexed = 0
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]

            # Read file contents
            contents = []
            valid_batch = []
            for fpath in batch:
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    # Chunk large files (max 4000 chars per chunk)
                    if len(content) > 4000:
                        # Store first 4000 chars as representative
                        content = content[:4000]
                    contents.append(content)
                    valid_batch.append(fpath)
                except Exception:
                    continue

            if not contents:
                continue

            # Generate embeddings
            try:
                embeddings = self.embedding_fn(contents)
            except Exception as e:
                logger.warning("Embedding batch failed: %s", e)
                continue

            # Prepare for Chroma
            ids = []
            documents = []
            metadatas = []
            for j, fpath in enumerate(valid_batch):
                rel_path = str(fpath.relative_to(root))
                file_hash = hashlib.md5(rel_path.encode()).hexdigest()[:12]
                ids.append(f"{file_hash}_{j}")
                documents.append(contents[j])
                metadatas.append({
                    "path": rel_path,
                    "language": fpath.suffix.lstrip("."),
                })

            # Upsert into Chroma
            try:
                self._collection.upsert(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                indexed += len(valid_batch)
            except Exception as e:
                logger.warning("Chroma upsert failed: %s", e)

        logger.info("Indexed %d files into vector store.", indexed)
        return indexed

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """Search the codebase semantically.

        Args:
            query: Natural language query
            top_k: Number of results to return

        Returns:
            List of SearchResult sorted by relevance
        """
        if not self.enabled:
            return []

        # Generate query embedding
        try:
            query_embeddings = self.embedding_fn([query])
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
            return []

        # Query Chroma
        try:
            results = self._collection.query(
                query_embeddings=query_embeddings,
                n_results=min(top_k, 50),
            )
        except Exception as e:
            logger.warning("Chroma query failed: %s", e)
            return []

        search_results = []
        if results and results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                document = results["documents"][0][i] if results["documents"] else ""
                distance = results["distances"][0][i] if results["distances"] else 1.0

                # Convert distance to similarity score (cosine distance → 0-1 score)
                score = max(0.0, 1.0 - distance) if distance else 1.0

                search_results.append(SearchResult(
                    path=metadata.get("path", "unknown"),
                    content=document[:500],
                    score=score,
                    metadata=metadata,
                ))

        return search_results

    def delete_file(self, path: str) -> None:
        """Remove a file from the index."""
        if not self._collection:
            return
        file_hash = hashlib.md5(path.encode()).hexdigest()[:12]
        try:
            # Get all items and filter by path
            results = self._collection.get()
            ids_to_delete = []
            if results and results["ids"]:
                for i, rid in enumerate(results["ids"]):
                    md = results["metadatas"][i] if results["metadatas"] else {}
                    if md.get("path") == path:
                        ids_to_delete.append(rid)
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
        except Exception as e:
            logger.debug("Vector delete failed for %s: %s", path, e)

    def reindex_file(self, root: str, path: str) -> None:
        """Reindex a single file."""
        if not self.enabled:
            return
        self.delete_file(path)
        full_path = os.path.join(root, path)
        if os.path.isfile(full_path):
            try:
                content = Path(full_path).read_text(encoding="utf-8", errors="replace")
                if len(content) > 4000:
                    content = content[:4000]
                embedding = self.embedding_fn([content])[0]
                file_hash = hashlib.md5(path.encode()).hexdigest()[:12]
                self._collection.upsert(
                    ids=[file_hash],
                    documents=[content],
                    embeddings=[embedding],
                    metadatas=[{"path": path}],
                )
            except Exception as e:
                logger.debug("Reindex failed for %s: %s", path, e)

    def clear(self) -> None:
        """Delete the entire collection."""
        if self._client and self._collection:
            try:
                self._client.delete_collection(self.collection_name)
                self._collection = self._client.create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        if not self._collection:
            return {"enabled": False, "count": 0}
        try:
            results = self._collection.get()
            count = len(results["ids"]) if results and results.get("ids") else 0
            return {"enabled": True, "count": count, "dir": self.persist_dir}
        except Exception:
            return {"enabled": True, "count": -1}


# Import needed for the dataclass
from dataclasses import dataclass
