#!/usr/bin/env python3
"""
Extract memories from ChatGPT/Claude conversations using GPT-4.

Usage:
    OPENAI_API_KEY=key python generate_memories_from_conversations.py \
        --input-file conversations.json \
        --output-file memories.jsonl \
        --batch-size 10
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    from openai import OpenAI
except ImportError:
    print("OpenAI library required: pip install openai")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


MEMORY_EXTRACTION_PROMPT = """You are a memory extraction assistant. Analyze the conversation and extract key memories.

Extract memories about:
- **Decisions**: Technical choices, architectural decisions, approach selections
- **Facts**: Project details, configurations, database schemas, API endpoints
- **Procedures**: How to do things, workflows, deployment steps
- **Preferences**: User preferences, coding standards, conventions
- **Context**: Project names, technologies, frameworks used

For each memory, provide:
1. **title**: Concise summary (10-15 words)
2. **content**: Detailed description (2-4 sentences)
3. **type**: One of [decision, fact, procedure, preference, context, other]

Return a JSON array of memories:
```json
[
  {
    "title": "...",
    "content": "...",
    "type": "decision"
  },
  ...
]
```

Only extract significant memories. Skip:
- Greetings, small talk
- Error messages without resolution
- Incomplete thoughts
- Clarifying questions without answers

Conversation:
"""


def extract_conversation_text(conversation: Dict[str, Any]) -> str:
    """Extract text from a conversation object."""

    text_parts = []
    mapping = conversation.get("mapping", {})

    # Traverse message tree
    for msg_id, msg_data in mapping.items():
        message = msg_data.get("message", {})

        if not message:
            continue

        role = message.get("author", {}).get("role", "unknown")
        content = message.get("content", {})

        # Extract text parts
        if isinstance(content, dict):
            parts = content.get("parts", [])
            if parts:
                text = "\n".join(str(p) for p in parts if p)
                if text.strip():
                    text_parts.append(f"{role.upper()}: {text}")
        elif isinstance(content, str):
            if content.strip():
                text_parts.append(f"{role.upper()}: {content}")

    return "\n\n".join(text_parts)


def extract_memories_from_conversation(
    client: OpenAI,
    conversation: Dict[str, Any],
    model: str = "gpt-4o-mini"
) -> List[Dict[str, Any]]:
    """Extract memories from a single conversation using GPT-4."""

    conv_text = extract_conversation_text(conversation)

    if not conv_text or len(conv_text) < 100:
        return []

    # Truncate if too long (keep first 20K chars)
    if len(conv_text) > 20000:
        conv_text = conv_text[:20000] + "\n\n[...truncated...]"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a memory extraction assistant. Extract key technical memories from conversations."},
                {"role": "user", "content": MEMORY_EXTRACTION_PROMPT + conv_text}
            ],
            temperature=0.3,
        )

        result_text = response.choices[0].message.content or ""

        # Extract JSON array from response
        # Try to find JSON array in the response
        import re
        json_match = re.search(r'\[\s*\{.*\}\s*\]', result_text, re.DOTALL)

        if json_match:
            memories = json.loads(json_match.group())
            return memories
        else:
            log.warning("No valid JSON array found in GPT response")
            return []

    except Exception as e:
        log.error(f"Error extracting memories: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Extract memories from conversations")
    parser.add_argument("--input-file", required=True, help="Input conversations JSON file")
    parser.add_argument("--output-file", required=True, help="Output memories JSONL file")
    parser.add_argument("--batch-size", type=int, default=10, help="Process N conversations at a time")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model to use")

    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        log.error("OPENAI_API_KEY not set")
        return 1

    client = OpenAI()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        return 1

    log.info(f"Loading conversations from: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        conversations = json.load(f)

    if not isinstance(conversations, list):
        log.error("Expected JSON array of conversations")
        return 1

    log.info(f"Loaded {len(conversations)} conversations")

    # Process conversations
    all_memories = []

    for i, conv in enumerate(conversations, 1):
        conv_id = conv.get("id", f"unknown_{i}")
        conv_title = conv.get("title", "Untitled")

        log.info(f"Processing conversation {i}/{len(conversations)}: {conv_title[:50]}")

        memories = extract_memories_from_conversation(client, conv, model=args.model)

        if not memories:
            log.info(f"  No memories extracted")
            continue

        log.info(f"  Extracted {len(memories)} memories")

        # Add metadata to memories
        for mem in memories:
            mem_id = hashlib.md5(
                f"{conv_id}_{mem.get('title', '')}".encode()
            ).hexdigest()[:16]

            mem["memory_id"] = f"claude_{conv_id}_{mem_id}"
            mem["source"] = "claude_code"
            mem["conversation_id"] = conv_id
            mem["conversation_title"] = conv_title

            all_memories.append(mem)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for mem in all_memories:
            f.write(json.dumps(mem) + "\n")

    log.info(f"\nExtracted {len(all_memories)} total memories from {len(conversations)} conversations")
    log.info(f"Output: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
