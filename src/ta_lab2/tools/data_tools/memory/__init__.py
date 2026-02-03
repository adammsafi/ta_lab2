"""Memory tools migrated from Data_Tools.

Scripts in this module:
- embed_codebase.py: AST-based code chunking and embedding
- embed_memories.py: Memory object embedding for semantic search
- generate_memories_from_code.py: OpenAI-based memory generation from code
- generate_memories_from_conversations.py: Memory generation from ChatGPT exports
- generate_memories_from_diffs.py: Git diff memory generation
- combine_memories.py: Memory JSONL file merger
- memory_bank_rest.py: Vertex AI Memory Bank REST client
- memory_bank_engine_rest.py: Memory Bank with reasoning engine support
- memory_build_registry.py: Memory source registry builder
- memory_headers_dedup.py: Memory header deduplication
- memory_headers_step1_deterministic.py: Deterministic header extraction
- memory_headers_step2_openai_enrich.py: OpenAI-based header enrichment
- memory_instantiate_children_step3.py: Child memory instantiation
- instantiate_final_memories.py: Final memory processing
- setup_mem0.py: Mem0 integration setup
- setup_mem0_direct.py: Direct Mem0 setup variant
"""
