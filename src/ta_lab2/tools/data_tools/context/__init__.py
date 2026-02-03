"""
Context retrieval and reasoning tools.

Tools for:
- Retrieving context from memory stores (get_context.py)
- Context-aware chat interfaces (chat_with_context.py)
- Reasoning engine creation and querying (create_reasoning_engine.py, query_reasoning_engine.py)
- Project Q&A (ask_project.py)

Dependencies:
- OpenAI (for embeddings/chat): pip install openai
- ChromaDB (for vector store): pip install chromadb
- Vertex AI (for reasoning engines): pip install google-cloud-aiplatform vertexai

Usage:
    # Get context from memories
    python -m ta_lab2.tools.data_tools.context.get_context "What is the EMA calculation?" --chroma-dir /path/to/chromadb

    # Interactive chat with context
    python -m ta_lab2.tools.data_tools.context.chat_with_context --chroma-dir /path/to/chromadb

    # Project Q&A
    python -m ta_lab2.tools.data_tools.context.ask_project --chroma-dir /path/to/chromadb --collection-name project_memories --memory-file memories.jsonl

    # Vertex AI reasoning engine (requires GCP setup)
    python -m ta_lab2.tools.data_tools.context.create_reasoning_engine
    python -m ta_lab2.tools.data_tools.context.query_reasoning_engine
"""

__all__ = [
    "get_context",
    "chat_with_context",
    "ask_project",
    "create_reasoning_engine",
    "query_reasoning_engine",
]
