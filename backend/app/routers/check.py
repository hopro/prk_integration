import logging

from fastapi import APIRouter, HTTPException

from app.schemas import InsCheckRequest, InsCheckResponse
from app.services.soap_client import send_get_ins_prk_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ins-check", tags=["ins-check"])


@router.post("/check", response_model=InsCheckResponse)
async def check_ins_prk(request: InsCheckRequest):
    try:
        result = await send_get_ins_prk_state(request)
        return result
    except Exception as e:
        logger.exception("Error processing GetInsPrkState request")
        raise HTTPException(status_code=500, detail=str(e))
