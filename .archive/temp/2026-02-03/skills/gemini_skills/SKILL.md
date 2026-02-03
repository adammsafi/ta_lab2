---
name: file-reader-and-analyzer
description: Enables the AI to read, search, and analyze file contents within the project repository to facilitate discussion and understanding.
version: 0.1.0
---

## File Reader and Analyzer Skill

This skill provides the AI with enhanced capabilities to interact with the project's file system, allowing for detailed code analysis, content retrieval, and structural understanding.

### Capabilities:

*   **Read File Content:** The AI can read the content of any specified file within the repository.
*   **Search File Content:** The AI can search for specific patterns or strings across multiple files in the repository.
*   **Glob Files:** The AI can find files matching specific patterns (e.g., all Python files, all Markdown files).

### Usage:

When you want to discuss a file, ask the AI to:

*   "Read the content of `path/to/your/file.py`"
*   "Search for the function `my_function` in `src/`"
*   "List all markdown files in the `docs/` directory"

The AI will use its internal tools to perform these actions and then use the retrieved information to engage in a conversation about your codebase, answer questions, or assist with development tasks.

This skill does not introduce new tools, but rather formalizes the AI's ability to use its existing file system interaction tools (`read_file`, `search_file_content`, `glob`) for analytical and conversational purposes related to your project's files.
