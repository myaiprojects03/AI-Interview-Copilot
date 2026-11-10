"""Interview history (transcripts and suggested answers) and deleting a user's data."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.accounts.store import AccountStore
from app.core.deps import StoreDep, UserDep, get_accounts

router = APIRouter(tags=["history"])
AccountsDep = Annotated[AccountStore, Depends(get_accounts)]


def _summary(s) -> dict:
    return {
        "id": s.id,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "minutes": round(s.audio_seconds / 60, 1),
        "seconds": round(s.audio_seconds),
        "cv_title": s.cv_title,
        "jd_title": s.jd_title,
        "question_count": s.question_count,
    }


@router.get("/sessions")
async def list_sessions(user_id: UserDep, accounts: AccountsDep) -> list[dict]:
    return [_summary(s) for s in await accounts.list_sessions(user_id)]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: UserDep, accounts: AccountsDep) -> dict:
    found = await accounts.get_session(user_id, session_id)
    if not found:
        raise HTTPException(404, "Interview not found.")
    session, turns, answers = found
    return {
        **_summary(session),
        "turns": [{"speaker": t.speaker, "text": t.text, "at": t.created_at} for t in turns],
        "answers": [
            {"question": a.question, "question_type": a.question_type, "answer": a.answer,
             "status": a.status, "at": a.created_at}
            for a in answers
        ],
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: UserDep, accounts: AccountsDep) -> None:
    if not await accounts.delete_session(user_id, session_id):
        raise HTTPException(404, "Interview not found.")


@router.delete("/me/data")
async def delete_my_data(user_id: UserDep, accounts: AccountsDep, store: StoreDep) -> dict:
    """Delete every CV, job description and interview transcript. The subscription and
    this month's usage are kept so billing stays correct."""
    docs = await store.list_documents(user_id)
    for d in docs:
        await store.delete(user_id, d.id)
    sessions = await accounts.delete_history(user_id)
    return {"deleted_documents": len(docs), "deleted_interviews": sessions}
