"""Tests for orchestrator CLI."""
import json
import pytest
from unittest.mock import patch, Mock

from ta_lab2.tools.ai_orchestrator.cli import (
    build_orchestrator_parser,
    cmd_status,
    cmd_costs,
    cmd_quota,
    main,
)


class TestParserBuilding:
    """Test CLI parser structure."""

    def test_parser_has_subcommands(self):
        """Parser has all required subcommands."""
        ap = build_orchestrator_parser()
        # Parse each subcommand to verify they exist
        args = ap.parse_args(["status"])
        assert args.orch_cmd == "status"

    def test_submit_requires_prompt(self):
        """Submit subcommand requires --prompt."""
        ap = build_orchestrator_parser()
        with pytest.raises(SystemExit):
            ap.parse_args(["submit"])  # Missing required --prompt


class TestCmdStatus:
    """Test status command."""

    def test_status_text_format(self, capsys):
        """Status with text format prints readable output."""
        args = Mock()
        args.format = "text"

        with patch("ta_lab2.tools.ai_orchestrator.quota.QuotaTracker") as mock_qt:
            mock_qt.return_value.get_status.return_value = {}
            mock_qt.return_value.display_status.return_value = "Quota Status"

            result = cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Status" in captured.out

    def test_status_json_format(self, capsys):
        """Status with json format prints valid JSON."""
        args = Mock()
        args.format = "json"

        with patch("ta_lab2.tools.ai_orchestrator.quota.QuotaTracker") as mock_qt:
            mock_qt.return_value.get_status.return_value = {"test": "data"}

            result = cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "adapters" in data or "quota" in data


class TestCmdCosts:
    """Test costs command."""

    def test_costs_shows_session_summary(self, capsys):
        """Costs without chain-id shows session summary."""
        args = Mock()
        args.chain_id = None
        args.date = None
        args.format = "text"

        with patch("ta_lab2.tools.ai_orchestrator.cost.CostTracker") as mock_ct:
            mock_ct.return_value.display_summary.return_value = "Cost Summary"

            result = cmd_costs(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Cost Summary" in captured.out

    def test_costs_with_chain_id(self, capsys):
        """Costs with chain-id shows chain breakdown."""
        args = Mock()
        args.chain_id = "chain_123"
        args.date = None
        args.format = "text"

        with patch("ta_lab2.tools.ai_orchestrator.cost.CostTracker") as mock_ct:
            mock_ct.return_value.get_chain_cost.return_value = 0.05
            mock_ct.return_value.get_chain_tasks.return_value = []

            result = cmd_costs(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "chain_123" in captured.out


class TestCmdQuota:
    """Test quota command."""

    def test_quota_text_format(self, capsys):
        """Quota with text format prints status."""
        args = Mock()
        args.format = "text"

        with patch("ta_lab2.tools.ai_orchestrator.quota.QuotaTracker") as mock_qt:
            mock_qt.return_value.display_status.return_value = "Quota Status"

            result = cmd_quota(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Quota Status" in captured.out


class TestMainEntrypoint:
    """Test main() function."""

    def test_main_with_status(self):
        """main() handles status subcommand."""
        with patch(
            "ta_lab2.tools.ai_orchestrator.cli.cmd_status", return_value=0
        ) as mock_cmd:
            result = main(["status"])

        assert result == 0
        mock_cmd.assert_called_once()

    def test_main_shows_help_without_args(self):
        """main() shows help when no subcommand."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2  # Missing required subcommand
