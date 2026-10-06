from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UnifiedResponse(BaseModel):
    success: bool = Field(..., description="Флаг успеха")
    data: Any = Field(None, description="Тело ответа (данные МИС)")
    error: dict | None = Field(None, description="Объект ошибки при success=false")


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Код ошибки")
    message: str = Field(..., description="Текст ошибки")


class UnifiedErrorResponse(BaseModel):
    success: bool = False
    data: None = None
    error: ErrorDetail


class SearchPatientsRequest(BaseModel):
    PersonSurName_SurName: str = Field("", description="Фамилия пациента")
    PersonFirName_FirName: str = Field("", description="Имя пациента")
    PersonSecName_SecName: str = Field("", description="Отчество пациента")
    PersonBirthDay_BirthDay: str = Field("", description="Дата рождения (ДД.ММ.ГГГГ)")
    Person_id: str = Field("", description="ID пациента в МИС")
    Person_Snils: str = Field("", description="СНИЛС")
    Person_Inn: str = Field("", description="ИНН")
    Polis_Ser: str = Field("", description="Серия полиса")
    Polis_Num: str = Field("", description="Номер полиса")
    Polis_EdNum: str = Field("", description="Единый номер полиса")
    page: int = Field(1, description="Номер страницы", ge=1)
    start: int = Field(0, description="Смещение от начала выборки", ge=0)
    limit: int = Field(100, description="Количество записей на странице", ge=1, le=1000)
    searchMode: str = Field("all", description="Режим поиска: all / simple")
    showAll: int = Field(1, description="Показывать все (1) или только основные (0)")


class SearchPatientsResponseItem(BaseModel):
    Person_id: str = Field(..., description="ID пациента")
    Server_id: str = Field(..., description="ID сервера (ЛПУ)")
    PersonEvn_id: str = Field(..., description="ID события")
    PersonSurName_SurName: str = Field("", description="Фамилия")
    PersonFirName_FirName: str = Field("", description="Имя")
    PersonSecName_SecName: str = Field("", description="Отчество")
    PersonBirthDay_BirthDay: str = Field("", description="Дата рождения")
    Person_Snils: str = Field("", description="СНИЛС")
    Person_Inn: str = Field("", description="ИНН")
    Person_Phone: str | None = Field(None, description="Телефон")
    Person_IsDead: str = Field("false", description="Признак смерти")
    UAddress_AddressText: str = Field("", description="Адрес регистрации")
    PAddress_AddressText: str = Field("", description="Адрес проживания")
    Polis_Ser: str | None = Field(None, description="Серия полиса")
    Polis_Num: str | None = Field(None, description="Номер полиса")


class SearchPatientsResponse(BaseModel):
    data: list[SearchPatientsResponseItem] = Field(..., description="Список найденных пациентов")


class GetPatientInfoRequest(BaseModel):
    Person_id: str = Field(..., description="ID пациента в МИС", examples=["660910003025820"])
    Server_id: str = Field(..., description="ID сервера (ЛПУ)", examples=["13003795"])
    type: int = Field(1, description="Тип запроса")
    userMedStaffFact_id: int | str = Field("", description="ID медсотрудника (если требуется)")
    userLpuUnitType_SysNick: str = Field("polka", description="Системный ник подразделения ЛПУ")


class PersonInfo(BaseModel):
    Person_id: str = Field(..., description="ID пациента")
    PersonEvn_id: str = Field(..., description="ID события")
    Server_id: str = Field(..., description="ID сервера")
    Server_pid: str = Field(..., description="ID сервера (персональный)")
    Person_Birthday: str = Field("", description="Дата рождения (ДД.ММ.ГГГГ)")
    Person_Age: str = Field("", description="Возраст (лет)")
    Person_AgeMonth: str = Field("", description="Возраст (месяцев)")
    Person_IsDead: str | None = Field(None, description="Признак смерти")
    Sex_Name: str = Field("", description="Пол")
    Lpu_Nick: str = Field("", description="Наименование ЛПУ")
    Person_Snils: str = Field("", description="СНИЛС")
    Person_Inn: str = Field("", description="ИНН")
    Person_Phone: str = Field("", description="Телефон")
    Person_PAddress: str = Field("", description="Адрес проживания")
    Person_RAddress: str = Field("", description="Адрес регистрации")
    PersonCard_id: str = Field("", description="ID карты")
    PersonCard_Code: str = Field("", description="Номер карты")
    PersonCard_begDate: str = Field("", description="Дата начала карты")
    PersonCard_endDate: str = Field("", description="Дата окончания карты")


class GetPatientInfoResponse(BaseModel):
    Error_Msg: str = Field("", description="Текст ошибки (пусто при успехе)")
    personInfo: list[PersonInfo] = Field(..., description="Информация о пациенте")


