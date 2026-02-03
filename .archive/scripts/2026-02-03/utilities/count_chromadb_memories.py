#!/usr/bin/env python3
"""Quick script to count memories in ChromaDB."""
import chromadb
from pathlib import Path

chroma_path = Path(r"C:\Users\asafi\Documents\ProjectTT\ChatGPT\20251228\out\chromadb")

if not chroma_path.exists():
    print(f"ChromaDB not found at: {chroma_path}")
    exit(1)

client = chromadb.PersistentClient(path=str(chroma_path))
collections = client.list_collections()

print(f"\nChromaDB Location: {chroma_path}")
print(f"Collections: {len(collections)}\n")

total = 0
for collection in collections:
    count = collection.count()
    total += count
    print(f"  {collection.name}: {count:,} memories")

print(f"\nTotal memories across all collections: {total:,}")
