"""
Report and content generation tools.

Generators for:
- Code/content reviews (review_generator.py)
- Category digests (category_digest_generator.py)
- Intelligence reports (intelligence_report_generator.py)
- Fine-tuning training data (finetuning_data_generator.py)
- Review triage (review_triage_generator.py)

Dependencies:
- OpenAI (for content generation): pip install openai

Usage:
    # CLI usage
    python -m ta_lab2.tools.data_tools.generators.review_generator --input memories.jsonl --output review.md
    python -m ta_lab2.tools.data_tools.generators.category_digest_generator --input memories.jsonl --output digest.md
    python -m ta_lab2.tools.data_tools.generators.intelligence_report_generator --input memories.jsonl --output report.md
    python -m ta_lab2.tools.data_tools.generators.finetuning_data_generator --memory-file memories.jsonl --output training.jsonl
    python -m ta_lab2.tools.data_tools.generators.review_triage_generator --review-file review_queue.jsonl --output triage.md
"""

__all__ = [
    "review_generator",
    "category_digest_generator",
    "intelligence_report_generator",
    "finetuning_data_generator",
    "review_triage_generator",
]
