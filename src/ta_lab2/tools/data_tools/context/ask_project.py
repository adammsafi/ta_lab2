#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam
except ImportError:
    print("OpenAI Python library not found. Please install it with 'pip install openai'.")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    print("ChromaDB library not found. Please install it with 'pip install chromadb'.")
    sys.exit(1)

def get_query_embedding(query: str, client: OpenAI, model: str) -> List[float]:
    """Generates an embedding for a single query string."""
    try:
        response = client.embeddings.create(input=[query], model=model)
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Error calling OpenAI embedding API for query: {e}")
        return []

def find_semantic_memories(query: str, collection: chromadb.Collection, client: OpenAI, model: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """
    Finds the most relevant memories using semantic search in ChromaDB.
    """
    query_embedding = get_query_embedding(query, client, model)
    if not query_embedding:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_n
    )
    
    # The 'documents' field from ChromaDB contains the text we need for the LLM context.
    # We can reconstruct a simplified memory object for the next step.
    retrieved_memories = []
    if results and results.get('documents'):
        for i, doc in enumerate(results['documents'][0]):
            # The 'doc' is the string we created: "Title: ...\nType: ...\nContent: ..."
            # We can pass this directly to the generation model. For simplicity, we'll
            # extract the title from the first line for display.
            title_line = doc.split('\n')[0]
            # It's better to just pass the whole retrieved document as content.
            retrieved_memories.append({
                'title': title_line,
                'content': doc
            })
            
    return retrieved_memories

