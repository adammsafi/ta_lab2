# v0.5.0 Ecosystem Reorganization Guide

**Version:** 1.0.0
**Reorganization period:** 2026-02-02 to 2026-02-04
**Phases covered:** 11-17

This document provides a comprehensive record of the v0.5.0 ecosystem reorganization, which consolidated four external directories (ProjectTT, Data_Tools, fredtools2, fedtools2) into the unified ta_lab2 structure.

## Executive Summary

| Source Directory | Files | Action | Destination |
|------------------|-------|--------|-------------|
| ProjectTT | 62 | Archive + Convert | .archive/documentation/ + docs/ |
| Data_Tools | 51 | Migrate + Archive | src/ta_lab2/tools/data_tools/ + .archive/data_tools/ |
| fredtools2 | 13 | Archive | .archive/external-packages/ |
| fedtools2 | 29 | Archive | .archive/external-packages/ |
| **Total** | **155** | | |

## Key Principles

1. **NO DELETION** - All files preserved in git history and/or .archive/
2. **Memory-first** - All moves tracked in Mem0 memory system
3. **Manifest tracking** - Every archive category has manifest.json with SHA256 checksums
4. **Import continuity** - Migration guide enables updating old imports

## Directory Structure Diagrams

See [docs/diagrams/](diagrams/) for visual representations:
- `before_tree.txt` - Pre-reorganization structure (v0.4.0)
- `after_tree.txt` - Post-reorganization structure (v0.5.0)
- `data_flow.mmd` - Mermaid diagram showing file flow
- `package_structure.mmd` - Internal ta_lab2 organization

## Decision Tracking

All major decisions documented in [docs/manifests/](manifests/):
- `decisions.json` - Structured decision data with $schema validation
- `decisions-schema.json` - JSON Schema for validation
- `DECISIONS.md` - Human-readable rationale

---

## Table of Contents

