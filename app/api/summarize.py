import threading
from uuid import uuid4

from fastapi import Depends, HTTPException, APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import MAX_QUEUE_SIZE, MODEL_NAME
from app.core.log import log
from app.core.runtime import queue_lock, task_queue, task_status
from app.db.database import get_session
from app.db.models import Summary
from app.schemas.summary import StatusResponse, URLRequest
from app.services.summarize import process_queue_item

router = APIRouter()


class QueueResponse(BaseModel):
    request_id: str


@router.post("/summarize", response_model=QueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def queue_summary_task(request: URLRequest, session: AsyncSession = Depends(get_session)):
    url = str(request.url)  # important if URLRequest.url becomes HttpUrl/AnyUrl
    log.info(f"📥 New request for URL: {url}")

    result = await session.execute(select(Summary).where(Summary.url == url))
    existing = result.scalar_one_or_none()

    if existing and existing.status == "success":
        log.info(f"⚠️ URL already successfully processed and result will be replaced: {url}")

    request_id = str(uuid4())

    model = MODEL_NAME if len(str(request.model).strip()) == 0 else request.model

    with queue_lock:
        if len(task_queue) >= MAX_QUEUE_SIZE:
            log.warning(f"🚫 Queue full. Rejected URL: {url}")
            raise HTTPException(status_code=429, detail="Queue is full. Try again later.")

        task_queue.append(request_id)
        task_status[request_id] = {
            "status": "in_progress",
            "request": {"url": url},
        }

    if not existing:
        session.add(Summary(url=url, status="in_progress", model=model))

    else:
        existing.status = "in_progress"
        existing.result = None
        existing.error = None

    await session.commit()
    log.info(f"🟡 Added to queue: request_id={request_id}, url={url}")

    threading.Thread(
        target=process_queue_item,
        args=(request_id,),
        daemon=True,
        name=f"summarize-{request_id[:8]}",
    ).start()

    return QueueResponse(request_id=request_id)


@router.get("/status/{request_id}", response_model=StatusResponse)
def get_status(request_id: str):
    with queue_lock:
        entry = task_status.get(request_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Request not found")

    status_ = entry["status"]

    if status_ == "in_progress":
        return StatusResponse(status="in_progress")
    if status_ == "success":
        return StatusResponse(status="success", result=entry.get("result"))
    return StatusResponse(status="failure", error=entry.get("error"))
