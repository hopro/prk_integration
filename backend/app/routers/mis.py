import logging

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from app.services import mis_client
from app.schemas import SavePersonCardRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mis", tags=["mis"])


class MiSearchRequest(BaseModel):
    params: dict[str, Any]


class MiPersonCardRequest(BaseModel):
    params: dict[str, Any]


class MiRegionsRequest(BaseModel):
    params: dict[str, Any]


@router.post("/search-patients")
async def search_patients(req: MiSearchRequest):
    try:
        result = await mis_client.search_patients(req.params)
        return result
    except Exception as e:
        logger.exception("MIS search-patients failed")
        return {"success": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}}


@router.post("/get-person-card")
async def get_person_card(req: MiPersonCardRequest):
    try:
        result = await mis_client.get_person_card(req.params)
        return result
    except Exception as e:
        logger.exception("MIS get-person-card failed")
        return {"success": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}}


@router.post("/get-regions-id")
async def get_regions_id(req: MiRegionsRequest):
    try:
        result = await mis_client.get_regions_id(req.params)
        return result
    except Exception as e:
        logger.exception("MIS get-regions-id failed")
        return {"success": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}}


@router.post("/save-person-card")
async def save_person_card(req: SavePersonCardRequest):
    try:
        result = await mis_client.save_person_card(req.model_dump())
        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("Error_Msg") or result.get("error", {}).get("message") or str(result)
            return {"success": False, "error": {"code": "GATEWAY_ERROR", "message": error_msg}}
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": {"code": "PROXY_ERROR", "message": str(e)}}
