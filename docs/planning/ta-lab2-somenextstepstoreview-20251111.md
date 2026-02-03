---
title: "ta_lab2_someNextStepsToReview_20251111"
author: "Adam Safi"
created: 2025-11-03T03:58:00+00:00
modified: 2025-11-11T11:46:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\ta_lab2_someNextStepsToReview_20251111.docx"
original_size_bytes: 15466
---
1. **Documentation Automation**

   * Merge the function-map output into Markdown/HTML docs (like a
     mini Sphinx-style index).
   * Each function row → module.html#function\_name block.
2. **Code Quality & Style**

   * Add ruff or black to pyproject.toml for consistency.
   * Type-hint coverage pass (mypy or pyright).
3. **Versioned Release**

   * Tag as v0.1.0 once the function-map and doc generator
     stabilize.
   * Publish to TestPyPI for internal install tests.
4. **Pipeline Enhancements**

   * Add feature caching (joblib or parquet) for multi-TF
     aggregation.
   * Integrate volatility regime overlay and momentum
     clustering.
5. **Visualization**

   * Build one viz.show\_summary(df) function that shows price, EMA,
     trend, and volatility regimes together.
6. **Docs/Examples**

   * Add a notebooks/ directory with simple demos: load BTC, compute
     EMAs, plot, interpret regimes.
