"""Tests for DB schema + repositories (in-memory SQLite)."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from mailsweep.db.schema import init_db
from mailsweep.db.repository import AccountRepository, FolderRepository, MessageRepository
from mailsweep.models.account import Account, AuthType
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def account_repo(conn):
    return AccountRepository(conn)


@pytest.fixture
def folder_repo(conn):
    return FolderRepository(conn)


@pytest.fixture
def msg_repo(conn):
    return MessageRepository(conn)


@pytest.fixture
def sample_account(account_repo):
    acc = Account(
        display_name="Test Account",
        host="imap.example.com",
        port=993,
        username="user@example.com",
        auth_type=AuthType.PASSWORD,
        use_ssl=True,
    )
    return account_repo.upsert(acc)


@pytest.fixture
def sample_folder(folder_repo, sample_account):
    f = Folder(
        account_id=sample_account.id,
        name="INBOX",
        uid_validity=12345,
    )
    return folder_repo.upsert(f)


class TestAccountRepository:
    def test_upsert_returns_id(self, account_repo):
        acc = Account(
            display_name="Alice",
            host="imap.gmail.com",
            port=993,
            username="alice@gmail.com",
            auth_type=AuthType.PASSWORD,
            use_ssl=True,
        )
        saved = account_repo.upsert(acc)
        assert saved.id is not None
        assert saved.id > 0

    def test_get_all(self, account_repo):
        for i in range(3):
            account_repo.upsert(Account(
                display_name=f"User {i}",
                host=f"imap{i}.example.com",
                port=993,
                username=f"user{i}@example.com",
                auth_type=AuthType.PASSWORD,
                use_ssl=True,
            ))
        accounts = account_repo.get_all()
        assert len(accounts) == 3

    def test_upsert_updates_existing(self, account_repo):
        acc = Account(
            display_name="Original",
            host="imap.example.com",
            port=993,
            username="same@example.com",
            auth_type=AuthType.PASSWORD,
            use_ssl=True,
        )
        saved1 = account_repo.upsert(acc)
        acc2 = Account(
            display_name="Updated",
            host="imap.example.com",
            port=993,
            username="same@example.com",
            auth_type=AuthType.PASSWORD,
            use_ssl=True,
        )
        saved2 = account_repo.upsert(acc2)
        assert saved2.id == saved1.id
        retrieved = account_repo.get_by_id(saved1.id)
        assert retrieved.display_name == "Updated"

    def test_delete(self, account_repo):
        acc = account_repo.upsert(Account(
            display_name="ToDelete",
            host="imap.del.com",
            port=993,
            username="del@del.com",
            auth_type=AuthType.PASSWORD,
            use_ssl=True,
        ))
        account_repo.delete(acc.id)
        assert account_repo.get_by_id(acc.id) is None


class TestFolderRepository:
    def test_upsert_folder(self, folder_repo, sample_account):
        f = Folder(account_id=sample_account.id, name="Sent")
        saved = folder_repo.upsert(f)
        assert saved.id is not None

    def test_get_by_account(self, folder_repo, sample_account):
        for name in ["INBOX", "Sent", "Trash"]:
            folder_repo.upsert(Folder(account_id=sample_account.id, name=name))
        folders = folder_repo.get_by_account(sample_account.id)
        assert len(folders) == 3
        assert {f.name for f in folders} == {"INBOX", "Sent", "Trash"}

    def test_invalidate_clears_uid_validity(self, folder_repo, msg_repo, sample_folder):
        msgs = [Message(uid=i, folder_id=sample_folder.id, size_bytes=1000) for i in range(5)]
        msg_repo.upsert_batch(msgs)
        folder_repo.invalidate(sample_folder.id)
        updated = folder_repo.get_by_id(sample_folder.id)
        assert updated.uid_validity == 0
        assert len(msg_repo.get_uids_for_folder(sample_folder.id)) == 0

    def test_update_stats(self, folder_repo, msg_repo, sample_folder):
        msgs = [Message(uid=i, folder_id=sample_folder.id, size_bytes=1024) for i in range(10)]
        msg_repo.upsert_batch(msgs)
        folder_repo.update_stats(sample_folder.id)
        updated = folder_repo.get_by_id(sample_folder.id)
        assert updated.message_count == 10
        assert updated.total_size_bytes == 10240


class TestMessageRepository:
    def test_upsert_batch(self, msg_repo, sample_folder):
        msgs = [
            Message(uid=i, folder_id=sample_folder.id, from_addr=f"user{i}@x.com",
                    subject=f"Subject {i}", size_bytes=i * 1024)
            for i in range(1, 11)
        ]
        msg_repo.upsert_batch(msgs)
        uids = msg_repo.get_uids_for_folder(sample_folder.id)
        assert uids == set(range(1, 11))

    def test_upsert_updates_on_conflict(self, msg_repo, sample_folder):
        msg = Message(uid=42, folder_id=sample_folder.id, subject="Original", size_bytes=1000)
        msg_repo.upsert_batch([msg])
        msg2 = Message(uid=42, folder_id=sample_folder.id, subject="Updated", size_bytes=2000)
        msg_repo.upsert_batch([msg2])
        results = msg_repo.query_messages(folder_ids=[sample_folder.id])
        assert len(results) == 1
        assert results[0].subject == "Updated"
        assert results[0].size_bytes == 2000

    def test_delete_uids(self, msg_repo, sample_folder):
        msgs = [Message(uid=i, folder_id=sample_folder.id, size_bytes=100) for i in range(5)]
        msg_repo.upsert_batch(msgs)
        msg_repo.delete_uids(sample_folder.id, [1, 3])
        uids = msg_repo.get_uids_for_folder(sample_folder.id)
        assert uids == {0, 2, 4}

    def test_query_with_size_filter(self, msg_repo, sample_folder):
        msgs = [
            Message(uid=1, folder_id=sample_folder.id, size_bytes=500_000),
            Message(uid=2, folder_id=sample_folder.id, size_bytes=1_000_000),
            Message(uid=3, folder_id=sample_folder.id, size_bytes=100_000),
        ]
        msg_repo.upsert_batch(msgs)
        large = msg_repo.query_messages(folder_ids=[sample_folder.id], size_min=600_000)
        assert len(large) == 1
        assert large[0].uid == 2

    def test_query_with_attachment_filter(self, msg_repo, sample_folder):
        msgs = [
            Message(uid=1, folder_id=sample_folder.id, has_attachment=True,
                    attachment_names=["file.pdf"], size_bytes=1000),
            Message(uid=2, folder_id=sample_folder.id, has_attachment=False, size_bytes=500),
        ]
        msg_repo.upsert_batch(msgs)
        att = msg_repo.query_messages(folder_ids=[sample_folder.id], has_attachment=True)
        assert len(att) == 1
        assert att[0].uid == 1

    def test_query_from_filter(self, msg_repo, sample_folder):
        msgs = [
            Message(uid=1, folder_id=sample_folder.id, from_addr="alice@example.com", size_bytes=100),
            Message(uid=2, folder_id=sample_folder.id, from_addr="bob@example.com", size_bytes=100),
        ]
        msg_repo.upsert_batch(msgs)
        results = msg_repo.query_messages(folder_ids=[sample_folder.id], from_filter="alice")
        assert len(results) == 1
        assert results[0].from_addr == "alice@example.com"

    def test_sender_summary(self, msg_repo, sample_folder):
        msgs = [
            Message(uid=1, folder_id=sample_folder.id, from_addr="alice@x.com", size_bytes=1000),
            Message(uid=2, folder_id=sample_folder.id, from_addr="alice@x.com", size_bytes=2000),
            Message(uid=3, folder_id=sample_folder.id, from_addr="bob@x.com", size_bytes=500),
        ]
        msg_repo.upsert_batch(msgs)
        summary = msg_repo.get_sender_summary(folder_ids=[sample_folder.id])
        assert len(summary) == 2
        alice = next(s for s in summary if s["from_addr"] == "alice@x.com")
        assert alice["message_count"] == 2
        assert alice["total_size_bytes"] == 3000


class TestUnlabelled:
    """Tests for virtual 'Unlabelled' folder feature."""

    @pytest.fixture
    def gmail_account(self, account_repo):
        acc = Account(
            display_name="Gmail",
            host="imap.gmail.com",
            port=993,
            username="user@gmail.com",
            auth_type=AuthType.PASSWORD,
            use_ssl=True,
        )
        return account_repo.upsert(acc)

    @pytest.fixture
    def gmail_folders(self, folder_repo, gmail_account):
        """Create INBOX, [Gmail]/All Mail, and [Gmail]/Sent Mail folders."""
        inbox = folder_repo.upsert(Folder(account_id=gmail_account.id, name="INBOX"))
        all_mail = folder_repo.upsert(Folder(account_id=gmail_account.id, name="[Gmail]/All Mail"))
        sent = folder_repo.upsert(Folder(account_id=gmail_account.id, name="[Gmail]/Sent Mail"))
        return inbox, all_mail, sent

    def test_find_all_mail_folder_gmail(self, folder_repo, gmail_folders, gmail_account):
        result = folder_repo.find_all_mail_folder(gmail_account.id)
        assert result is not None
        assert result.name == "[Gmail]/All Mail"

    def test_find_all_mail_folder_non_gmail(self, folder_repo, sample_account):
        """Non-Gmail account has no All Mail folder."""
        result = folder_repo.find_all_mail_folder(sample_account.id)
        assert result is None

    def test_message_in_both_allmail_and_inbox_not_unlabelled(
        self, msg_repo, gmail_folders,
    ):
        """Message appearing in both All Mail and INBOX should NOT be unlabelled."""
        inbox, all_mail, _sent = gmail_folders
        # Same identity tuple in both folders
        msg_all = Message(
            uid=1, folder_id=all_mail.id,
            from_addr="alice@x.com", subject="Hello", date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            size_bytes=5000,
        )
        msg_inbox = Message(
            uid=100, folder_id=inbox.id,
            from_addr="alice@x.com", subject="Hello", date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            size_bytes=5000,
        )
        msg_repo.upsert_batch([msg_all, msg_inbox])

        other_ids = [inbox.id, _sent.id]
        count, size = msg_repo.get_unlabelled_stats(all_mail.id, other_ids)
        assert count == 0
        assert size == 0

        messages = msg_repo.query_unlabelled_messages(all_mail.id, other_ids)
        assert len(messages) == 0

    def test_message_only_in_allmail_is_unlabelled(
        self, msg_repo, gmail_folders,
    ):
        """Message only in All Mail (no copy in INBOX/Sent) IS unlabelled."""
        inbox, all_mail, sent = gmail_folders
        # This message only exists in All Mail
        msg_archived = Message(
            uid=1, folder_id=all_mail.id,
            from_addr="bob@x.com", subject="Archived", date=datetime(2025, 2, 1, tzinfo=timezone.utc),
            size_bytes=3000,
        )
        # This message exists in both All Mail and INBOX (not unlabelled)
        msg_labelled_all = Message(
            uid=2, folder_id=all_mail.id,
            from_addr="carol@x.com", subject="Labelled", date=datetime(2025, 3, 1, tzinfo=timezone.utc),
            size_bytes=2000,
        )
        msg_labelled_inbox = Message(
            uid=200, folder_id=inbox.id,
            from_addr="carol@x.com", subject="Labelled", date=datetime(2025, 3, 1, tzinfo=timezone.utc),
            size_bytes=2000,
        )
        msg_repo.upsert_batch([msg_archived, msg_labelled_all, msg_labelled_inbox])

        other_ids = [inbox.id, sent.id]
        count, size = msg_repo.get_unlabelled_stats(all_mail.id, other_ids)
        assert count == 1
        assert size == 3000

        messages = msg_repo.query_unlabelled_messages(all_mail.id, other_ids)
        assert len(messages) == 1
        assert messages[0].subject == "Archived"

    def test_no_other_folders_returns_all(self, msg_repo, gmail_folders):
        """When other_folder_ids is empty, all All Mail messages are 'unlabelled'."""
        _inbox, all_mail, _sent = gmail_folders
        msgs = [
            Message(uid=i, folder_id=all_mail.id, from_addr=f"u{i}@x.com",
                    subject=f"Msg {i}", size_bytes=1000 * i)
            for i in range(1, 4)
        ]
        msg_repo.upsert_batch(msgs)

        count, size = msg_repo.get_unlabelled_stats(all_mail.id, [])
        assert count == 3
        assert size == 6000

        messages = msg_repo.query_unlabelled_messages(all_mail.id, [])
        assert len(messages) == 3

    def test_query_unlabelled_with_filters(self, msg_repo, gmail_folders):
        """Filters (from, size, etc.) work on unlabelled queries."""
        inbox, all_mail, sent = gmail_folders
        msg_repo.upsert_batch([
            Message(uid=1, folder_id=all_mail.id, from_addr="big@x.com",
                    subject="Big", size_bytes=10_000),
            Message(uid=2, folder_id=all_mail.id, from_addr="small@x.com",
                    subject="Small", size_bytes=100),
        ])
        other_ids = [inbox.id, sent.id]
        messages = msg_repo.query_unlabelled_messages(
            all_mail.id, other_ids, size_min=5000,
        )
        assert len(messages) == 1
        assert messages[0].from_addr == "big@x.com"
