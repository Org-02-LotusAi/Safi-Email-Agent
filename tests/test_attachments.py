"""Unit tests for safi/attachments.py (doc §24, §37/TEST 21)."""

from __future__ import annotations

from safi.attachments import extract

from conftest import make_docx_bytes, make_pdf_bytes


def test_txt_extraction():
    pa = extract("notes.txt", b"Hello world\nSecond line")
    assert pa.supported is True
    assert pa.error is None
    assert "Hello world" in pa.extracted_text


def test_txt_extraction_latin1_fallback():
    data = "café".encode("latin-1")
    pa = extract("notes.txt", data)
    assert pa.supported is True
    assert pa.extracted_text is not None


def test_pdf_extraction():
    pdf_bytes = make_pdf_bytes("The quarterly report shows PDF-MARKER-42.")
    pa = extract("report.pdf", pdf_bytes)
    assert pa.supported is True
    assert pa.error is None
    assert "PDF-MARKER-42" in pa.extracted_text


def test_docx_extraction():
    docx_bytes = make_docx_bytes("The proposal contains DOCX-MARKER-77.")
    pa = extract("proposal.docx", docx_bytes)
    assert pa.supported is True
    assert pa.error is None
    assert "DOCX-MARKER-77" in pa.extracted_text


def test_unsupported_extension_returns_supported_false_without_raising():
    pa = extract("archive.zip", b"PK\x03\x04not a real zip but bytes")
    assert pa.supported is False
    assert pa.extracted_text is None
    assert pa.error is not None


def test_unsupported_binary_extension_returns_supported_false_without_raising():
    pa = extract("payload.bin", b"\x00\x01\x02\xff")
    assert pa.supported is False
    assert pa.extracted_text is None


def test_corrupt_pdf_returns_error_not_raise():
    pa = extract("broken.pdf", b"this is not a valid pdf file at all")
    # Must not raise. "supported" reflects that .pdf is a mandatory type; the failure
    # is captured in .error, .extracted_text stays None (doc §37).
    assert pa.supported is True
    assert pa.extracted_text is None
    assert pa.error is not None


def test_corrupt_docx_returns_error_not_raise():
    pa = extract("broken.docx", b"this is not a valid docx/zip file at all")
    assert pa.supported is True
    assert pa.extracted_text is None
    assert pa.error is not None


def test_ext_property_on_parsed_attachment():
    pa = extract("notes.TXT", b"hi")
    assert pa.ext == "txt"
