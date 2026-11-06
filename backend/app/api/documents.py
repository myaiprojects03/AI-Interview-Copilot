"""Upload, list, view and delete CVs and job descriptions."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.deps import EmbedderDep, SettingsDep, StoreDep, UserDep
from app.documents.parsing import MAX_UPLOAD_BYTES, ParseError, clean_text, extract_text
from app.documents.service import ingest
from app.documents.store import StoredDocument
from app.providers.base import ProviderError
from app.providers.registry import get_llm

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    kind: Literal["cv", "jd"]
    title: str
    filename: str | None
    summary: str
    chunk_count: int
    word_count: int
    created_at: datetime


class DocumentDetail(DocumentOut):
    content: str


def _out(doc: StoredDocument) -> dict:
    return {
        "id": doc.id,
        "kind": doc.kind,
        "title": doc.title,
        "filename": doc.filename,
        "summary": doc.summary,
        "chunk_count": doc.chunk_count,
        "word_count": len(doc.content.split()),
        "created_at": doc.created_at,
    }


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    settings: SettingsDep,
    store: StoreDep,
    embedder: EmbedderDep,
    user_id: UserDep,
    kind: Annotated[Literal["cv", "jd"], Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form(max_length=60_000)] = None,
    title: Annotated[str | None, Form(max_length=120)] = None,
):
    """Send either a file (PDF, DOCX, TXT, MD) or pasted text."""
    try:
        if file is not None and file.filename:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            content = extract_text(file.filename, data)
            filename = file.filename
        elif text and text.strip():
            content = clean_text(text)
            if len(content.split()) < 20:
                raise ParseError("Paste at least a few sentences.")
            filename = None
        else:
            raise ParseError("Upload a file or paste the text.")
        llm = get_llm(settings)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    doc = await ingest(
        user_id=user_id,
        kind=kind,
        text=content,
        filename=filename,
        title=title,
        store=store,
        embedder=embedder,
        llm=llm,
    )
    return _out(doc)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    store: StoreDep, user_id: UserDep, kind: Literal["cv", "jd"] | None = None
):
    return [_out(d) for d in await store.list_documents(user_id, kind)]


@router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(doc_id: str, store: StoreDep, user_id: UserDep):
    doc = await store.get(user_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {**_out(doc), "content": doc.content}


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, store: StoreDep, user_id: UserDep) -> None:
    if not await store.delete(user_id, doc_id):
        raise HTTPException(status_code=404, detail="Document not found.")
