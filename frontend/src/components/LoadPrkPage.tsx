import { useState, useEffect } from 'react';
import {
  Stepper, Step, StepLabel, Button, Box, CircularProgress, Alert, Paper, Typography,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import PersonForm from './PersonForm';
import PatientSearch from './PatientSearch';
import PatientCard from './PatientCard';
import AttachmentList from './AttachmentList';
import ResultPanel from './ResultPanel';
import ConfirmDialog from './ConfirmDialog';
import { sendLoadPrk, downloadScd, parseAsc } from '../api/prk';
import { sendInsCheck } from '../api/check';
import { getRegionsId, savePersonCard } from '../api/mis';
import { fetchRegionsForPatient } from '../api/dictionaries';
import type { PersonData, AttachmentData, LoadPrkResponse, SettingsData, MisPersonCard, InsCheckResponse } from '../types';

type ViewMode = 'search' | 'card' | 'form' | 'attachments' | 'result';

const STORAGE_KEY_PERSON = 'prk_person';
const STORAGE_KEY_ATTACHMENTS = 'prk_attachments';

function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

const steps = ['Данные пациента', 'Прикрепления', 'Результат'];

const defaultPerson: PersonData = { fam: '', im: '', ot: '', dr: '', pol: '', vpolis: 3, npolis: '' };
const today = new Date().toISOString().slice(0, 10);
const defaultAttachments: AttachmentData[] = [
  { typeprk: 1, mo: 893, podr: '', dbeg: today, meth: 2 },
];

function parseMisDate(dateStr: string): string {
  if (!dateStr) return '';
  const parts = dateStr.split(/[./\-]/);
  if (parts.length === 3) {
    const [d, m, y] = parts;
    if (y && y.length === 4) return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
    if (d && d.length === 4) return `${d}-${m.padStart(2, '0')}-${y.padStart(2, '0')}`;
  }
  return dateStr;
}

function formatSnils(snils: string): string {
  const digits = snils.replace(/\D/g, '');
  if (digits.length !== 11) return snils;
  return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 9)} ${digits.slice(9)}`;
}

function generateNrec(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 32);
  }
  const arr = new Uint8Array(16);
  for (let i = 0; i < 16; i++) arr[i] = Math.floor(Math.random() * 256);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

function getCurrentMonthDates() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return {
    date1: `${year}-${month}-01`,
    date2: `${year}-${month}-${day}`,
  };
}

interface Props {
  settings: SettingsData;
  spmoMap: Record<number, string>;
  spsmoMap: Record<number, string>;
}

export default function LoadPrkPage({ settings, spmoMap, spsmoMap }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('search');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [person, setPerson] = useState<PersonData>(() =>
    loadFromStorage(STORAGE_KEY_PERSON, defaultPerson),
  );
  const [attachments, setAttachments] = useState<AttachmentData[]>(() =>
    loadFromStorage(STORAGE_KEY_ATTACHMENTS, defaultAttachments),
  );
  const [response, setResponse] = useState<LoadPrkResponse | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const [misAttachment, setMisAttachment] = useState<{
    lpuNick: string;
    begDate: string;
    regionName: string;
    regionDescr: string;
    medPersonalFio: string;
    lpuRegionId: string;
  } | null>(null);
  const [searchKey, setSearchKey] = useState(0);
  const [misCardData, setMisCardData] = useState<{
    Person_id: string;
    PersonCard_id: string;
    PersonCard_Code: string;
    // Server_id различается у разных пациентов и приходит из карты ЕЦП.
    Server_id: string;
  } | null>(null);
  const [rawCardData, setRawCardData] = useState<MisPersonCard | null>(null);

  const [insCheckResponse, setInsCheckResponse] = useState<InsCheckResponse | null>(null);
  const [insCheckLoading, setInsCheckLoading] = useState(false);
  const [insCheckError, setInsCheckError] = useState<string | null>(null);

  const [syncLoading, setSyncLoading] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncSuccess, setSyncSuccess] = useState(false);

  const [ascData, setAscData] = useState<any>(null);
  const [ascDialogOpen, setAscDialogOpen] = useState(false);
  const [ascError, setAscError] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_PERSON, JSON.stringify(person));
  }, [person]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_ATTACHMENTS, JSON.stringify(attachments));
  }, [attachments]);

  const handlePatientSelected = async (card: MisPersonCard) => {
    const sexId = String((card as any).Sex_id || '');
    const pol = sexId === '1' ? 'М' : sexId === '2' ? 'Ж' : '';

    const newPerson: PersonData = {
      fam: card.PersonSurName_SurName || '',
      im: card.PersonFirName_FirName || '',
      ot: card.PersonSecName_SecName || '',
      dr: parseMisDate(card.PersonBirthDay_BirthDay || ''),
      pol,
      vpolis: person.vpolis || 3,
      npolis: card.Polis_Num || person.npolis,
    };
    setPerson(newPerson);
    setMisCardData({
      Person_id: card.Person_id || '',
      PersonCard_id: (card as any).PersonCard_id || '',
      PersonCard_Code: (card as any).PersonCard_Code || '',
      Server_id: String((card as any).Server_id || ''),
    });
    setRawCardData(card);
    setViewMode('card');
    setInsCheckResponse(null);
    setInsCheckError(null);

    // Load MIS attachment info
    const lpuNick = (card as any).Lpu_Nick || '';
    const begDate = (card as any).PersonCard_begDate || '';
    const lpuId = (card as any).Lpu_id;
    const lpuRegionName = card.LpuRegion_Name || '';

    if (lpuId) {
      try {
        // Сначала локальный кэш участков (вкладка «Справочники»), при его пустоте — ЕЦП.
        const { regions } = await fetchRegionsForPatient(String(lpuId), async (id) => {
          const resp = await getRegionsId({ Lpu_id: id });
          if (Array.isArray(resp.data)) return resp.data;
          const nested = resp.data as any;
          if (nested && typeof nested === 'object') {
            const list = nested.data || nested.rows || nested.items || [];
            if (Array.isArray(list)) return list;
          }
          return [];
        });

        // Кэш отдаёт нормализованные имена полей, ЕЦП — свои.
        const regionName = (r: any) => (r.name ?? r.LpuRegion_Name ?? '').toString().trim();
        const regionDescr = (r: any) => (r.descr ?? r.LpuRegion_Descr ?? '').toString();
        const regionFio = (r: any) => (r.med_personal_fio ?? r.MedPersonal_FIO ?? '').toString();
        const regionId = (r: any) => (r.region_id ?? r.LpuRegion_id ?? '').toString();

        if (regions.length > 0) {
          const trimmedName = lpuRegionName.trim();
          const lowered = trimmedName.toLowerCase();
          const region = trimmedName
            ? regions.find((r: any) => regionName(r) === trimmedName)
              || regions.find((r: any) => regionName(r).toLowerCase() === lowered)
              || regions.find((r: any) => {
                  const name = regionName(r).toLowerCase();
                  return name && (name.includes(lowered) || lowered.includes(name));
                })
              || regions[0]
            : regions[0];
          if (region) {
            setMisAttachment({
              lpuNick,
              begDate,
              regionName: regionName(region),
              regionDescr: regionDescr(region),
              medPersonalFio: regionFio(region),
              lpuRegionId: regionId(region),
            });
          } else {
            setMisAttachment({ lpuNick, begDate, regionName: '', regionDescr: '', medPersonalFio: '', lpuRegionId: '' });
          }
        } else {
          setMisAttachment({ lpuNick, begDate, regionName: '', regionDescr: '', medPersonalFio: '', lpuRegionId: '' });
        }
      } catch {
        setMisAttachment({ lpuNick, begDate, regionName: '', regionDescr: '', medPersonalFio: '', lpuRegionId: '' });
      }
    } else {
      setMisAttachment(lpuNick || begDate ? { lpuNick, begDate, regionName: '', regionDescr: '', medPersonalFio: '', lpuRegionId: '' } : null);
    }
  };

  const handleManualEntry = () => {
    setPerson(defaultPerson);
    setMisAttachment(null);
    setMisCardData(null);
    setRawCardData(null);
    setViewMode('form');
    setInsCheckResponse(null);
    setInsCheckError(null);
  };

  const handleCheckIns = async () => {
    setInsCheckLoading(true);
    setInsCheckError(null);
    setInsCheckResponse(null);
    setSyncError(null);
    setSyncSuccess(false);

    const { date1, date2 } = getCurrentMonthDates();
    const nrec = generateNrec();
    const w = person.pol === 'М' ? 1 : person.pol === 'Ж' ? 2 : null;

    try {
      const result = await sendInsCheck({
        login: { user: settings.user, password: settings.password },
        nrec,
        date1,
        date2,
        type_org: 1,
        code_org: Number(settings.defaultMo) || 0,
        fam: person.fam,
        im: person.im,
        ot: person.ot,
        w,
        dr: person.dr || null,
        vpolis: person.vpolis || null,
        npolis: person.npolis,
        doctype: null,
        docser: '',
        docnum: '',
        snils: formatSnils(rawCardData?.Person_Snils || ''),
        mr: '',
      });
      setInsCheckResponse(result);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : e?.message || 'Ошибка отправки запроса';
      setInsCheckError(msg);
    } finally {
      setInsCheckLoading(false);
    }
  };

  const handleSyncWithTfoms = async () => {
    if (settings.misStatus && !settings.misStatus.password_set) {
      setSyncError('Не заданы логин и пароль ЕЦП. Откройте настройки (шестерёнка) и сохраните их.');
      setSyncSuccess(false);
      return;
    }
    setSyncLoading(true);
    setSyncError(null);
    setSyncSuccess(false);
    try {
      // Lookup LpuRegion_id from ИАС result's attachment podr
      let lpuRegionId = misAttachment?.lpuRegionId || '';
      const insPodr = insCheckResponse?.attachment?.podr;
      if (insPodr && settings.misLpuId) {
        try {
          const regionResp = await getRegionsId({ Lpu_id: settings.misLpuId });
          let syncRegions: any[] = [];
          if (Array.isArray(regionResp.data)) {
            syncRegions = regionResp.data;
          } else if (regionResp.data && typeof regionResp.data === 'object') {
            syncRegions = (regionResp.data as any).data || (regionResp.data as any).rows || (regionResp.data as any).items || [];
            if (!Array.isArray(syncRegions)) syncRegions = [];
          }
          if (regionResp.success && syncRegions.length > 0) {
            const trimmedPodr = insPodr.trim();
            const region = syncRegions.find((r: any) => r.LpuRegion_Name?.trim() === trimmedPodr)
              || syncRegions.find((r: any) => r.LpuRegion_Name?.trim().toLowerCase() === trimmedPodr.toLowerCase())
              || syncRegions.find((r: any) => r.LpuRegion_Name?.trim().toLowerCase().includes(trimmedPodr.toLowerCase()) || trimmedPodr.toLowerCase().includes(r.LpuRegion_Name?.trim().toLowerCase()));
            if (region?.LpuRegion_id) {
              lpuRegionId = String(region.LpuRegion_id);
            }
          }
        } catch {
          // fallback to current attachment region
        }
      }
      const result = await savePersonCard({
        Person_id: misCardData?.Person_id || '',
        PersonCard_id: misCardData?.PersonCard_id || '',
        PersonCard_Code: misCardData?.PersonCard_Code || '',
        Server_id: misCardData?.Server_id || settings.misLpuId || '',
        Lpu_id: settings.misLpuId || '',
        LpuRegion_id: lpuRegionId,
      });
      if (result.success && result.data?.success !== false && !result.data?.Error_Msg) {
        setSyncSuccess(true);
      } else {
        const errMsg = result.data?.Error_Msg || result.error?.message || result.data?.error_message || 'Ошибка синхронизации';
        setSyncError(errMsg);
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : e?.response?.data?.error?.message || e?.message || 'Ошибка синхронизации';
      setSyncError(msg);
    } finally {
      setSyncLoading(false);
    }
  };

  const handleBackToCard = () => {
    setViewMode('card');
  };

  const handleGenerateScd = () => {
    const w = person.pol === 'М' ? 1 : 2;
    downloadScd({
      fam: person.fam,
      im: person.im,
      ot: person.ot,
      dr: person.dr,
      w,
      vpolis: person.vpolis,
      npolis: person.npolis,
      snils: rawCardData?.Person_Snils || undefined,
    });
  };

  const handleUploadAsc = async (file: File) => {
    setAscError(null);
    setAscData(null);
    try {
      const result = await parseAsc(file);
      if (result.success) {
        setAscData(result.data);
      } else {
        setAscError(result.error || 'Ошибка парсинга ASC');
      }
    } catch (e: any) {
      setAscError(e?.message || 'Ошибка загрузки ASC');
    }
    setAscDialogOpen(true);
  };

  const handleChangeAttachment = () => {
    setViewMode('form');
  };

  const handleNext = () => {
    setViewMode('attachments');
  };

  const handleBack = () => {
    setViewMode('form');
  };

  const handleSubmit = () => {
    if (!settings.user || !settings.password) {
      setError('Не указаны логин и пароль ИАС-4. Откройте настройки (шестерёнка) и введите учётные данные.');
      return;
    }
    setConfirmOpen(true);
  };

  const handleSend = async () => {
    setLoading(true);
    setError(null);
    try {
      const mis_save_data = misCardData
        ? {
            Person_id: misCardData.Person_id,
            PersonCard_id: misCardData.PersonCard_id,
            PersonCard_Code: misCardData.PersonCard_Code,
            Server_id: misCardData.Server_id || undefined,
          }
        : undefined;
      const result = await sendLoadPrk({
        login: { user: settings.user, password: settings.password },
        person,
        prk_list: attachments,
        mis_save_data,
      });
      setResponse(result);
      setViewMode('result');
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : typeof detail === 'object' && detail !== null
            ? JSON.stringify(detail)
            : e?.message || 'Ошибка отправки запроса';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = () => {
    setConfirmOpen(false);
    handleSend();
  };

  const canProceedForm = (): boolean =>
    person.fam !== '' && person.im !== '' && person.dr !== '' && person.npolis !== '';

  const canProceedAttachments = (): boolean =>
    attachments.every((a) => a.mo > 0 && a.podr !== '' && a.dbeg !== '');

  const handleReset = () => {
    setViewMode('search');
    setPerson(defaultPerson);
    setAttachments(defaultAttachments);
    setResponse(null);
    setError(null);
    setMisAttachment(null);
    setMisCardData(null);
    setRawCardData(null);
    setInsCheckResponse(null);
    setInsCheckError(null);
    setSyncLoading(false);
    setSyncError(null);
    setSyncSuccess(false);
    setSearchKey((k) => k + 1);
    localStorage.removeItem(STORAGE_KEY_PERSON);
    localStorage.removeItem(STORAGE_KEY_ATTACHMENTS);
  };

  const handleBackToSearch = () => {
    setViewMode('search');
    setPerson(defaultPerson);
    setAttachments(defaultAttachments);
    setResponse(null);
    setError(null);
    setMisAttachment(null);
    setMisCardData(null);
    setRawCardData(null);
    setInsCheckResponse(null);
    setInsCheckError(null);
    setSyncLoading(false);
    setSyncError(null);
    setSyncSuccess(false);
    setSearchKey((k) => k + 1);
    localStorage.removeItem(STORAGE_KEY_PERSON);
    localStorage.removeItem(STORAGE_KEY_ATTACHMENTS);
  };

  return (
    <>
      {viewMode === 'search' && (
        <Paper sx={{ p: 3 }}>
          <PatientSearch
            key={searchKey}
            onPatientSelected={handlePatientSelected}
            onManualEntry={handleManualEntry}
          />
        </Paper>
      )}

      {(viewMode === 'card' || viewMode === 'form' || viewMode === 'attachments' || viewMode === 'result') && (
        <>
          <Stepper
            activeStep={viewMode === 'card' || viewMode === 'form' ? 0 : viewMode === 'attachments' ? 1 : 2}
            sx={{ mb: 3 }}
          >
            {steps.map((label) => (
              <Step key={label}><StepLabel>{label}</StepLabel></Step>
            ))}
          </Stepper>

          {viewMode === 'card' && (
            <Paper sx={{ p: 3 }}>
          <PatientCard
            person={person}
            rawCard={rawCardData}
            misAttachment={misAttachment}
            insCheckResponse={insCheckResponse}
            insCheckLoading={insCheckLoading}
            insCheckError={insCheckError}
            spmoMap={spmoMap}
            spsmoMap={spsmoMap}
            syncLoading={syncLoading}
            syncError={syncError}
            syncSuccess={syncSuccess}
            onCheckIns={handleCheckIns}
            onSyncWithTfoms={handleSyncWithTfoms}
            onChangeAttachment={handleChangeAttachment}
            onBackToSearch={handleBackToSearch}
            onGenerateScd={handleGenerateScd}
            onUploadAsc={handleUploadAsc}
          />
            </Paper>
          )}

          {viewMode === 'form' && (
            <>
              <Paper sx={{ p: 3 }}>
                <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                  <Typography variant="subtitle1" fontWeight="bold">
                    Данные пациента
                  </Typography>
                  <Button size="small" startIcon={<ArrowBackIcon />} onClick={handleReset}>
                    К поиску
                  </Button>
                </Box>
                <PersonForm person={person} onChange={setPerson} />
              </Paper>
              <Box display="flex" justifyContent="space-between" mt={2}>
                <Button onClick={handleReset} startIcon={<RestartAltIcon />}>Сбросить</Button>
                <Box display="flex" gap={1}>
                  <Button onClick={handleBackToCard} disabled={loading}>Назад</Button>
                  <Button variant="contained" onClick={handleNext} disabled={!canProceedForm()}>Далее</Button>
                </Box>
              </Box>
            </>
          )}

          {(viewMode === 'attachments' || viewMode === 'result') && (
            <>
              <Paper sx={{ p: 3 }}>
                {viewMode === 'attachments' && (
                  <>
                    <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                      <Typography variant="subtitle1" fontWeight="bold">
                        Прикрепления
                      </Typography>
                      <Button size="small" startIcon={<ArrowBackIcon />} onClick={handleReset}>
                        К поиску
                      </Button>
                    </Box>
                    <AttachmentList
                    attachments={attachments}
                    onChange={setAttachments}
                    defaultMo={Number(settings.defaultMo) || 893}
                    spmoMap={spmoMap}
                  />
                  </>
                )}
                {viewMode === 'result' && response && <ResultPanel response={response} spmoMap={spmoMap} />}

                {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
                {loading && (
                  <Box display="flex" justifyContent="center" mt={2}><CircularProgress /></Box>
                )}
              </Paper>

              <ConfirmDialog
                open={confirmOpen}
                person={person}
                attachments={attachments}
                spmoMap={spmoMap}
                onConfirm={handleConfirm}
                onClose={() => setConfirmOpen(false)}
              />
            </>
          )}
        </>
      )}

      {viewMode === 'attachments' && (
        <Box display="flex" justifyContent="space-between" mt={2}>
          <Box display="flex" gap={1}>
            <Button
              disabled={loading}
              onClick={handleReset}
              startIcon={<ArrowBackIcon />}
            >
              К поиску
            </Button>
            <Button
              disabled={loading}
              onClick={handleReset}
              startIcon={<RestartAltIcon />}
            >
              Сбросить
            </Button>
          </Box>
          <Box display="flex" gap={1}>
            <Button disabled={loading} onClick={handleBack}>Назад</Button>
            <Button
              variant="contained"
              color="success"
              onClick={handleSubmit}
              disabled={!canProceedAttachments() || loading}
            >
              {loading ? 'Отправка...' : 'Отправить'}
            </Button>
          </Box>
        </Box>
      )}

      {viewMode === 'result' && (
        <Box display="flex" justifyContent="flex-end" mt={2}>
          <Button variant="outlined" onClick={handleReset}>Новый запрос</Button>
        </Box>
      )}
      <Dialog open={ascDialogOpen} onClose={() => setAscDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Результат запроса SCD</DialogTitle>
        <DialogContent>
          {ascError && <Alert severity="error">{ascError}</Alert>}
          {ascData && (
            <Box>
              <Alert severity={ascData.ack === 0 ? 'success' : 'warning'} sx={{ mb: 2 }}>
                {ascData.ack === 0 ? 'Страховая принадлежность определена' : `Ошибка обработки (ack=${ascData.ack})`}
              </Alert>
              {ascData.algs?.length > 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  Алгоритмы: {ascData.algs.join(', ')}
                </Typography>
              )}
              {ascData.insurance && (
                <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
                  <Typography variant="subtitle2" fontWeight="bold" gutterBottom>Страховая принадлежность</Typography>
                  <Box display="grid" gridTemplateColumns="1fr 1fr" gap={0.5}>
                    <Typography variant="body2">СМО: {ascData.insurance.smo ?? '—'}</Typography>
                    <Typography variant="body2">Тип полиса: {ascData.insurance.vpolis ?? '—'}</Typography>
                    <Typography variant="body2">Номер: {ascData.insurance.npolis || '—'}</Typography>
                    <Typography variant="body2">Форма: {ascData.insurance.fpolis ?? '—'}</Typography>
                    <Typography variant="body2">Дата заявления: {ascData.insurance.dvisit || '—'}</Typography>
                    <Typography variant="body2">Полис с: {ascData.insurance.dbeg || '—'}</Typography>
                    <Typography variant="body2">Полис по: {ascData.insurance.dend || '—'}</Typography>
                    <Typography variant="body2">Причина: {ascData.insurance.reason ?? '—'}</Typography>
                    <Typography variant="body2">ID: {ascData.insurance.id ?? '—'}</Typography>
                    <Typography variant="body2">СНИЛС: {ascData.insurance.snils || '—'}</Typography>
                  </Box>
                </Paper>
              )}
              {ascData.attachment && (
                <Paper variant="outlined" sx={{ p: 1.5 }}>
                  <Typography variant="subtitle2" fontWeight="bold" gutterBottom>Прикрепление</Typography>
                  <Box display="grid" gridTemplateColumns="1fr 1fr" gap={0.5}>
                    <Typography variant="body2">МО: {ascData.attachment.mo ?? '—'}</Typography>
                    <Typography variant="body2">Подр.: {ascData.attachment.podr || '—'}</Typography>
                    <Typography variant="body2">Тип: {ascData.attachment.typeprk ?? '—'}</Typography>
                    <Typography variant="body2">Дата: {ascData.attachment.modt || '—'}</Typography>
                    <Typography variant="body2">Метод: {ascData.attachment.meth ?? '—'}</Typography>
                  </Box>
                </Paper>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAscDialogOpen(false)}>Закрыть</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
