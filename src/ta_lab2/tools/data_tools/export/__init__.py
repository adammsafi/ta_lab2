"""ChatGPT and Claude export processing tools.

Tools for:
- Exporting ChatGPT conversations from data exports
- Diffing exports to find new conversations
- Cleaning and normalizing export data
- Processing Claude conversation history
- Format conversion between platforms

Usage examples
--------------

Export conversations:
    python -m ta_lab2.tools.data_tools.export.export_chatgpt_conversations \\
        --in /path/to/conversations.json \\
        --out /path/to/output

Diff two exports:
    python -m ta_lab2.tools.data_tools.export.chatgpt_export_diff \\
        /path/to/old.zip \\
        /path/to/new.zip \\
        --out /path/to/diff_report

Clean export with trash list:
    python -m ta_lab2.tools.data_tools.export.chatgpt_export_clean \\
        /path/to/export.zip \\
        --out /path/to/cleaned \\
        --trash-list /path/to/trash_list.json
"""

from ta_lab2.tools.data_tools.export.export_chatgpt_conversations import (
    export_conversations,
)
from ta_lab2.tools.data_tools.export.chatgpt_export_diff import (
    diff_exports,
)
from ta_lab2.tools.data_tools.export.chatgpt_export_clean import (
    clean_export,
)
from ta_lab2.tools.data_tools.export.extract_kept_chats_from_keepfile import (
    extract_kept_chats,
)
from ta_lab2.tools.data_tools.export.convert_claude_code_to_chatgpt_format import (
    convert_claude_conversations,
)

__all__ = [
    "export_conversations",
    "diff_exports",
    "clean_export",
    "extract_kept_chats",
    "convert_claude_conversations",
]
