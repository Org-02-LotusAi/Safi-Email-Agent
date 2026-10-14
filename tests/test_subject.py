"""Unit tests for safi/subject.py (doc §14, §9, §16)."""

from __future__ import annotations

from safi.subject import (
    canonicalize_subject,
    is_private_subject,
    reply_subject,
    subject_key,
)


def test_canonicalize_plain():
    assert canonicalize_subject("Contract Renewal") == "Contract Renewal"


def test_canonicalize_re_prefix():
    assert canonicalize_subject("Re: Contract Renewal") == "Contract Renewal"


def test_canonicalize_fwd_prefix():
    assert canonicalize_subject("Fwd: Contract Renewal") == "Contract Renewal"


def test_canonicalize_chained_prefix():
    # doc §14 example: RE: Fwd: Contract Renewal -> Contract Renewal
    assert canonicalize_subject("RE: Fwd: Contract Renewal") == "Contract Renewal"


def test_canonicalize_fw_variant():
    assert canonicalize_subject("FW: Contract Renewal") == "Contract Renewal"


def test_canonicalize_collapses_whitespace():
    assert canonicalize_subject("  Contract   Renewal  ") == "Contract Renewal"


def test_canonicalize_empty_or_none():
    assert canonicalize_subject("") == ""
    assert canonicalize_subject(None) == ""


def test_all_doc_examples_share_one_canonical_form():
    examples = [
        "Contract Renewal",
        "Re: Contract Renewal",
        "Fwd: Contract Renewal",
        "RE: Fwd: Contract Renewal",
    ]
    forms = {canonicalize_subject(e) for e in examples}
    assert forms == {"Contract Renewal"}
    keys = {subject_key(e) for e in examples}
    assert len(keys) == 1


def test_subject_key_is_casefolded():
    assert subject_key("Contract Renewal") == subject_key("CONTRACT RENEWAL")
    assert subject_key("Contract Renewal") == "contract renewal"


def test_private_is_reserved_case_insensitive():
    assert is_private_subject("Private")
    assert is_private_subject("private")
    assert is_private_subject("PRIVATE")
    assert is_private_subject("Re: Private")
    assert is_private_subject("Fwd: private")


def test_private_not_confused_with_similar_subject():
    assert not is_private_subject("Private Matters")
    assert not is_private_subject("Contract Renewal")


def test_reply_subject_adds_single_re_prefix():
    assert reply_subject("Contract Renewal") == "Re: Contract Renewal"


def test_reply_subject_does_not_double_prefix_when_given_canonical_input():
    # reply_subject is expected to receive an already-canonicalized subject; it must
    # still normalize any lingering prefix chain down to exactly one "Re: ".
    assert reply_subject("Re: Contract Renewal") == "Re: Contract Renewal"


def test_reply_subject_empty():
    assert reply_subject("") == "Re:"
