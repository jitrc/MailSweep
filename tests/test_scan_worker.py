"""Tests for ScanWorker with a mock IMAPClient."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from mailsweep.workers.scan_worker import (
    ScanWorker,
    _parse_bodystructure,
    _decode_header,
    _parse_date,
    _envelope_addr,
)


def make_mock_client(uid_map: dict) -> MagicMock:
    """Create a mock IMAPClient that returns uid_map from fetch()."""
    client = MagicMock()
    client.search.return_value = list(uid_map.keys())
    client.fetch.return_value = uid_map
    return client


class _MockAddress:
    """Mimics imapclient.response_types.Address (attribute-based)."""
    def __init__(self, name, route, mailbox, host):
        self.name = name
        self.route = route
        self.mailbox = mailbox
        self.host = host


class _MockEnvelope:
    """Mimics imapclient.response_types.Envelope (attribute-based)."""
    def __init__(self, date, subject, from_, sender=None, reply_to=None,
                 to=None, cc=None, bcc=None, in_reply_to=None, message_id=None):
        self.date = date
        self.subject = subject
        self.from_ = from_
        self.sender = sender
        self.reply_to = reply_to
        self.to = to
        self.cc = cc
        self.bcc = bcc
        self.in_reply_to = in_reply_to
        self.message_id = message_id


def make_envelope(
    date=None,
    subject: bytes = b"Test Subject",
    from_name: bytes = b"Alice",
    from_mbox: bytes = b"alice",
    from_host: bytes = b"example.com",
    message_id: bytes = b"<test@example.com>",
):
    """Build a mock Envelope matching imapclient 3.x API."""
    from datetime import datetime, timezone
    if date is None:
        date = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    addr = _MockAddress(from_name, None, from_mbox, from_host)
    return _MockEnvelope(date=date, subject=subject, from_=(addr,), message_id=message_id)


class TestScanWorker:
    def test_basic_scan_returns_messages(self):
        uid_map = {
            1: {
                b"ENVELOPE": make_envelope(subject=b"Hello"),
                b"RFC822.SIZE": 1024,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [b"\\Seen"],
            },
            2: {
                b"ENVELOPE": make_envelope(subject=b"World", from_mbox=b"bob", from_host=b"test.com"),
                b"RFC822.SIZE": 2048,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 200),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 12345}

        batches: list = []
        worker = ScanWorker(
            client=client,
            folder_id=1,
            folder_name="INBOX",
            on_batch=batches.extend,
        )
        messages = worker.run()

        assert len(messages) == 2
        assert len(batches) == 2
        uids = {m.uid for m in messages}
        assert uids == {1, 2}

    def test_attachment_detected(self):
        uid_map = {
            10: {
                b"ENVELOPE": make_envelope(),
                b"RFC822.SIZE": 5_000_000,
                b"BODYSTRUCTURE": [
                    [(b"text", b"html", [], None, None, b"7bit", 500)],
                    (
                        b"application", b"pdf",
                        [b"name", b"report.pdf"],
                        None, None, b"base64", 4_000_000,
                        None, (b"attachment", [b"filename", b"report.pdf"]),
                    ),
                ],
                b"FLAGS": [],
            }
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].has_attachment is True
        assert len(messages[0].attachment_names) > 0

    def test_message_id_parsed_from_envelope(self):
        uid_map = {
            1: {
                b"ENVELOPE": make_envelope(
                    subject=b"Hello",
                    message_id=b"<unique123@gmail.com>",
                ),
                b"RFC822.SIZE": 1024,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].message_id == "<unique123@gmail.com>"

    def test_message_id_empty_without_envelope(self):
        uid_map = {
            1: {
                b"RFC822.SIZE": 512,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].message_id == ""

    def test_cancel_stops_scan(self):
        uids = list(range(1, 1001))
        uid_map = {
            uid: {
                b"ENVELOPE": make_envelope(),
                b"RFC822.SIZE": 100,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 10),
                b"FLAGS": [],
            }
            for uid in uids
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}
        # Return all UIDs from search but only one batch at a time
        client.search.return_value = uids
        client.fetch.return_value = {uid: uid_map[uid] for uid in uids[:500]}

        batches_received = []

        def on_batch(msgs):
            batches_received.extend(msgs)

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX", on_batch=on_batch)
        worker.cancel()  # Cancel before running
        messages = worker.run()
        assert len(messages) == 0  # Cancelled before first batch


class TestBodystructureParsing:
    def test_simple_text(self):
        bs = (b"text", b"plain", [], None, None, b"7bit", 100)
        has_att, names = _parse_bodystructure(bs)
        assert has_att is False
        assert names == []

    def test_pdf_attachment(self):
        bs = (
            b"application", b"pdf",
            [b"name", b"invoice.pdf"],
            None, None, b"base64", 500000,
            None, (b"attachment", [b"filename", b"invoice.pdf"]),
        )
        has_att, names = _parse_bodystructure(bs)
        assert has_att is True
        assert "invoice.pdf" in names

    def test_multipart_with_attachment(self):
        bs = [
            [
                (b"text", b"plain", [], None, None, b"7bit", 100),
                (b"text", b"html", [], None, None, b"7bit", 200),
            ],
            (
                b"application", b"zip",
                [b"name", b"archive.zip"],
                None, None, b"base64", 100000,
                None, (b"attachment", [b"filename", b"archive.zip"]),
            ),
        ]
        has_att, names = _parse_bodystructure(bs)
        assert has_att is True

    def test_none_bodystructure(self):
        has_att, names = _parse_bodystructure(None)
        assert has_att is False
        assert names == []


class TestDecodeHeader:
    def test_plain_ascii(self):
        assert _decode_header(b"Hello World") == "Hello World"

    def test_encoded_word_utf8(self):
        # "Subject" encoded in UTF-8
        encoded = b"=?UTF-8?B?SGVsbG8gV29ybGQ=?="
        assert _decode_header(encoded) == "Hello World"

    def test_none(self):
        assert _decode_header(None) == ""

    def test_plain_string(self):
        assert _decode_header("Plain string") == "Plain string"


class TestParseDate:
    def test_rfc2822_with_tz(self):
        dt = _parse_date(b"Mon, 01 Jan 2024 12:00:00 +0000")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_invalid_date(self):
        assert _parse_date(b"not a date") is None

    def test_none(self):
        assert _parse_date(None) is None


class TestEnvelopeAddr:
    def test_full_address_object(self):
        addr_list = (_MockAddress(b"Alice Smith", None, b"alice", b"example.com"),)
        result = _envelope_addr(addr_list)
        assert "alice@example.com" in result
        assert "Alice" in result

    def test_full_address_tuple(self):
        addr_list = [(b"Alice Smith", None, b"alice", b"example.com")]
        result = _envelope_addr(addr_list)
        assert "alice@example.com" in result
        assert "Alice" in result

    def test_empty(self):
        assert _envelope_addr(None) == ""
        assert _envelope_addr([]) == ""


class TestInReplyToParsing:
    def test_in_reply_to_parsed_from_envelope(self):
        """ScanWorker extracts in_reply_to from ENVELOPE."""
        envelope = _MockEnvelope(
            date=None,
            subject=b"Re: Test",
            from_=(_MockAddress(b"Bob", None, b"bob", b"example.com"),),
            in_reply_to=b"<original@example.com>",
            message_id=b"<reply@example.com>",
        )
        uid_map = {
            1: {
                b"ENVELOPE": envelope,
                b"RFC822.SIZE": 1024,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].in_reply_to == "<original@example.com>"

    def test_in_reply_to_empty_when_none(self):
        """in_reply_to defaults to empty string when not set."""
        uid_map = {
            1: {
                b"ENVELOPE": make_envelope(),
                b"RFC822.SIZE": 512,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].in_reply_to == ""


class TestThreadIdParsing:
    def test_thread_id_parsed_from_xgm_thrid(self):
        """ScanWorker extracts X-GM-THRID as thread_id."""
        uid_map = {
            1: {
                b"ENVELOPE": make_envelope(),
                b"RFC822.SIZE": 1024,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
                b"X-GM-THRID": 1234567890,
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].thread_id == 1234567890

    def test_thread_id_zero_when_absent(self):
        """thread_id defaults to 0 when X-GM-THRID is not present (non-Gmail)."""
        uid_map = {
            1: {
                b"ENVELOPE": make_envelope(),
                b"RFC822.SIZE": 512,
                b"BODYSTRUCTURE": (b"text", b"plain", [], None, None, b"7bit", 100),
                b"FLAGS": [],
            },
        }
        client = make_mock_client(uid_map)
        client.select_folder.return_value = {b"UIDVALIDITY": 1}

        worker = ScanWorker(client=client, folder_id=1, folder_name="INBOX")
        messages = worker.run()
        assert len(messages) == 1
        assert messages[0].thread_id == 0
