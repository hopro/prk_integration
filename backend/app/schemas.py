from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class LoginSchema(BaseModel):
    user: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)


class PersonSchema(BaseModel):
    fam: str = Field(..., max_length=40)
    im: str = Field(..., max_length=40)
    ot: str = Field(..., max_length=40)
    dr: date
    vpolis: int = Field(..., ge=1, le=3)
    npolis: str = Field(..., max_length=16)

    @field_validator("fam", "im", "ot")
    @classmethod
    def validate_fio_chars(cls, v: str) -> str:
        if not v:
            return v
        allowed = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ -.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        for ch in v:
            if ch not in allowed:
                raise ValueError(f"Недопустимый символ '{ch}' в ФИО")
        return v.strip()


class AttachmentSchema(BaseModel):
    typeprk: int = Field(..., ge=1, le=3)
    mo: int = Field(..., ge=1, le=9999)
    # Код подразделения. Раньше стояло max_length=8, и выбор участка с длинным
    # названием ЕЦП («30100_ГП3») давал 422 «String should have at most 8
    # characters»: запрос отбрасывался целиком, запись не попадала ни в ЕЦП,
    # ни в историю. Ограничение ослаблено — несовпадение кода теперь
    # диагностируется сопоставлением участков, а не ошибкой валидации.
    podr: str = Field(..., min_length=1, max_length=64)
    dbeg: date
    meth: int = Field(..., ge=1, le=2)


class ErrorSchema(BaseModel):
    errcode: int
    errname: str
    comment: str


class ResultSchema(BaseModel):
    timeoper: datetime
    ack: int
    errors: list[ErrorSchema] = []


class MisSavePersonCardData(BaseModel):
    Person_id: str
    PersonCard_id: str
    PersonCard_Code: str
    Server_id: str = "13003795"
    action: str = "add"
    LpuRegionType_id: str = "1"
    LpuAttachType_id: str = "1"
    isPersonCardAttach: str = "1"


class SavePersonCardRequest(BaseModel):
    Person_id: str
    PersonCard_id: str
    PersonCard_Code: str
    # Server_id различается у разных пациентов и приходит из их карты ЕЦП.
    # Раньше здесь был зашит 13003795, из-за чего пациенты других ЛПУ
    # прикреплялись не к своему учреждению.
    Server_id: str | None = None
    Lpu_id: str
    LpuRegion_id: str
    action: str = "add"
    LpuRegionType_id: str = "1"
    LpuAttachType_id: str = "1"
    isPersonCardAttach: str = "1"


class LoadPrkRequest(BaseModel):
    login: LoginSchema
    person: PersonSchema
    prk_list: list[AttachmentSchema] = Field(..., min_length=1)
    mis_save_data: Optional[MisSavePersonCardData] = None


class LoadPrkResponse(BaseModel):
    success: bool
    person: PersonSchema
    prk_list: list[AttachmentSchema]
    result: Optional[ResultSchema] = None
    error_message: Optional[str] = None
    mis_save_result: Optional[dict] = None


class InsCheckRequest(BaseModel):
    login: LoginSchema
    nrec: str = Field(..., max_length=32)
    date1: date
    date2: date
    type_org: int = Field(..., ge=1, le=3)
    code_org: int = Field(..., ge=0, le=9999)
    fam: str = ""
    im: str = ""
    ot: str = ""
    w: Optional[int] = Field(None, ge=1, le=2)
    dr: Optional[date] = None
    vpolis: Optional[int] = Field(None, ge=1, le=3)
    npolis: str = ""
    doctype: Optional[int] = None
    docser: str = ""
    docnum: str = ""
    snils: str = ""
    mr: str = ""

    @field_validator("dr", mode="before")
    @classmethod
    def blank_date_to_none(cls, v: object) -> object:
        if v == "" or v is None:
            return None
        return v


class SpDeptEntry(BaseModel):
    code: str
    name: str


class InsCheckError(BaseModel):
    errcode: int
    errtext: str


class InsuranceInfo(BaseModel):
    smo: Optional[int] = None
    vpolis: Optional[int] = None
    fpolis: Optional[int] = None
    npolis: str = ""
    dvisit: Optional[date] = None
    dbeg: Optional[date] = None
    dend: Optional[date] = None
    reason: Optional[int] = None
    id: Optional[int] = None


class CheckPrkInfo(BaseModel):
    mo: Optional[int] = None
    modt: Optional[date] = None
    podr: str = ""


class InsCheckResponse(BaseModel):
    success: bool
    nrec: str
    ack: int
    errors: list[InsCheckError] = []
    algs: list[str] = []
    insurance: Optional[InsuranceInfo] = None
    attachment: Optional[CheckPrkInfo] = None
    p_disp: str = ""
    p_proph: str = ""
    p_healthc: str = ""
    error_message: Optional[str] = None


class PrkHistoryAttachment(BaseModel):
    typeprk: int
    mo: int
    podr: str
    dbeg: str
    meth: int


class PrkHistoryItem(BaseModel):
    id: int
    created_at: str
    success: bool
    error_message: Optional[str] = None
    fam: str
    im: str
    ot: str
    dr: str
    vpolis: int
    npolis: str
    ack: Optional[int] = None
    timeoper: Optional[str] = None
    errors: list[dict] = []
    attachments: list[PrkHistoryAttachment] = []


class PrkHistoryResponse(BaseModel):
    items: list[PrkHistoryItem]
    total: int
    page: int
    limit: int


class GenerateScdRequest(BaseModel):
    fam: str = Field(..., max_length=40)
    im: str = Field(..., max_length=40)
    ot: str = Field("", max_length=40)
    dr: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    w: int = Field(..., ge=1, le=2)
    vpolis: int = Field(..., ge=1, le=3)
    npolis: str = Field(..., max_length=16)
    snils: str = Field("", max_length=14)


class PrkStats(BaseModel):
    total: int
    success: int
    failed: int
