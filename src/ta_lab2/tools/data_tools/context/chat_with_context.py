#!/usr/bin/env python3
"""
Chat with an LLM that has access to your project memories.

Usage:
    OPENAI_API_KEY=your-key python chat_with_context.py

Features:
- Automatically retrieves relevant context for each message
- Maintains conversation history
- No need to manually provide context
"""

import os
import sys
from pathlib import Path
from typing import List, Dict

try:
    from openai import OpenAI
except ImportError:
    print("Error: pip install openai")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    print("Error: pip install chromadb")
    sys.exit(1)


class ContextualChat:
    """Chat assistant with automatic context retrieval from ChromaDB."""

    def __init__(
        self,
        chroma_dir: Path,
        collection_name: str = "project_memories",
        model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-small",
        context_k: int = 8,
    ):
        self.client = OpenAI()
        self.model = model
        self.embedding_model = embedding_model
        self.context_k = context_k

        # Connect to ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
        self.collection = self.chroma_client.get_collection(name=collection_name)

        # Conversation history
        self.messages: List[Dict[str, str]] = []

        print(f"✓ Connected to {collection_name} ({self.collection.count()} memories)")

    def get_relevant_context(self, query: str) -> str:
        """Retrieve relevant memories for the query."""

        # Generate embedding
        response = self.client.embeddings.create(
            input=[query], model=self.embedding_model
        )
        query_embedding = response.data[0].embedding

        # Search ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding], n_results=self.context_k
        )

        if not results or not results.get("documents"):
            return ""

        # Format context
        context_parts = ["# Relevant Project Context\n"]
        for i, doc in enumerate(results["documents"][0], 1):
            context_parts.append(f"\n## Memory {i}\n{doc}\n")

        return "\n".join(context_parts)

    def chat(self, user_message: str) -> str:
        """Send a message and get a response with auto-retrieved context."""

        # Get relevant context
        context = self.get_relevant_context(user_message)

        # Build system prompt with context
        system_prompt = (
            "You are a helpful assistant for the ta_lab2 project. "
            "Use the provided project context to inform your responses. "
            "If the context contains relevant information, use it. "
            "If not, you can still answer based on general knowledge."
        )

        if context:
            system_prompt += f"\n\n{context}"

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history (last 6 messages to keep context window manageable)
        messages.extend(self.messages[-6:])

        # Add current message
        messages.append({"role": "user", "content": user_message})

        # Get response
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
        )

        assistant_message = response.choices[0].message.content or ""

        # Update history
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": assistant_message})

        return assistant_message


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Chat with context from ChromaDB memory bank"
    )
    parser.add_argument("--chroma-dir", required=True, help="ChromaDB directory")
    parser.add_argument(
        "--collection", default="project_memories", help="Collection name"
    )
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model")
    parser.add_argument(
        "--context-k",
        type=int,
        default=8,
        help="Number of context memories to retrieve",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    chroma_dir = Path(args.chroma_dir)

    if not chroma_dir.exists():
        print(f"Error: ChromaDB not found at {chroma_dir}")
        sys.exit(1)

    print("Initializing contextual chat...")
    chat = ContextualChat(
        chroma_dir,
        collection_name=args.collection,
        model=args.model,
        context_k=args.context_k,
    )

    print("\n" + "=" * 60)
    print("Contextual Chat - Your memories are automatically retrieved")
    print("Type 'exit' to quit, 'clear' to reset conversation")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("Goodbye!")
                break

            if user_input.lower() == "clear":
                chat.messages = []
                print("Conversation history cleared.\n")
                continue

            # Get response with auto-retrieved context
            print("\n🧠 Retrieving relevant context...")
            response = chat.chat(user_input)

            print(f"\nAssistant: {response}\n")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
