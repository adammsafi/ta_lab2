"""Smoke tests: verify all migrated data_tools modules import successfully."""
import importlib
import pytest

# Build module list from actual migrated scripts
# Group by category for clarity

ANALYSIS_MODULES = [
    "ta_lab2.tools.data_tools.analysis.generate_function_map",
    "ta_lab2.tools.data_tools.analysis.tree_structure",
    # Added from 14-12 (enhanced function mapper)
    "ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose",
]

DATABASE_MODULES = [
    "ta_lab2.tools.data_tools.database_utils.ema_runners",
]

MEMORY_MODULES = [
    "ta_lab2.tools.data_tools.memory.embed_codebase",
    "ta_lab2.tools.data_tools.memory.embed_memories",
    "ta_lab2.tools.data_tools.memory.generate_memories_from_code",
    "ta_lab2.tools.data_tools.memory.memory_bank_rest",
    "ta_lab2.tools.data_tools.memory.setup_mem0",
    # Added from 14-11 (memory pipeline scripts)
    "ta_lab2.tools.data_tools.memory.generate_memories_from_diffs",
    "ta_lab2.tools.data_tools.memory.generate_memories_from_conversations",
    "ta_lab2.tools.data_tools.memory.instantiate_final_memories",
    "ta_lab2.tools.data_tools.memory.memory_headers_dedup",
    "ta_lab2.tools.data_tools.memory.memory_headers_step1_deterministic",
    "ta_lab2.tools.data_tools.memory.memory_headers_step2_openai_enrich",
    "ta_lab2.tools.data_tools.memory.memory_instantiate_children_step3",
    "ta_lab2.tools.data_tools.memory.memory_bank_engine_rest",
    "ta_lab2.tools.data_tools.memory.memory_build_registry",
    "ta_lab2.tools.data_tools.memory.combine_memories",
]

EXPORT_MODULES = [
    "ta_lab2.tools.data_tools.export.export_chatgpt_conversations",
    "ta_lab2.tools.data_tools.export.chatgpt_export_diff",
    "ta_lab2.tools.data_tools.export.chatgpt_export_clean",
    "ta_lab2.tools.data_tools.export.chatgpt_pipeline",
    "ta_lab2.tools.data_tools.export.process_new_chatgpt_dump",
    "ta_lab2.tools.data_tools.export.extract_kept_chats_from_keepfile",
    "ta_lab2.tools.data_tools.export.process_claude_history",
    "ta_lab2.tools.data_tools.export.convert_claude_code_to_chatgpt_format",
]

GENERATOR_MODULES = [
    "ta_lab2.tools.data_tools.generators.review_generator",
    "ta_lab2.tools.data_tools.generators.category_digest_generator",
    "ta_lab2.tools.data_tools.generators.intelligence_report_generator",
    "ta_lab2.tools.data_tools.generators.finetuning_data_generator",
    "ta_lab2.tools.data_tools.generators.review_triage_generator",
    # Added from 14-12 (commit history generator)
    "ta_lab2.tools.data_tools.generators.generate_commits_txt",
]

PROCESSING_MODULES = [
    # Added from 14-12 (DataFrame consolidation)
    "ta_lab2.tools.data_tools.processing.DataFrame_Consolidation",
]

CONTEXT_MODULES = [
    "ta_lab2.tools.data_tools.context.get_context",
    "ta_lab2.tools.data_tools.context.chat_with_context",
    "ta_lab2.tools.data_tools.context.ask_project",
    "ta_lab2.tools.data_tools.context.create_reasoning_engine",
    "ta_lab2.tools.data_tools.context.query_reasoning_engine",
]

ALL_MODULES = (
    ANALYSIS_MODULES
    + DATABASE_MODULES
    + MEMORY_MODULES
    + EXPORT_MODULES
    + GENERATOR_MODULES
    + PROCESSING_MODULES
    + CONTEXT_MODULES
)


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports_successfully(module_name):
    """Smoke test: each migrated module can be imported without errors."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        # Allow graceful failures for optional dependencies
        if "pip install" in str(e):
            pytest.skip(f"Optional dependency not installed: {e}")
        else:
            pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_has_docstring(module_name):
    """Each module should have a docstring explaining its purpose."""
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        pytest.skip("Module has optional dependency not installed")

    assert module.__doc__ is not None, f"{module_name} missing docstring"
    assert len(module.__doc__.strip()) > 10, f"{module_name} docstring too short"
