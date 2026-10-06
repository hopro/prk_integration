export interface LoginData {
  user: string;
  password: string;
}

export interface MisCredentialsStatus {
  mis_login: string;
  password_set: boolean;
  updated_at: string | null;
}

export interface SettingsData {
  user: string;
  password: string;
  defaultMo: string;
  misLpuId: string;
  misLogin: string;
  misPassword: string;
  /** Адрес ИАС для прикрепления ЗЛ (SOAP LoadPrk). */
  iasUrl: string;
  /** Адрес ИАС для проверки полиса (SOAP GetInsPrkState). */
  iasCheckUrl: string;
  /** Кодировка XML-выгрузок ТФОМС (обычно windows-1251). */
  tfomsEncoding: string;
  /** Адрес ЕЦП. Фактическое значение уточняется со шлюза. */
  ecpUrl: string;
  /** Фактическое состояние учётных данных ЕЦП по данным шлюза. */
  misStatus?: MisCredentialsStatus | null;
}

export interface DictionaryItem {
  kind: 'regions' | 'spmo' | 'spsmo' | 'spdiv' | 'spdept';
  title: string;
  /** Область действия: Lpu_id для участков, код МО для подразделений. */
  scope: string;
  scopeLabel: string;
  rows: number;
  loadedAt: string | null;
  source: string;
}

export interface DictionarySource {
  kind: string;
  file: string;
  title: string;
  path: string | null;
  size: number | null;
}

export interface DictionarySources {
  directory: string;
  found: DictionarySource[];
  missing: DictionarySource[];
}

export interface DictionaryLoadLog {
  kind: string;
  scope: string;
  rows_loaded: number;
  source: string;
  status: string;
  message: string;
  created_at: string;
}

export interface DictionaryRow {
  region_id?: string;
  code?: string;
  name?: string;
  extra?: string;
  descr?: string;
  med_personal_fio?: string;
  beg_date?: string;
  end_date?: string;
  sync_status?: string;
  scope?: string;
  loaded_at?: string;
}

export interface PersonData {
  fam: string;
  im: string;
  ot: string;
  dr: string;
  pol: string;
  vpolis: number;
  npolis: string;
}

export interface AttachmentData {
  typeprk: number;
  mo: number;
  podr: string;
  dbeg: string;
  meth: number;
}

export interface MisSavePersonCardData {
  Person_id: string;
  PersonCard_id: string;
  PersonCard_Code: string;
  Server_id?: string;
  action?: string;
  LpuRegionType_id?: string;
  LpuAttachType_id?: string;
  isPersonCardAttach?: string;
}

export interface LoadPrkRequest {
  login: LoginData;
  person: PersonData;
  prk_list: AttachmentData[];
  mis_save_data?: MisSavePersonCardData;
}

export interface ErrorInfo {
  errcode: number;
  errname: string;
  comment: string;
}

export interface ResultData {
  timeoper: string;
  ack: number;
  errors: ErrorInfo[];
}

export interface LoadPrkResponse {
  success: boolean;
  person: PersonData;
  prk_list: AttachmentData[];
  result: ResultData | null;
  error_message: string | null;
  mis_save_result?: any;
}

export interface InsCheckRequest {
  login: LoginData;
  nrec: string;
  date1: string;
  date2: string;
  type_org: number;
  code_org: number;
  fam: string;
  im: string;
  ot: string;
  w: number | null;
  dr: string | null;
  vpolis: number | null;
  npolis: string;
  doctype: number | null;
  docser: string;
  docnum: string;
  snils: string;
  mr: string;
}

export interface InsCheckError {
  errcode: number;
  errtext: string;
}

export interface InsuranceInfo {
  smo: number | null;
  vpolis: number | null;
  fpolis: number | null;
  npolis: string;
  dvisit: string | null;
  dbeg: string | null;
  dend: string | null;
  reason: number | null;
  id: number | null;
}

export interface CheckPrkInfo {
  mo: number | null;
  modt: string | null;
  podr: string;
}

export interface SpmoEntry {
  code: number;
  name: string;
}

export interface SpDeptEntry {
  /** Код подразделения, который уходит в ИАС-4 в поле podr. */
  code: string;
  /** Название для показа пользователю. */
  name: string;
  /** Название участка в ЕЦП — может отличаться от name. */
  ecpName?: string;
}

export interface InsCheckResponse {
  success: boolean;
  nrec: string;
  ack: number;
  errors: InsCheckError[];
  algs: string[];
  insurance: InsuranceInfo | null;
  attachment: CheckPrkInfo | null;
  p_disp: string;
  p_proph: string;
  p_healthc: string;
  error_message: string | null;
}

export interface MisUnifiedResponse {
  success: boolean;
  data: any;
  error: { code: string; message: string } | null;
}

export interface MisPatient {
  Person_id: string;
  Server_id: string;
  PersonSurName_SurName: string;
  PersonFirName_FirName: string;
  PersonSecName_SecName: string;
  PersonBirthDay_BirthDay: string;
  Person_Snils: string;
  Polis_Num: string;
  Polis_Ser: string;
  [key: string]: any;
}

export interface MisPersonCard {
  Person_id: string;
  Server_id: string;
  PersonSurName_SurName: string;
  PersonFirName_FirName: string;
  PersonSecName_SecName: string;
  PersonBirthDay_BirthDay: string;
  Person_Snils: string;
  Polis_Num: string;
  Polis_Ser: string;
  LpuRegion_Name?: string;
  [key: string]: any;
}

export interface MisRegion {
  LpuRegion_id: string;
  LpuRegion_Name: string;
  [key: string]: any;
}

export interface PrkHistoryAttachment {
  typeprk: number;
  mo: number;
  podr: string;
  dbeg: string;
  meth: number;
}

export interface PrkHistoryItem {
  id: number;
  created_at: string;
  success: boolean;
  error_message: string | null;
  fam: string;
  im: string;
  ot: string;
  dr: string;
  vpolis: number;
  npolis: string;
  ack: number | null;
  timeoper: string | null;
  errors: any[];
  /** Результат отправки в ЕЦП: null — отправка не выполнялась. */
  misSave: { success: boolean; error?: string } | null;
  attachments: PrkHistoryAttachment[];
}

export interface PrkHistoryResponse {
  items: PrkHistoryItem[];
  total: number;
  page: number;
  limit: number;
}

export interface PrkStats {
  total: number;
  success: number;
  failed: number;
  /** Сколько записей дошло до этапа отправки в ЕЦП. */
  ecpAttempted: number;
  ecpSuccess: number;
  ecpFailed: number;
}