def ask_question(query: str, context_memories: List[Dict[str, Any]], client: OpenAI) -> str:
    """
    Asks the OpenAI model a question based on the provided context memories.
    """
    if not context_memories:
        return "I could not find any relevant memories in the knowledge base to answer that question."

    system_prompt = (
        "You are an expert assistant for the 'ta_lab2' software project. "
        "Your task is to answer the user's question based *only* on the provided context memories. "
        "The memories are extracted from past conversations and represent project decisions, procedures, and facts. "
        "Synthesize an answer from the provided information. "
        "If the context does not contain enough information to answer the question, you MUST state that you cannot answer from the knowledge base. "
        "Do not use any outside knowledge."
    )

    context_str = ""
    for i, mem in enumerate(context_memories):
        context_str += f"--- Memory {i+1} ---\n"
        # The full document from ChromaDB is now the content
        context_str += f"{mem.get('content', '')}\n\n"

    user_prompt = (
        f"CONTEXT MEMORIES:\n{context_str}\n\n"
        f"QUESTION: {query}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Using a more capable model for better synthesis
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content or "The model returned an empty response."
    except Exception as e:
        return f"An error occurred while contacting the OpenAI API: {e}"

def collect_user_feedback(answer: str) -> tuple[str, dict | None]:
    """
    Prompt for feedback: 'y', 'n', or 'correct' with correction data.
    Returns: (feedback_type, correction_data)
    """
    while True:
        try:
            feedback = input("\nWas this helpful? (y/n/correct): ").strip().lower()

            if feedback in ['y', 'yes']:
                return ('yes', None)
            elif feedback in ['n', 'no']:
                return ('no', None)
            elif feedback == 'correct':
                print("\nWhat is the correct information?")
                title = input("Title (press Enter to keep original): ").strip()

                # Get content with validation
                while True:
                    content = input("Content: ").strip()
                    if content:
                        break
                    print("Content cannot be empty. Please provide the correct information.")

                return ('correct', {'title': title, 'content': content})
            else:
                print("Please enter 'y', 'n', or 'correct'.")
        except (EOFError, KeyboardInterrupt):
            return ('exit', None)

def create_correction_memory(
    original_query: str,
    original_memories: List[Dict],
    correction_data: dict
) -> dict:
    """Create correction memory with unique ID and metadata."""
    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S")

    # Create unique ID with timestamp + hash
    hash_input = f"{timestamp_str}_{correction_data['content']}"
    hash_suffix = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
    memory_id = f"user_correction_{timestamp_str}_{hash_suffix}"

    # Try to extract original memory ID if available
    corrects_memory_id = "unknown"
    if original_memories:
        # Attempt to extract memory_id from the first memory's content
        first_mem_content = original_memories[0].get('content', '')
        for line in first_mem_content.split('\n'):
            if line.startswith('Memory ID:'):
                corrects_memory_id = line.replace('Memory ID:', '').strip()
                break

    # Build correction memory
    correction = {
        "memory_id": memory_id,
        "title": correction_data.get('title') or "User Correction",
        "content": correction_data['content'],
        "source_chunk": correction_data['content'],
        "type": "user_correction",
        "source_path": "ask_project_correction",
        "corrects_memory_id": corrects_memory_id,
        "original_query": original_query,
        "correction_timestamp_utc": timestamp.isoformat(),
        "conversation_id": f"ask_project_session_{hash_suffix}",
        "accepted_ts_utc": timestamp.isoformat(),
        "accepted_reason": "user_correction",
        "evidence": {"ok": True, "hits": 0, "patterns": [], "sample": []}
    }

    return correction

def append_correction_to_jsonl(correction: dict, jsonl_path: Path) -> bool:
    """Atomically append correction to JSONL file."""
    try:
        # Check if file exists
        if not jsonl_path.exists():
            response = input(f"\nMemory file does not exist at {jsonl_path}. Create it? (y/n): ").strip().lower()
            if response not in ['y', 'yes']:
                return False
            # Create parent directory if needed
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        # Append to file
        with open(jsonl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(correction, ensure_ascii=False) + '\n')

        return True
    except PermissionError:
        logging.error(f"Permission denied writing to {jsonl_path}")
        return False
    except OSError as e:
        logging.error(f"OS error writing to {jsonl_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error writing to {jsonl_path}: {e}")
        return False

def generate_code_search_queries(correction_content: str, client: OpenAI) -> List[str]:
    """Use GPT-4 to generate 2-3 code search queries from correction."""
    system_prompt = (
        "You are an assistant that generates semantic search queries for finding relevant code. "
        "Given a correction or piece of information, extract 2-3 concise search queries that would "
        "help find code files that may need to be updated based on this information. "
        "Focus on technical terms, function names, class names, and key concepts. "
        "Return only the queries, one per line, without numbering or explanation."
    )

    user_prompt = f"Generate 2-3 code search queries based on this correction:\n\n{correction_content}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )

        queries_text = response.choices[0].message.content or ""
        queries = [q.strip() for q in queries_text.split('\n') if q.strip()]
        return queries[:3]  # Ensure max 3 queries
    except Exception as e:
        logging.error(f"Error generating code search queries: {e}")
        return [correction_content]  # Fallback to original content

def search_affected_code(
    queries: List[str],
    code_collection: chromadb.Collection,
    client: OpenAI,
    embedding_model: str,
    threshold: float = 0.7
) -> List[Dict]:
    """Search code collection for affected code chunks."""
    all_results = []
    seen_ids = set()

    for query in queries:
        try:
            query_embedding = get_query_embedding(query, client, embedding_model)
            if not query_embedding:
                continue

            results = code_collection.query(
                query_embeddings=[query_embedding],
                n_results=10
            )

            if results and results.get('documents') and results.get('distances'):
                for i, doc in enumerate(results['documents'][0]):
                    distance = results['distances'][0][i]

                    # Filter by threshold
                    if distance > threshold:
                        continue

                    # Extract metadata if available
                    metadata = {}
                    if results.get('metadatas') and len(results['metadatas'][0]) > i:
                        metadata = results['metadatas'][0][i] or {}

                    # Create unique identifier
                    doc_id = results.get('ids', [[]])[0][i] if results.get('ids') else f"doc_{i}"

                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        all_results.append({
                            'doc_id': doc_id,
                            'content': doc,
                            'distance': distance,
                            'metadata': metadata
                        })
        except Exception as e:
            logging.error(f"Error searching code with query '{query}': {e}")
            continue

    # Sort by distance and limit to top 10
    all_results.sort(key=lambda x: x['distance'])
    return all_results[:10]

def format_code_results(results: List[Dict]) -> str:
    """Format code search results with file paths, line numbers, distances."""
    if not results:
        return "No code found that needs updating."

    output = "\nCode that may need updates:\n"
    for i, result in enumerate(results, 1):
        metadata = result.get('metadata', {})
        file_path = metadata.get('file_path', 'unknown')
        start_line = metadata.get('start_line', '?')

        distance = result['distance']
        relevance = "highly relevant" if distance < 0.5 else "relevant"

        output += f"\n{i}. {file_path}:{start_line}\n"
        output += f"   Distance: {distance:.2f} ({relevance})\n"

    return output

def check_code_collection(
    chroma_client: chromadb.Client,
    collection_name: str
) -> chromadb.Collection | None:
    """Check if code collection exists, return None if missing."""
    try:
        collection = chroma_client.get_collection(name=collection_name)
        return collection
    except Exception:
        return None

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Interactively ask questions about your project using a semantic search-powered knowledge base."
    )
    ap.add_argument("--chroma-dir", required=True, help="Path to the directory containing ChromaDB files.")
    ap.add_argument("--collection-name", required=True, help="Name of the ChromaDB collection to use.")
    ap.add_argument("--embedding-model", default="text-embedding-3-small", help="OpenAI model for query embeddings.")
    ap.add_argument("--memory-file", required=True, help="Path to JSONL file for saving corrections")
    ap.add_argument("--code-collection-name", default=None, help="ChromaDB collection name for code (optional)")
    ap.add_argument("--code-search-threshold", type=float, default=0.7, help="Distance threshold for code relevance (0-2, lower=stricter)")

    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        return 1
    
    client = OpenAI()
    chroma_path = Path(args.chroma_dir)
    
    if not chroma_path.exists() or not chroma_path.is_dir():
        log.error(f"ChromaDB directory not found at: {chroma_path}")
        return 1

    # --- Initialize ChromaDB ---
    log.info(f"Connecting to ChromaDB at: {chroma_path}")
    try:
        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        collection = chroma_client.get_collection(name=args.collection_name)
        log.info(f"✅ Connected to collection '{args.collection_name}' with {collection.count()} memories.")
    except Exception as e:
        log.error(f"Failed to connect to ChromaDB collection: {e}")
        log.error("Please ensure you have run the `embed_memories.py` script successfully first.")
        return 1

    # --- Check for optional code collection ---
    code_collection = None
    if args.code_collection_name:
        code_collection = check_code_collection(chroma_client, args.code_collection_name)
        if code_collection:
            log.info(f"✅ Code collection available for update detection")
        else:
            log.warning(f"Code collection '{args.code_collection_name}' not found. Code search disabled.")
            log.warning("Run embed_codebase.py to enable code update detection.")

    print("\nWelcome to the Project Q&A Tool (Level 4: Semantic Search).")
    
    while True:
        try:
            query = input("\nAsk a question (or type 'exit' to quit): ")
            if query.lower().strip() == 'exit':
                break
            if not query.strip():
                continue

            # 1. Retrieve relevant memories using semantic search
            print("🧠 Finding semantically relevant memories...")
            relevant_memories = find_semantic_memories(query, collection, client, model=args.embedding_model)
            
            if not relevant_memories:
                print("\nAssistant: I could not find any relevant memories in the knowledge base to answer that question.")
                continue

            # 2. Generate answer
            print("🤖 Synthesizing an answer...")
            answer = ask_question(query, relevant_memories, client)

            # 3. Print answer
            print("\nAssistant:")
            print(answer)

            # 4. Collect feedback
            feedback_type, correction_data = collect_user_feedback(answer)

            if feedback_type == 'exit':
                break
            elif feedback_type == 'correct' and correction_data:
                # Create and save correction
                correction = create_correction_memory(query, relevant_memories, correction_data)
                memory_file_path = Path(args.memory_file)

                if append_correction_to_jsonl(correction, memory_file_path):
                    print("✅ Correction saved to memory bank.")

                    # Check for affected code
                    if code_collection:
                        print("\n🔍 Searching for code that may need updates...")
                        search_queries = generate_code_search_queries(
                            correction_data['content'], client
                        )
                        affected_code = search_affected_code(
                            search_queries, code_collection, client,
                            args.embedding_model, args.code_search_threshold
                        )

                        if affected_code:
                            print(format_code_results(affected_code))
                        else:
                            print("No code found that needs updating.")
                else:
                    print("❌ Failed to save correction.")

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nAn unexpected error occurred: {e}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
