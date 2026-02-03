# Data Tools

Scripts migrated from external `Data_Tools/` directory as part of v0.5.0 reorganization.

## Origin

These scripts were originally located in:
- `C:/Users/asafi/Downloads/Data_Tools/` (root-level utilities)
- `C:/Users/asafi/Downloads/Data_Tools/chatgpt/` (AI memory/export tools)

## Structure

| Directory | Purpose | Scripts |
|-----------|---------|---------|
| analysis/ | Code analysis (function maps, tree structure) | 3 |
| processing/ | Data transformation | 1 |
| memory/ | AI memory and embedding tools | 16 |
| export/ | ChatGPT/Claude export processing | 7 |
| context/ | Context retrieval and reasoning | 5 |
| generators/ | Report generation | 6 |

**Total:** 38 scripts migrated (40 planned - excludes database_utils which had no scripts)

## Usage

```python
# Import specific tools
from ta_lab2.tools.data_tools.analysis import generate_function_map
from ta_lab2.tools.data_tools.memory import embed_codebase

# Or import submodule
from ta_lab2.tools.data_tools import memory
from ta_lab2.tools.data_tools import export
```

## Script Inventory

### Analysis (3 scripts)
- `generate_function_map.py` - AST-based function/method mapper (CSV output)
- `generate_function_map_with_purpose.py` - Enhanced function mapper with purpose inference
- `tree_structure.py` - Directory tree visualizations (text, MD, JSON, CSV)

### Processing (1 script)
- `DataFrame_Consolidation.py` - Time-series DataFrame merging utilities

### Memory (16 scripts)
- `embed_codebase.py` - AST-based code chunking and embedding
- `embed_memories.py` - Memory object embedding for semantic search
- `generate_memories_from_code.py` - OpenAI-based memory generation from code
- `generate_memories_from_conversations.py` - Memory generation from ChatGPT exports
- `generate_memories_from_diffs.py` - Git diff memory generation (58KB, largest script)
- `combine_memories.py` - Memory JSONL file merger
- `memory_bank_rest.py` - Vertex AI Memory Bank REST client
- `memory_bank_engine_rest.py` - Memory Bank with reasoning engine support
- `memory_build_registry.py` - Memory source registry builder
- `memory_headers_dedup.py` - Memory header deduplication
- `memory_headers_step1_deterministic.py` - Deterministic header extraction
- `memory_headers_step2_openai_enrich.py` - OpenAI-based header enrichment
- `memory_instantiate_children_step3.py` - Child memory instantiation (20KB)
- `instantiate_final_memories.py` - Final memory processing (16KB)
- `setup_mem0.py` - Mem0 integration setup
- `setup_mem0_direct.py` - Direct Mem0 setup variant

### Export (7 scripts)
- `export_chatgpt_conversations.py` - ChatGPT export to Markdown/CSV
- `chatgpt_export_clean.py` - Export data cleaning
- `chatgpt_export_diff.py` - Export version comparison (24KB)
- `extract_kept_chats_from_keepfile.py` - Chat filtering and extraction
- `process_claude_history.py` - Claude conversation processor
- `process_new_chatgpt_dump.py` - New ChatGPT dump processor
- `convert_claude_code_to_chatgpt_format.py` - Format converter

### Context (5 scripts)
- `ask_project.py` - RAG-based project Q&A system (17KB)
- `chat_with_context.py` - Context-aware chat interface
- `get_context.py` - Semantic context retrieval
- `create_reasoning_engine.py` - Vertex AI reasoning engine creation
- `query_reasoning_engine.py` - Reasoning engine query interface

### Generators (6 scripts)
- `intelligence_report_generator.py` - Memory-based intelligence reports
- `category_digest_generator.py` - Category-based digests
- `review_generator.py` - Code/project review generator
- `review_triage_generator.py` - Review triage reports
- `finetuning_data_generator.py` - Model finetuning dataset generator
- `generate_commits_txt.py` - Git commit history exporter

## Archived Scripts

Scripts not migrated (prototypes, one-offs, duplicates) are preserved in:
- `.archive/data_tools/2026-02-02/one_offs/` - 5 scripts
- `.archive/data_tools/2026-02-02/prototypes/` - 6 scripts

See archive manifest for details.

## External Dependencies

These scripts require external packages (to be added to pyproject.toml):
- `openai` - Used by 16 memory scripts, RAG tools, generators
- `chromadb` - Used by memory/embedding tools, context search
- `mem0` - Used by memory setup scripts
- `google.auth` + `google.auth.transport.requests` - Used by Vertex AI integrations
- `requests` - Used by REST clients
- `pandas` - Used by processing tools

## Migration Phase

- **Phase:** 14 (Tools Integration)
- **Plan:** 14-02 (Package Structure Creation)
- **Date:** 2026-02-02
- **Requirements:** TOOL-01, TOOL-02, TOOL-03
- **Discovery:** See `.planning/phases/14-tools-integration/14-01-discovery.json`
