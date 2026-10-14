"""Unit tests for safi/email_parse.py (doc §21, §22, §23)."""

from __future__ import annotations

from safi import compose
from safi.email_parse import parse_email

from conftest import make_pdf_bytes, make_docx_bytes

MAILBOX = "reply-agent@example.com"


def test_message_id_from_and_subject_are_parsed():
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Contract Renewal",
        body="Please review.",
        message_id="fixed-id-1@safi.local",
    )
    email = parse_email(raw, MAILBOX)
    assert email.message_id == "fixed-id-1@safi.local"
    assert email.sender == "alice@customer.com"
    assert email.canonical_subject == "Contract Renewal"
    assert email.is_private is False
    assert email.delivered_to == MAILBOX
    assert "Please review." in email.body_text


def test_from_header_is_normalized_lowercase():
    raw = compose.make_message(
        sender="Alice@Customer.COM",
        to=MAILBOX,
        subject="Hello",
        body="hi",
    )
    email = parse_email(raw, MAILBOX)
    assert email.sender == "alice@customer.com"


def test_private_subject_detected():
    raw = compose.make_message(
        sender="owner@example.com", to=MAILBOX, subject="Private", body="train me"
    )
    email = parse_email(raw, MAILBOX)
    assert email.is_private is True


def test_threading_headers_in_reply_to_and_references():
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Re: Contract Renewal",
        body="Follow up",
        message_id="child-id@safi.local",
        in_reply_to="parent-id@safi.local",
        references=["root-id@safi.local", "parent-id@safi.local"],
    )
    email = parse_email(raw, MAILBOX)
    assert email.in_reply_to == "parent-id@safi.local"
    assert email.references == ["root-id@safi.local", "parent-id@safi.local"]
    assert email.thread_key == "parent-id@safi.local"


def test_thread_key_falls_back_to_last_reference_without_in_reply_to():
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Re: Contract Renewal",
        body="Follow up",
        references=["root-id@safi.local", "second-id@safi.local"],
    )
    email = parse_email(raw, MAILBOX)
    assert email.in_reply_to is None
    assert email.thread_key == "second-id@safi.local"


def test_forwarded_text_extraction_from_body_marker():
    body = (
        "Please handle this.\n\n"
        "---------- Forwarded message ----------\n"
        "From: bob@customer.com\n"
        "Subject: Original topic\n\n"
        "Here is the original important detail: BUDGET-APPROVED-9000."
    )
    raw = compose.make_message(
        sender="alice@customer.com", to=MAILBOX, subject="Contract Renewal", body=body
    )
    email = parse_email(raw, MAILBOX)
    assert "Please handle this." in email.body_text
    assert "Forwarded message" not in email.body_text
    assert "BUDGET-APPROVED-9000" in email.forwarded_text


def test_quoted_reply_lines_treated_as_forwarded_history():
    body = "Sure, sounds good.\n> Original ask: can we move to Net 60?\n> Thanks."
    raw = compose.make_message(
        sender="alice@customer.com", to=MAILBOX, subject="Contract Renewal", body=body
    )
    email = parse_email(raw, MAILBOX)
    assert "Sure, sounds good." in email.body_text
    assert "Net 60" in email.forwarded_text


def test_attachment_collection_txt():
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Contract Renewal",
        body="See attached.",
        attachments=[("notes.txt", b"important note ABC123")],
    )
    email = parse_email(raw, MAILBOX)
    assert len(email.attachments) == 1
    att = email.attachments[0]
    assert att.filename == "notes.txt"
    assert att.supported is True
    assert "ABC123" in att.extracted_text


def test_attachment_collection_pdf_and_docx():
    pdf_bytes = make_pdf_bytes("PDF-CONTENT-XYZ")
    docx_bytes = make_docx_bytes("DOCX-CONTENT-XYZ")
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Contract Renewal",
        body="See attached.",
        attachments=[("doc.pdf", pdf_bytes), ("doc.docx", docx_bytes)],
    )
    email = parse_email(raw, MAILBOX)
    by_name = {a.filename: a for a in email.attachments}
    assert "PDF-CONTENT-XYZ" in by_name["doc.pdf"].extracted_text
    assert "DOCX-CONTENT-XYZ" in by_name["doc.docx"].extracted_text


def test_unsupported_attachment_collected_but_marked_unsupported():
    raw = compose.make_message(
        sender="alice@customer.com",
        to=MAILBOX,
        subject="Contract Renewal",
        body="See attached.",
        attachments=[("archive.zip", b"not a real zip")],
    )
    email = parse_email(raw, MAILBOX)
    assert len(email.attachments) == 1
    assert email.attachments[0].supported is False
