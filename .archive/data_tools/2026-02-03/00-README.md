# Archived Data_Tools Scripts

Scripts from Data_Tools that were not migrated to ta_lab2/tools/data_tools/.

## Archive Date
2026-02-03

## Reason for Archiving

| Category | Scripts | Reason |
|----------|---------|--------|
| prototypes | chatgpt_script_look*.py, chatgpt_script_keep_look*.py | Numbered variations indicate prototyping |
| prototypes | chatgpt_pipeline.py, main.py | Experimental/stub files |
| prototypes | run_instantiate_final_memories_tests.py, test_code_search.py | Test files, not production tools |
| one_offs | write_daily_emas.py, write_multi_tf_emas.py, write_ema_multi_tf_cal.py | Simple wrappers for existing ta_lab2 functionality |
| one_offs | upsert_new_emas_canUpdate.py | Wrapper for existing ta_lab2 functionality |
| one_offs | github instruction.py | One-off instruction file |

## Retrieval

These files are preserved in git history. To access:
```bash
# View file at archive time
git show HEAD:.archive/data_tools/2026-02-03/prototypes/script.py

# Or checkout specific file
git checkout HEAD -- .archive/data_tools/2026-02-03/prototypes/script.py
```

## Related

- Migrated scripts: src/ta_lab2/tools/data_tools/
- Migration phase: 14 (Tools Integration)
- Discovery manifest: .planning/phases/14-tools-integration/14-01-discovery.json
