#!/usr/bin/env python3
"""Generate OpenAI fine-tuning datasets from memory collections."""
from __future__ import annotations

import argparse
import json
import os
import sys
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam
except ImportError:
    print(
        "OpenAI Python library not found. Please install it with 'pip install openai'."
    )
    sys.exit(1)


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Reads a JSONL file line by line."""
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {i} in {path}: {e}") from e


def generate_question_for_memory(
    memory: Dict[str, Any], client: OpenAI, model: str
) -> str | None:
    """
    Uses an LLM to generate a user question for a given memory.
    """
    mem_type = memory.get("type", "fact")
    title = memory.get("title", "Untitled Memory")
    content = memory.get("content", "")

    system_prompt_content = (
        "You are an expert at generating concise, direct, and relevant user questions "
        "for a fine-tuning dataset. The question should be directly answerable by the provided "
        "memory content. Focus on what a software developer would genuinely ask to retrieve this specific piece of information. "
        "Keep the question to a single sentence if possible, max 2 sentences. Do NOT include the answer in the question."
    )

    user_prompt_content = (
        f"Generate a single, direct question for the following project memory:\n\n"
        f"Type: {mem_type}\n"
        f"Title: {title}\n"
        f"Content: {content}\n\n"
        f"Question:"
    )

    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt_content},
        {"role": "user", "content": user_prompt_content},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=50,  # Questions should be short
            temperature=0.5,  # Keep questions fairly consistent
            seed=42,  # For reproducibility
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error generating question for memory '{title}': {e}")
        return None


def main() -> int:
    # --- Setup Logging ---
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Generates a fine-tuning dataset (training_data.jsonl) from accepted memories."
    )
    ap.add_argument(
        "--memory-file",
        required=True,
        help="Path to the final_memory.jsonl file containing accepted memories.",
    )
    ap.add_argument(
        "--output",
        required=True,
        help="Path to write the generated training_data.jsonl file.",
    )
    ap.add_argument(
        "--question-gen-model",
        default="gpt-3.5-turbo-0125",
        help="OpenAI model to use for generating user questions (default: gpt-3.5-turbo-0125).",
    )
    ap.add_argument(
        "--max-memories",
        type=int,
        default=0,  # 0 means all memories
        help="Optional: Limit the number of memories to process for faster testing.",
    )
    args = ap.parse_args()

    # --- Check for API Key ---
    if not os.environ.get("OPENAI_API_KEY"):
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        log.error("Please set it before running this script.")
        return 1

    client = OpenAI()

    # --- Load Memories ---
    memory_path = Path(args.memory_file)
    if not memory_path.exists():
        log.error(f"Error: Memory file not found at '{memory_path}'")
        return 1

    log.info("Loading knowledge base...")
    try:
        memories = list(read_jsonl(memory_path))
        log.info(f"✅ Knowledge base loaded with {len(memories)} memories.")
    except Exception as e:
        log.error(f"Error loading or parsing memory file: {e}")
        return 1

    # --- Process Memories for Fine-Tuning ---
    output_path = Path(args.output)
    output_data: List[Dict[str, Any]] = []

    memories_to_process = (
        memories[: args.max_memories] if args.max_memories > 0 else memories
    )

    log.info(
        f"Generating questions for {len(memories_to_process)} memories using {args.question_gen_model}..."
    )

    generated_count = 0
    start_time = time.time()

    with output_path.open("w", encoding="utf-8") as f:
        for i, mem in enumerate(memories_to_process):
            log.info(
                f"Processing memory {i+1}/{len(memories_to_process)}: '{mem.get('title', 'Untitled')}'"
            )

            question = generate_question_for_memory(
                mem, client, args.question_gen_model
            )

            if question:
                training_sample = {
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an expert developer on the ta_lab2 project, providing answers based on its established knowledge base.",
                        },
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": mem["content"]},
                    ]
                }
                f.write(json.dumps(training_sample, ensure_ascii=False) + "\n")
                generated_count += 1
            else:
                log.warning(
                    f"Skipping memory {i+1} due to question generation failure."
                )

            if (i + 1) % 10 == 0:  # Log progress every 10 memories
                elapsed = time.time() - start_time
                log.info(
                    f"Progress: {i+1}/{len(memories_to_process)} processed. Generated {generated_count} samples. Elapsed: {elapsed:.1f}s"
                )

    log.info(
        f"Successfully generated {generated_count} fine-tuning samples to: {output_path}"
    )
    log.info(
        f"Total time for question generation: {time.time() - start_time:.1f} seconds."
    )
    log.info(
        "Remember to manually review and refine the generated training_data.jsonl file for best results!"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
