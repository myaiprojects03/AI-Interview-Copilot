from tests.doc_fixtures import make_docx, make_pdf

JD = """Senior Backend Engineer at Lumen Pay
We build real-time payment infrastructure for small businesses.
Requirements
- 5+ years building backend services in Go or Python
- Experience with PostgreSQL, Kafka and AWS
- Strong ownership and incident response skills
"""


def test_upload_pdf_cv_then_list_get_delete(client):
    pdf = make_pdf(
        [
            "Jordan Lee",
            "EXPERIENCE",
            "Data Engineer, Acme Analytics (2020 - 2024)",
            "• Built streaming pipelines in Kafka and Spark handling 5 TB per day.",
            "• Cut warehouse costs by 40% by partitioning BigQuery tables.",
        ]
    )
    r = client.post(
        "/documents", data={"kind": "cv"}, files={"file": ("jordan.pdf", pdf, "application/pdf")}
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["kind"] == "cv"
    assert doc["title"] == "jordan"
    assert doc["chunk_count"] >= 1
    assert doc["summary"]  # fake LLM returns a fixed sentence

    listed = client.get("/documents?kind=cv").json()
    assert [d["id"] for d in listed] == [doc["id"]]
    assert client.get("/documents?kind=jd").json() == []

    detail = client.get(f"/documents/{doc['id']}").json()
    assert "Acme Analytics" in detail["content"]

    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert client.get(f"/documents/{doc['id']}").status_code == 404
    assert client.delete(f"/documents/{doc['id']}").status_code == 404


def test_upload_docx_and_pasted_jd(client):
    docx = make_docx(
        [
            ("Experience", "Heading 1"),
            ("Platform Engineer, Northwind (2021 to present)", None),
            ("Migrated 40 services to Kubernetes with zero downtime releases.", "List Bullet"),
            ("Introduced Terraform modules used by six product teams across the company.", None),
        ]
    )
    r = client.post("/documents", data={"kind": "cv"}, files={"file": ("cv.docx", docx)})
    assert r.status_code == 201, r.text

    r = client.post("/documents", data={"kind": "jd", "text": JD, "title": "Lumen Pay"})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Lumen Pay"
    assert len(client.get("/documents").json()) == 2


def test_bad_upload_is_rejected_with_reason(client):
    r = client.post("/documents", data={"kind": "cv"}, files={"file": ("cv.exe", b"MZ" * 50)})
    assert r.status_code == 422
    assert "Unsupported" in r.json()["detail"]

    r = client.post("/documents", data={"kind": "cv"})
    assert r.status_code == 422

    r = client.post("/documents", data={"kind": "resume", "text": JD})
    assert r.status_code == 422


def test_unknown_ids_are_404(client):
    assert client.get("/documents/does-not-exist").status_code == 404
    assert client.get("/documents/00000000-0000-0000-0000-000000000000").status_code == 404


def test_health_reports_memory_storage(client):
    db = client.get("/health/providers").json()["database"]
    assert db == {"configured": False, "storage": "memory", "error": None}
