import pytest

from app.answer.prompts import SAMPLE_CV
from app.documents.chunking import chunk_text
from app.documents.parsing import ParseError, clean_text, extract_text
from tests.doc_fixtures import make_docx, make_pdf

PDF_LINES = [
    "Jordan Lee",
    "EXPERIENCE",
    "Data Engineer, Acme Analytics (2020 - 2024)",
    "• Built streaming pipelines in Kafka and Spark handling 5 TB per day.",
    "• Cut warehouse costs by 40% by partitioning BigQuery tables.",
    "EDUCATION",
    "MSc Data Science, University of Manchester, 2019",
]


def test_pdf_text_and_bullets():
    text = extract_text("cv.pdf", make_pdf(PDF_LINES))
    assert "Acme Analytics" in text
    assert "- Built streaming pipelines" in text


def test_docx_paragraphs_lists_and_tables():
    data = make_docx(
        [
            ("Experience", "Heading 1"),
            ("Platform Engineer, Northwind (2021 to present)", None),
            ("Migrated 40 services to Kubernetes with zero downtime releases.", "List Bullet"),
            ("Introduced Terraform modules used by six product teams across the company.", None),
        ]
    )
    text = extract_text("cv.docx", data)
    assert "- Migrated 40 services" in text
    assert "Skills | Python, Go, PostgreSQL" in text


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("cv.exe", b"MZ" + b"x" * 100, "Unsupported"),
        ("cv.doc", b"\xd0\xcf" + b"x" * 100, ".docx"),
        ("cv.pdf", b"%PDF-1.4 garbage", "couldn't be read"),
        ("cv.docx", b"not a zip", "couldn't be read"),
        ("cv.txt", b"too short", "enough text"),
        ("cv.txt", b"", "empty"),
        ("cv.txt", b"x" * (5 * 1024 * 1024 + 1), "5 MB"),
    ],
    ids=["exe", "old-doc", "broken-pdf", "broken-docx", "too-short", "empty", "too-big"],
)
def test_bad_files_give_clear_errors(name, data, message):
    with pytest.raises(ParseError, match=message):
        extract_text(name, data)


def test_clean_text_normalises_bullets_and_spacing():
    assert clean_text("  ●  Built   things\r\n\r\n\r\n▪ Shipped") == "- Built things\n\n- Shipped"


def test_chunks_keep_section_and_role_context():
    chunks = chunk_text(SAMPLE_CV)
    latency = next(c for c in chunks if "480 ms" in c.text)
    assert latency.section == "Experience"
    assert latency.role and "Brightlane Payments" in latency.role
    assert latency.text.startswith("Experience · **Senior") is False  # markdown bold stripped
    assert "Brightlane Payments" in latency.text.split("\n")[0]
    education = next(c for c in chunks if "Leeds" in c.text)
    assert education.section == "Education"
    assert all(len(c.text.split()) <= 130 for c in chunks)


def test_role_without_bullets_still_becomes_a_chunk():
    chunks = chunk_text(
        "EXPERIENCE\nJunior Developer, Foo Ltd (2018 to 2019)\nEDUCATION\nBSc, 2018"
    )
    assert any("Foo Ltd" in c.text for c in chunks)
    assert any("BSc" in c.text for c in chunks)


def test_pdf_cv_chunks_end_to_end():
    chunks = chunk_text(extract_text("cv.pdf", make_pdf(PDF_LINES)))
    kafka = next(c for c in chunks if "Kafka" in c.text)
    assert kafka.role == "Data Engineer, Acme Analytics (2020 - 2024)"
    assert kafka.section == "EXPERIENCE"
