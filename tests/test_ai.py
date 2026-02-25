"""Tests for AI providers and context builder."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from mailsweep.db.schema import init_db
from mailsweep.db.repository import AccountRepository, FolderRepository, MessageRepository
from mailsweep.models.account import Account, AuthType
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message
from mailsweep.ai.providers import (
    OpenAICompatProvider,
    AnthropicProvider,
    LLMError,
    create_provider,
    PROVIDER_PRESETS,
)
from mailsweep.ai.context import build_mailbox_context


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def populated_db(conn):
    """Create an account with multiple folders and messages for context testing."""
    acct_repo = AccountRepository(conn)
    folder_repo = FolderRepository(conn)
    msg_repo = MessageRepository(conn)

    acct = acct_repo.upsert(Account(
        display_name="Test",
        host="imap.test.com",
        port=993,
        username="test@test.com",
        auth_type=AuthType.PASSWORD,
    ))

    inbox = folder_repo.upsert(Folder(
        account_id=acct.id, name="INBOX", uid_validity=1,
        message_count=3, total_size_bytes=3000,
    ))
    imp = folder_repo.upsert(Folder(
        account_id=acct.id, name="IMP", uid_validity=1,
        message_count=2, total_size_bytes=2000,
    ))
    imp_banks = folder_repo.upsert(Folder(
        account_id=acct.id, name="IMP/Banks", uid_validity=1,
        message_count=1, total_size_bytes=500,
    ))

    # Messages in INBOX
    msg_repo.upsert_batch([
        Message(uid=1, folder_id=inbox.id, message_id="<a@test>",
                from_addr="Alice <alice@bank.com>", to_addr="test@test.com",
                subject="Bank Alert", date=datetime(2025, 1, 15, tzinfo=timezone.utc),
                size_bytes=1000, has_attachment=False),
        Message(uid=2, folder_id=inbox.id, message_id="<b@test>",
                from_addr="bob@shop.com", to_addr="test@test.com",
                subject="Order Confirmation", date=datetime(2025, 6, 1, tzinfo=timezone.utc),
                size_bytes=1500, has_attachment=True, attachment_names=["receipt.pdf"]),
        Message(uid=3, folder_id=inbox.id, message_id="<c@test>",
                from_addr="Alice <alice@bank.com>", to_addr="test@test.com",
                subject="Statement", date=datetime(2024, 3, 10, tzinfo=timezone.utc),
                size_bytes=500, has_attachment=False),
    ])
    # Messages in IMP
    msg_repo.upsert_batch([
        Message(uid=10, folder_id=imp.id, message_id="<d@test>",
                from_addr="Alice <alice@bank.com>", to_addr="test@test.com",
                subject="Loan Update", date=datetime(2025, 2, 20, tzinfo=timezone.utc),
                size_bytes=1200, has_attachment=False),
        Message(uid=11, folder_id=imp.id, message_id="<e@test>",
                from_addr="carol@work.com", to_addr="test@test.com",
                subject="Project Plan", date=datetime(2025, 5, 5, tzinfo=timezone.utc),
                size_bytes=800, has_attachment=False),
    ])
    # Messages in IMP/Banks
    msg_repo.upsert_batch([
        Message(uid=20, folder_id=imp_banks.id, message_id="<f@test>",
                from_addr="Alice <alice@bank.com>", to_addr="test@test.com",
                subject="Card Alert", date=datetime(2025, 7, 1, tzinfo=timezone.utc),
                size_bytes=500, has_attachment=False),
    ])

    # Recompute folder stats
    for f in [inbox, imp, imp_banks]:
        folder_repo.update_stats(f.id)

    return acct, conn


# ── Provider Tests ───────────────────────────────────────────────────────────

class TestOpenAICompatProvider:
    def test_chat_success(self):
        """Mock a successful OpenAI-compatible chat completion."""
        provider = OpenAICompatProvider(
            base_url="http://localhost:11434/v1",
            api_key="",
            model="llama3.2",
        )
        mock_response = json.dumps({
            "choices": [{"message": {"content": "Hello! I can help with that."}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.chat([{"role": "user", "content": "Hi"}])

        assert result == "Hello! I can help with that."

    def test_chat_with_system_prompt(self):
        provider = OpenAICompatProvider(
            base_url="http://localhost:8080/v1",
            api_key="test-key",
            model="test-model",
        )
        mock_response = json.dumps({
            "choices": [{"message": {"content": "response"}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            provider.chat(
                [{"role": "user", "content": "test"}],
                system="You are helpful.",
            )
            # Verify the request was made with Authorization header
            call_args = mock_open.call_args
            req = call_args[0][0]
            assert req.get_header("Authorization") == "Bearer test-key"
            # Verify system message is first
            body = json.loads(req.data.decode("utf-8"))
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][0]["content"] == "You are helpful."

    def test_chat_http_error(self):
        provider = OpenAICompatProvider(
            base_url="http://localhost:11434/v1",
            api_key="",
            model="llama3.2",
        )
        import urllib.error
        error = urllib.error.HTTPError(
            "http://localhost:11434/v1/chat/completions",
            500, "Server Error", {}, MagicMock(read=lambda: b"error")
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(LLMError, match="HTTP 500"):
                provider.chat([{"role": "user", "content": "Hi"}])


class TestAnthropicProvider:
    def test_chat_success(self):
        provider = AnthropicProvider(api_key="sk-test", model="claude-3-haiku")
        mock_response = json.dumps({
            "content": [{"type": "text", "text": "Anthropic response"}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = provider.chat(
                [{"role": "user", "content": "test"}],
                system="Be helpful.",
            )
            assert result == "Anthropic response"
            req = mock_open.call_args[0][0]
            assert req.get_header("X-api-key") == "sk-test"
            body = json.loads(req.data.decode("utf-8"))
            assert body["system"] == "Be helpful."


class TestCreateProvider:
    def test_ollama_preset(self):
        p = create_provider("ollama", "http://localhost:11434/v1", "", "llama3.2")
        assert isinstance(p, OpenAICompatProvider)

    def test_anthropic_no_key_raises(self):
        with pytest.raises(LLMError, match="API key"):
            create_provider("anthropic", "", "", "claude-3-haiku")

    def test_anthropic_with_key(self):
        p = create_provider("anthropic", "", "sk-test", "claude-3-haiku")
        assert isinstance(p, AnthropicProvider)

    def test_custom_no_url_raises(self):
        with pytest.raises(LLMError, match="Base URL"):
            create_provider("custom", "", "", "model")

    def test_presets_have_expected_keys(self):
        for name in ("ollama", "openai", "anthropic", "custom"):
            preset = PROVIDER_PRESETS[name]
            assert "base_url" in preset
            assert "api_key" in preset
            assert "model" in preset


# ── Context Builder Tests ────────────────────────────────────────────────────

class TestBuildMailboxContext:
    def test_basic_context(self, populated_db):
        acct, conn = populated_db
        ctx = build_mailbox_context(conn, account_id=acct.id)
        assert "test@test.com" in ctx
        assert "INBOX" in ctx
        assert "IMP" in ctx
        assert "IMP/Banks" in ctx

    def test_contains_folder_tree(self, populated_db):
        acct, conn = populated_db
        ctx = build_mailbox_context(conn, account_id=acct.id)
        assert "Folder Tree" in ctx

    def test_contains_top_senders(self, populated_db):
        acct, conn = populated_db
        ctx = build_mailbox_context(conn, account_id=acct.id)
        assert "Top Senders" in ctx
        assert "alice@bank.com" in ctx

    def test_contains_cross_folder_overlap(self, populated_db):
        acct, conn = populated_db
        ctx = build_mailbox_context(conn, account_id=acct.id)
        # alice@bank.com appears in INBOX, IMP, and IMP/Banks
        assert "Cross-Folder" in ctx
        assert "alice@bank.com" in ctx

    def test_with_folder_filter(self, populated_db):
        acct, conn = populated_db
        folder_repo = FolderRepository(conn)
        imp = folder_repo.get_by_name(acct.id, "IMP")
        ctx = build_mailbox_context(conn, account_id=acct.id, folder_ids=[imp.id])
        assert "IMP" in ctx

    def test_no_account(self, conn):
        ctx = build_mailbox_context(conn, account_id=999)
        # Should still produce something (picks first account or no-data message)
        assert isinstance(ctx, str)


# ── Repository Query Tests ───────────────────────────────────────────────────

class TestRepositoryAIQueries:
    def test_get_folder_tree_summary(self, populated_db):
        acct, conn = populated_db
        msg_repo = MessageRepository(conn)
        rows = msg_repo.get_folder_tree_summary(acct.id)
        assert len(rows) == 3
        names = [r["name"] for r in rows]
        assert "INBOX" in names
        assert "IMP" in names
        assert "IMP/Banks" in names
        # Verify date ranges exist
        inbox_row = next(r for r in rows if r["name"] == "INBOX")
        assert inbox_row["min_date"] is not None
        assert inbox_row["max_date"] is not None

    def test_get_cross_folder_senders(self, populated_db):
        acct, conn = populated_db
        msg_repo = MessageRepository(conn)
        cross = msg_repo.get_cross_folder_senders(acct.id, min_folders=2)
        # alice@bank.com appears in 3 folders
        assert len(cross) >= 1
        alice = next(r for r in cross if r["sender_email"] == "alice@bank.com")
        assert alice["folder_count"] >= 2

    def test_get_top_senders_per_folder(self, populated_db):
        acct, conn = populated_db
        msg_repo = MessageRepository(conn)
        folder_repo = FolderRepository(conn)
        inbox = folder_repo.get_by_name(acct.id, "INBOX")
        top = msg_repo.get_top_senders_per_folder(inbox.id, limit=5)
        assert len(top) >= 1
        # alice@bank.com has 2 msgs in INBOX, bob@shop.com has 1
        assert top[0]["sender_email"] == "alice@bank.com"
        assert top[0]["message_count"] == 2
