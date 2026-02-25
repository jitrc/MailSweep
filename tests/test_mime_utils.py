"""Tests for mime_utils — strip_attachments and related helpers."""
from __future__ import annotations

import email
import email.policy
from pathlib import Path

import pytest

from mailsweep.utils.mime_utils import strip_attachments, get_attachment_info, MAILSWEEP_HEADER


def make_simple_email(subject="Test", body="Hello World") -> bytes:
    """Build a simple text/plain email."""
    msg = email.message.MIMEPart(policy=email.policy.compat32)
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = subject
    msg.set_payload(body)
    msg["Content-Type"] = "text/plain; charset=utf-8"
    return msg.as_bytes()


def make_multipart_with_attachment(
    body="Hello",
    attachment_name="test.pdf",
    attachment_data=b"%PDF-1.4 fake pdf content",
) -> bytes:
    """Build a multipart/mixed email with one text body and one attachment."""
    import email.mime.multipart
    import email.mime.text
    import email.mime.base
    from email import encoders

    msg = email.mime.multipart.MIMEMultipart("mixed")
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Email with attachment"

    # Text body
    text_part = email.mime.text.MIMEText(body, "plain", "utf-8")
    msg.attach(text_part)

    # Attachment
    att = email.mime.base.MIMEBase("application", "pdf")
    att.set_payload(attachment_data)
    encoders.encode_base64(att)
    att.add_header("Content-Disposition", "attachment", filename=attachment_name)
    msg.attach(att)

    return msg.as_bytes()


def make_nested_multipart(
    body="Nested body",
    attachment_name="nested.zip",
    attachment_data=b"PK\x03\x04fake zip",
) -> bytes:
    """Build a multipart/alternative nested in multipart/mixed with attachment."""
    import email.mime.multipart
    import email.mime.text
    import email.mime.base
    from email import encoders

    outer = email.mime.multipart.MIMEMultipart("mixed")
    outer["From"] = "sender@example.com"
    outer["Subject"] = "Nested"

    inner = email.mime.multipart.MIMEMultipart("alternative")
    inner.attach(email.mime.text.MIMEText(body, "plain"))
    inner.attach(email.mime.text.MIMEText(f"<b>{body}</b>", "html"))
    outer.attach(inner)

    att = email.mime.base.MIMEBase("application", "zip")
    att.set_payload(attachment_data)
    encoders.encode_base64(att)
    att.add_header("Content-Disposition", "attachment", filename=attachment_name)
    outer.attach(att)

    return outer.as_bytes()


class TestStripAttachments:
    def test_simple_email_unchanged(self, tmp_path):
        raw = make_simple_email()
        cleaned, saved = strip_attachments(raw, tmp_path, uid=1)
        assert saved == []
        # Still a valid email
        msg = email.message_from_bytes(cleaned, policy=email.policy.compat32)
        assert "Hello World" in msg.get_payload()

    def test_attachment_saved_to_disk(self, tmp_path):
        raw = make_multipart_with_attachment(
            attachment_name="invoice.pdf",
            attachment_data=b"PDF CONTENT",
        )
        cleaned, saved = strip_attachments(raw, tmp_path, uid=42)
        assert len(saved) == 1
        saved_file = tmp_path / saved[0]
        assert saved_file.exists()
        assert saved_file.read_bytes() == b"PDF CONTENT"

    def test_attachment_removed_from_message(self, tmp_path):
        raw = make_multipart_with_attachment()
        cleaned, saved = strip_attachments(raw, tmp_path, uid=1)
        assert len(saved) == 1
        msg = email.message_from_bytes(cleaned, policy=email.policy.compat32)
        for part in msg.walk():
            disp = part.get("Content-Disposition") or ""
            assert "attachment" not in disp.lower()

    def test_audit_header_added(self, tmp_path):
        raw = make_multipart_with_attachment()
        cleaned, saved = strip_attachments(raw, tmp_path, uid=99)
        msg = email.message_from_bytes(cleaned, policy=email.policy.compat32)
        assert msg[MAILSWEEP_HEADER] is not None
        assert "Detached" in msg[MAILSWEEP_HEADER]

    def test_nested_multipart_attachment_stripped(self, tmp_path):
        raw = make_nested_multipart(attachment_name="archive.zip")
        cleaned, saved = strip_attachments(raw, tmp_path, uid=5)
        assert len(saved) == 1
        assert "archive.zip" in saved[0]

    def test_no_attachment_no_saved_files(self, tmp_path):
        raw = make_simple_email(body="Just text")
        cleaned, saved = strip_attachments(raw, tmp_path, uid=7)
        assert saved == []
        files = list(tmp_path.iterdir())
        assert files == []

    def test_multiple_attachments(self, tmp_path):
        import email.mime.multipart
        import email.mime.text
        import email.mime.base
        from email import encoders

        msg = email.mime.multipart.MIMEMultipart("mixed")
        msg["From"] = "x@x.com"
        msg["Subject"] = "Multi-attach"
        msg.attach(email.mime.text.MIMEText("Body"))

        for i, (name, data) in enumerate([("a.pdf", b"PDF"), ("b.zip", b"ZIP"), ("c.png", b"PNG")]):
            att = email.mime.base.MIMEBase("application", "octet-stream")
            att.set_payload(data)
            encoders.encode_base64(att)
            att.add_header("Content-Disposition", "attachment", filename=name)
            msg.attach(att)

        raw = msg.as_bytes()
        cleaned, saved = strip_attachments(raw, tmp_path, uid=10)
        assert len(saved) == 3
        assert len(list(tmp_path.iterdir())) == 3

    def test_safe_filename_path_traversal(self, tmp_path):
        import email.mime.multipart
        import email.mime.text
        import email.mime.base
        from email import encoders

        msg = email.mime.multipart.MIMEMultipart("mixed")
        msg["From"] = "x@x.com"
        msg["Subject"] = "Traversal test"
        msg.attach(email.mime.text.MIMEText("Body"))

        att = email.mime.base.MIMEBase("application", "octet-stream")
        att.set_payload(b"content")
        encoders.encode_base64(att)
        att.add_header("Content-Disposition", "attachment", filename="../../etc/passwd")
        msg.attach(att)

        raw = msg.as_bytes()
        cleaned, saved = strip_attachments(raw, tmp_path, uid=11)
        assert len(saved) == 1
        # The filename must not contain path separators
        assert "/" not in saved[0]
        assert ".." not in saved[0]


class TestGetAttachmentInfo:
    def test_no_attachment(self):
        raw = make_simple_email()
        has_att, names = get_attachment_info(raw)
        assert has_att is False
        assert names == []

    def test_with_attachment(self):
        raw = make_multipart_with_attachment(attachment_name="report.pdf")
        has_att, names = get_attachment_info(raw)
        assert has_att is True
        assert any("report.pdf" in n for n in names)