class SavePersonCardRequest(BaseModel):
    Person_id: str = Field(..., description="ID пациента", examples=["660910003025820"])
    Server_id: str = Field(..., description="ID сервера (ЛПУ)", examples=["13003795"])
    accessType: str = Field("edit", description="Тип доступа: edit / add")
    PersonCard_id: str = Field("", description="ID карты (для редактирования)")
    PersonCardAttach_id: str = Field("", description="ID прикрепления")
    PersonCard_Code: str = Field("", description="Номер карты")
    Lpu_id: str = Field("", description="ID ЛПУ")
    LpuRegion_id: int | str = Field("", description="ID участка")
    LpuAttachType_id: int | str = Field("", description="ID типа прикрепления")
    PersonCard_begDate: str = Field("", description="Дата начала (ДД.ММ.ГГГГ)")
    PersonCard_endDate: str = Field("", description="Дата окончания (ДД.ММ.ГГГГ)")
    PersonCardAttach_setDate: str = Field("", description="Дата прикрепления (ГГГГ-ММ-ДД)")
    PersonCard_IsAttachCondit: int = Field(0, description="Условное прикрепление (0/1)")
    PersonCard_OrderNumber: str = Field("", description="Номер приказа")


class SavePersonCardResponse(BaseModel):
    success: bool = Field(..., description="Флаг успеха операции")
    Error_Code: str | None = Field(None, description="Код ошибки")
    Error_Msg: str = Field("", description="Текст ошибки (пусто при успехе)")
    PersonCard_id: str = Field("", description="ID карты")
    PersonCardAttach_id: str | None = Field(None, description="ID прикрепления")


class GetPersonCardRequest(BaseModel):
    Person_id: str = Field(..., description="ID пациента", examples=["660910003025820"])
    Server_id: str = Field(..., description="ID сервера (ЛПУ)", examples=["13003795"])
    mode: str = Field("PersonInformationPanel", description="Режим загрузки данных")
    additionalFields: str = Field("[]", description="Дополнительные поля (JSON-массив)")


class PersonCardData(BaseModel):
    Person_id: str = Field(..., description="ID пациента")
    PersonEvn_id: str = Field(..., description="ID события")
    Server_id: str = Field(..., description="ID сервера")
    Server_pid: str = Field(..., description="ID сервера (персональный)")
    Person_Birthday: str = Field("", description="Дата рождения")
    Person_Age: str = Field("", description="Возраст")
    Person_Phone: str = Field("", description="Телефон")
    Person_PAddress: str = Field("", description="Адрес проживания")
    Lpu_Nick: str = Field("", description="Наименование ЛПУ")
    PersonCard_id: str = Field("", description="ID карты")
    PersonCard_Code: str = Field("", description="Номер карты")
    PersonCard_begDate: str = Field("", description="Дата начала карты")
    PersonCard_endDate: str = Field("", description="Дата окончания карты")
    LpuRegion_Name: str = Field("", description="Номер участка")


class GetRegionsIdRequest(BaseModel):
    LpuRegion_id: str = Field("", description="ID участка (для фильтра)")
    syncStatus: str = Field("", description="Статус синхронизации")
    LpuRegion_Name: str = Field("", description="Номер участка (фильтр)")
    LpuRegion_begDate: str = Field("", description="Дата начала (фильтр)")
    LpuRegion_endDate: str = Field("", description="Дата окончания (фильтр)")
    LpuRegion_Descr: str = Field("", description="Описание участка (фильтр)")
    LpuRegionType_Name: str = Field("", description="Тип участка (фильтр)")
    LpuRegionTipUch: str = Field("", description="Тип участка (ID, фильтр)")
    LpuRegion_Status: str = Field("", description="Статус участка (фильтр)")
    MedPersonal_FIO: str = Field("", description="ФИО врача (фильтр)")
    object: str = Field("LpuRegion", description="Тип объекта")
    isClose: str = Field("1", description="Фильтр по статусу (1 — действующие)")
    Lpu_id: str = Field(..., description="ID ЛПУ", examples=["13003795"])


class LpuRegionItem(BaseModel):
    LpuRegion_id: str = Field(..., description="ID участка")
    LpuRegion_Name: str = Field(..., description="Номер участка")
    LpuRegion_Descr: str = Field("", description="Описание участка")
    LpuRegionType_id: str = Field(..., description="ID типа участка")
    LpuRegion_begDate: str = Field("", description="Дата начала")
    LpuRegion_endDate: str | None = Field(None, description="Дата закрытия")
    MedPersonal_FIO: str = Field("", description="ФИО врача")
    syncStatus: str = Field("", description="Статус синхронизации")
    Lpu_id: str = Field(..., description="ID ЛПУ")
