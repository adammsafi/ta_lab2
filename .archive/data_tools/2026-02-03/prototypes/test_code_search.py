#!/usr/bin/env python3
import argparse
import os
import sys
from openai import OpenAI
import chromadb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--chroma-dir", required=True)
    parser.add_argument("--collection-name", required=True)
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--top-n", type=int, default=3)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set.")
        sys.exit(1)

    client = OpenAI()
    chroma_client = chromadb.PersistentClient(path=args.chroma_dir)

    try:
        collection = chroma_client.get_collection(name=args.collection_name)
    except Exception as e:
        print(f"Error getting collection: {e}")
        sys.exit(1)

    print(f"Generating embedding for query: '{args.query}'")
    query_embedding = (
        client.embeddings.create(input=[args.query], model=args.embedding_model)
        .data[0]
        .embedding
    )

    print(f"Performing semantic search for top {args.top_n} results...")
    results = collection.query(query_embeddings=[query_embedding], n_results=args.top_n)

    print("\n--- SEARCH RESULTS ---")
    if not results or not results.get("documents"):
        print("No relevant code chunks found.")
        return

    for i, doc in enumerate(results["documents"][0]):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i]

        print(f"\n--- Result {i+1} (Distance: {distance:.4f}) ---")
        print(
            f"Source: {metadata.get('file_path')} (Line: {metadata.get('start_line')})"
        )
        print(f"Name: {metadata.get('name')}")
        print("-" * 20)
        print(doc)


if __name__ == "__main__":
    main()