1. [ProjectTT Migration](#projecttt-migration)
2. [Data_Tools Migration](#data_tools-migration)
3. [fredtools2 Archive](#fredtools2-archive)
4. [fedtools2 Archive](#fedtools2-archive)
5. [Migration Guide](#migration-guide)
6. [Verification](#verification)

---

## ProjectTT Migration

**Decision:** DEC-001 to DEC-015 | **Rationale:** RAT-001
**Phase:** 13 (Documentation Consolidation)
**Total files:** 62

### Strategy

ProjectTT contained planning documents, feature documentation, and analysis spreadsheets in Word and Excel format. These were:
1. **Converted** to Markdown for docs/ integration
2. **Archived** as originals to .archive/documentation/

### File Listing

#### Foundational Documents (14 files)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/Foundational/CoreComponents.docx | docs/architecture/core-components.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/KeyTerms.docx | docs/reference/key-terms.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/ta_lab2_GenesisFiles_Summary.docx | docs/architecture/genesis-files.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/Hysteresis.docx | docs/architecture/hysteresis.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/RegimesInDepth.docx | docs/architecture/regimes-in-depth.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/TimeFrames.docx | docs/reference/timeframes.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/feddata_inDepthSummary_20251110.docx | docs/architecture/feddata-in-depth.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/ChatGPT_VisionQuestions.docx | docs/planning/chatgpt-vision-questions.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/Project Plan.docx | docs/planning/project-plan.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/V1 Project Plan.docx | docs/planning/v1-project-plan.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Foundational/ta_lab2_Vision_Draft_20251111.docx | docs/planning/vision-draft.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Schemas_20260114.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/db_schemas_keys.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/ta_lab2 Workspace v.1.1.docx | docs/planning/workspace.md | .archive/documentation/2026-02-02/ |

#### Feature Documentation - Bars (4 files)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/Features/Bars/DesriptiveDocuments/bar_creation.docx | docs/features/bars/bar-creation.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/Bars/DesriptiveDocuments/bar_implementation.docx | docs/features/bars/bar-implementation.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/Bars/Studies&Scraps/bar_analysis_20260108.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/Bars/Studies&Scraps/bar_data_analysis.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/Bars/Studies&Scraps/bar_tf_analysis.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |

#### Feature Documentation - EMAs (14 files)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_multi_tf.docx | docs/features/emas/ema-multi-tf.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_multi_tf_cal.docx | docs/features/emas/ema-multi-tf-cal.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_multi_tf_cal_anchor.docx | docs/features/emas/ema-multi-tf-cal-anchor.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_overview.docx | docs/features/emas/ema-overview.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_possible_next_steps.docx | docs/features/emas/ema-next-steps.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_comparisson_chart&values.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/DesriptiveDocuments/ema_daily.docx | docs/features/emas/ema-daily.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/EMA_loo.docx | docs/features/emas/ema-loo.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/EMA_thoughts.docx | docs/features/emas/ema-thoughts.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/cmc_ema_multi_tf_cal_us_1W_21P_Approval_20260127.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/dim_tf&ema_alpha_LUT.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/ema_alpha_lookup_20251219.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/ema_analysis_look.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/ema_analysis_review.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Features/EMAs/Studies&Scraps/cmcVSbitstampEMAs.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |

#### Feature Documentation - Memory (1 file)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/Features/Memory/Memory Model.docx | docs/features/memory/memory-model.md | .archive/documentation/2026-02-02/ |

#### Process Documents (4 files)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/ProcessDocuments/Chat Gpt Export Processing – End-to-end Process.docx | docs/guides/chatgpt-export-processing.md | .archive/documentation/2026-02-02/ |
| ProjectTT/ProcessDocuments/Updating Price Data Rough.docx | docs/guides/updating-price-data.md | .archive/documentation/2026-02-02/ |
| ProjectTT/ProcessDocuments/memories.docx | docs/guides/memories.md | .archive/documentation/2026-02-02/ |
| ProjectTT/ProcessDocuments/Update_DB.docx | docs/guides/update-db.md | .archive/documentation/2026-02-02/ |

#### Planning & Status Documents (10 files)

| Original Path | Converted To | Archived To |
|---------------|--------------|-------------|
| ProjectTT/Plans&Status/new_12wk_plan_doc.docx | docs/planning/12wk-plan.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/new_12wk_plan_doc_v2.docx | docs/planning/12wk-plan-v2.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/soFarInMyOwnWords.docx | docs/planning/so-far-own-words.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/soFar_20251108.docx | docs/planning/so-far-20251108.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/status_20251113.docx | docs/planning/status-20251113.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/updates_soFar_20251108 .docx | docs/planning/updates-so-far-20251108.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/new_12wk_plan_table.xlsx | [not converted - spreadsheet] | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/ta_lab2_NextSteps_NeedReview_20251111.docx | docs/planning/next-steps-20251111.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/ta_lab2_Status&ToDos_Review_20251111.docx | docs/planning/status-todos-20251111.md | .archive/documentation/2026-02-02/ |
| ProjectTT/Plans&Status/ta_lab2_someNextStepsToReview_20251111.docx | docs/planning/some-next-steps-20251111.md | .archive/documentation/2026-02-02/ |

#### Analysis & Tracking Spreadsheets (13 files)

| Original Path | Archived To |
|---------------|-------------|
| ProjectTT/TV_DataExportPlay.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/ChatGPT_Convos_Manually_Desc.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/ChatGPT_Convos_Manually_Desc2.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/EMA_Alpha_LUT_Comparisson.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/assets_exchanges_info.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/compare_3_emas'.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/review_refreshMethods_20251201.docx | .archive/documentation/2026-02-02/ |
| ProjectTT/ChatGPT/Look.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/ChatGPT/analysis_look.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/docs_Need_Work_20251128.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/github_code_frequency.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/ta_lab2_TimeFramesChart_20251111.xlsx | .archive/documentation/2026-02-02/ |
| ProjectTT/time_scrap.xlsx | .archive/documentation/2026-02-02/ |

**Note:** Spreadsheet files (.xlsx) were archived without conversion. Word documents (.docx) were converted to Markdown using pypandoc and markdownify.

---

## Data_Tools Migration

**Decision:** DEC-016 to DEC-025 | **Rationale:** RAT-003
**Phase:** 14 (Tools Integration)
**Total files:** 51 (40 migrated, 11 archived)

### Strategy

Data_Tools scripts were categorized into functional groups:
- **Migrated (40):** Reusable tools moved to src/ta_lab2/tools/data_tools/
- **Archived (11):** One-off runners and prototypes moved to .archive/data_tools/

### Migrated Scripts (40)

#### analysis/ (3 scripts)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/generate_function_map.py | src/ta_lab2/tools/data_tools/analysis/generate_function_map.py | AST-based function/method mapper - generates CSV of all functions in repo |
| Data_Tools/tree_structure.py | src/ta_lab2/tools/data_tools/analysis/tree_structure.py | Directory tree visualizations (text, MD, JSON, CSV) and API maps |
| Data_Tools/chatgpt/generate_function_map_with_purpose.py | src/ta_lab2/tools/data_tools/analysis/generate_function_map_with_purpose.py | Enhanced function mapping with purpose inference from docstrings |

#### processing/ (1 script)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/DataFrame_Consolidation.py | src/ta_lab2/tools/data_tools/processing/DataFrame_Consolidation.py | Time-series DataFrame merging utilities with differing granularities |

#### memory/ (16 scripts)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/chatgpt/embed_codebase.py | src/ta_lab2/tools/data_tools/memory/embed_codebase.py | AST-based code chunking and embedding generator for AI memory systems |
| Data_Tools/chatgpt/embed_memories.py | src/ta_lab2/tools/data_tools/memory/embed_memories.py | Embeds memory objects (not code) for semantic search |
| Data_Tools/chatgpt/generate_memories_from_code.py | src/ta_lab2/tools/data_tools/memory/generate_memories_from_code.py | Uses OpenAI to generate structured memories from code chunks |
| Data_Tools/chatgpt/generate_memories_from_conversations.py | src/ta_lab2/tools/data_tools/memory/generate_memories_from_conversations.py | Generates memories from ChatGPT conversation exports |
| Data_Tools/chatgpt/generate_memories_from_diffs.py | src/ta_lab2/tools/data_tools/memory/generate_memories_from_diffs.py | Generates memories from git diffs (58KB, comprehensive pipeline) |
| Data_Tools/chatgpt/combine_memories.py | src/ta_lab2/tools/data_tools/memory/combine_memories.py | Merges multiple memory JSONL files |
| Data_Tools/chatgpt/memory_bank_rest.py | src/ta_lab2/tools/data_tools/memory/memory_bank_rest.py | REST client for Vertex AI Memory Bank |
| Data_Tools/chatgpt/memory_bank_engine_rest.py | src/ta_lab2/tools/data_tools/memory/memory_bank_engine_rest.py | Enhanced Memory Bank client with reasoning engine support |
| Data_Tools/chatgpt/memory_build_registry.py | src/ta_lab2/tools/data_tools/memory/memory_build_registry.py | Builds registry of memory sources and metadata |
| Data_Tools/chatgpt/memory_headers_dedup.py | src/ta_lab2/tools/data_tools/memory/memory_headers_dedup.py | Deduplicates memory headers |
| Data_Tools/chatgpt/memory_headers_step1_deterministic.py | src/ta_lab2/tools/data_tools/memory/memory_headers_step1_deterministic.py | Step 1 of memory header processing - deterministic extraction |
| Data_Tools/chatgpt/memory_headers_step2_openai_enrich.py | src/ta_lab2/tools/data_tools/memory/memory_headers_step2_openai_enrich.py | Step 2 of memory header processing - OpenAI-based enrichment |
| Data_Tools/chatgpt/memory_instantiate_children_step3.py | src/ta_lab2/tools/data_tools/memory/memory_instantiate_children_step3.py | Step 3 of memory processing - instantiates child memories (20KB) |
| Data_Tools/chatgpt/instantiate_final_memories.py | src/ta_lab2/tools/data_tools/memory/instantiate_final_memories.py | Finalizes memory instantiation with validation/formatting |
| Data_Tools/chatgpt/setup_mem0.py | src/ta_lab2/tools/data_tools/memory/setup_mem0.py | Mem0 integration setup script |
| Data_Tools/chatgpt/setup_mem0_direct.py | src/ta_lab2/tools/data_tools/memory/setup_mem0_direct.py | Direct Mem0 setup variant with different initialization approach |

#### export/ (7 scripts)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/chatgpt/export_chatgpt_conversations.py | src/ta_lab2/tools/data_tools/export/export_chatgpt_conversations.py | Converts ChatGPT export JSON to Markdown transcripts and CSV index |
| Data_Tools/chatgpt/chatgpt_export_clean.py | src/ta_lab2/tools/data_tools/export/chatgpt_export_clean.py | Cleans ChatGPT export data |
| Data_Tools/chatgpt/chatgpt_export_diff.py | src/ta_lab2/tools/data_tools/export/chatgpt_export_diff.py | Diffs ChatGPT exports between versions (24KB, comprehensive) |
| Data_Tools/chatgpt/extract_kept_chats_from_keepfile.py | src/ta_lab2/tools/data_tools/export/extract_kept_chats_from_keepfile.py | Extracts specific chats based on keepfile |
| Data_Tools/chatgpt/process_claude_history.py | src/ta_lab2/tools/data_tools/export/process_claude_history.py | Processes Claude conversation history for analysis |
| Data_Tools/chatgpt/process_new_chatgpt_dump.py | src/ta_lab2/tools/data_tools/export/process_new_chatgpt_dump.py | Processes new ChatGPT data dumps |
| Data_Tools/chatgpt/convert_claude_code_to_chatgpt_format.py | src/ta_lab2/tools/data_tools/export/convert_claude_code_to_chatgpt_format.py | Converts Claude Code format to ChatGPT format |

#### context/ (5 scripts)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/chatgpt/ask_project.py | src/ta_lab2/tools/data_tools/context/ask_project.py | RAG tool - semantic search over codebase with LLM chat (17KB) |
| Data_Tools/chatgpt/chat_with_context.py | src/ta_lab2/tools/data_tools/context/chat_with_context.py | Chat interface with semantic context injection |
| Data_Tools/chatgpt/get_context.py | src/ta_lab2/tools/data_tools/context/get_context.py | Retrieves semantic context for queries from ChromaDB |
| Data_Tools/chatgpt/create_reasoning_engine.py | src/ta_lab2/tools/data_tools/context/create_reasoning_engine.py | Creates Vertex AI reasoning engine |
| Data_Tools/chatgpt/query_reasoning_engine.py | src/ta_lab2/tools/data_tools/context/query_reasoning_engine.py | Queries Vertex AI reasoning engine |

#### generators/ (6 scripts)

| Original Path | New Path | Purpose |
|---------------|----------|---------|
| Data_Tools/chatgpt/intelligence_report_generator.py | src/ta_lab2/tools/data_tools/generators/intelligence_report_generator.py | Generates intelligence reports from memory JSONL files |
| Data_Tools/chatgpt/category_digest_generator.py | src/ta_lab2/tools/data_tools/generators/category_digest_generator.py | Generates category-based digests from memories |
| Data_Tools/chatgpt/review_generator.py | src/ta_lab2/tools/data_tools/generators/review_generator.py | Generates code/project reviews |
| Data_Tools/chatgpt/review_triage_generator.py | src/ta_lab2/tools/data_tools/generators/review_triage_generator.py | Generates review triage reports |
| Data_Tools/chatgpt/finetuning_data_generator.py | src/ta_lab2/tools/data_tools/generators/finetuning_data_generator.py | Generates training data for model finetuning |
| Data_Tools/chatgpt/generate_commits_txt.py | src/ta_lab2/tools/data_tools/generators/generate_commits_txt.py | Generates commits.txt from git history |

### Archived Scripts (11)

#### one_offs/ (5 scripts)

| Original Path | Archived To | Reason |
|---------------|-------------|--------|
| Data_Tools/write_daily_emas.py | .archive/data_tools/2026-02-03/one_offs/ | Simple wrapper for existing ta_lab2 functionality |
| Data_Tools/write_multi_tf_emas.py | .archive/data_tools/2026-02-03/one_offs/ | Simple wrapper for existing ta_lab2 functionality |
| Data_Tools/write_ema_multi_tf_cal.py | .archive/data_tools/2026-02-03/one_offs/ | Simple wrapper for existing ta_lab2 functionality |
| Data_Tools/upsert_new_emas_canUpdate.py | .archive/data_tools/2026-02-03/one_offs/ | Wrapper script for existing ta_lab2 functionality |
| Data_Tools/github instruction.py | .archive/data_tools/2026-02-03/one_offs/ | One-off instruction file with git commands |

#### prototypes/ (6 scripts)

| Original Path | Archived To | Reason |
|---------------|-------------|--------|
| Data_Tools/chatgpt/chatgpt_script_look.py | .archive/data_tools/2026-02-03/prototypes/ | Prototype - numbered variations indicate experimentation |
| Data_Tools/chatgpt/chatgpt_script_keep_look.py | .archive/data_tools/2026-02-03/prototypes/ | Prototype - numbered variations indicate experimentation |
| Data_Tools/chatgpt/chatgpt_script_keep_look1.py | .archive/data_tools/2026-02-03/prototypes/ | Prototype - numbered variations indicate experimentation |
| Data_Tools/chatgpt/chatgpt_script_keep_look2.py | .archive/data_tools/2026-02-03/prototypes/ | Prototype - numbered variations indicate experimentation |
| Data_Tools/chatgpt/chatgpt_pipeline.py | .archive/data_tools/2026-02-03/prototypes/ | Experimental pipeline orchestration |
| Data_Tools/chatgpt/main.py | .archive/data_tools/2026-02-03/prototypes/ | Empty stub file, likely unused |
| Data_Tools/chatgpt/run_instantiate_final_memories_tests.py | .archive/data_tools/2026-02-03/prototypes/ | Test script, not production tool |
| Data_Tools/chatgpt/test_code_search.py | .archive/data_tools/2026-02-03/prototypes/ | Test script, not production tool |

**Note:** All migrated scripts are now importable from their new locations under `ta_lab2.tools.data_tools.*`.

---
