import { useRef } from 'react';
import { Box, Paper, Typography, Alert, Divider, CircularProgress, Button } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import SearchIcon from '@mui/icons-material/Search';
import DownloadIcon from '@mui/icons-material/Download';
import UploadIcon from '@mui/icons-material/Upload';
import type { PersonData, InsCheckResponse } from '../types';

interface Props {
  person: PersonData;
  rawCard: Record<string, any> | null;
  misAttachment: {
    lpuNick: string;
    begDate: string;
    regionName: string;
    regionDescr: string;
    medPersonalFio: string;
    lpuRegionId: string;
  } | null;
  insCheckResponse: InsCheckResponse | null;
  insCheckLoading: boolean;
  insCheckError: string | null;
  spmoMap: Record<number, string>;
  spsmoMap: Record<number, string>;
  syncLoading: boolean;
  syncError: string | null;
  syncSuccess: boolean;
  onCheckIns: () => void;
  onSyncWithTfoms: () => void;
  onChangeAttachment: () => void;
  onBackToSearch: () => void;
  onGenerateScd?: () => void;
  onUploadAsc?: (file: File) => void;
}

const POLIS_LABELS: Record<number, string> = {
  1: 'Старого образца',
  2: 'Временное свидетельство',
  3: 'Единого образца',
};

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const parts = dateStr.split('-');
  if (parts.length === 3) return `${parts[2]}.${parts[1]}.${parts[0]}`;
  return dateStr;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', gap: 0.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ color: 'text.secondary', minWidth: 110, flexShrink: 0 }}>{label}:</Typography>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>{value || '—'}</Typography>
    </Box>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box mb={1.5}>
      <Typography variant="subtitle2" fontWeight="bold" gutterBottom sx={{ color: 'primary.main', mb: 0.5 }}>{title}</Typography>
      {children}
    </Box>
  );
}

function formatDateFromNow(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const parts = dateStr.split('-');
  if (parts.length !== 3) return dateStr;
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
  return `${dateStr} (${diffDays} дн. назад)`;
}

export default function PatientCard({
  person, rawCard, misAttachment,
  insCheckResponse, insCheckLoading, insCheckError,
  spmoMap, spsmoMap,
  syncLoading, syncError, syncSuccess,
  onCheckIns, onSyncWithTfoms, onChangeAttachment, onBackToSearch, onGenerateScd, onUploadAsc,
}: Props) {
  const ascInputRef = useRef<HTMLInputElement>(null);
  const fio = [person.fam, person.im, person.ot].filter(Boolean).join(' ');
  const sexLabel = person.pol === 'М' ? 'Мужской' : person.pol === 'Ж' ? 'Женский' : '—';

  return (
    <>
      <Paper variant="outlined" sx={{ p: 2 }}>
        {/* Header */}
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="subtitle1" fontWeight="bold">Карточка пациента</Typography>
            <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
            <Typography variant="body2" color="text.secondary">{fio}</Typography>
          </Box>
          <Button size="small" startIcon={<ArrowBackIcon />} onClick={onBackToSearch}>
            К поиску
          </Button>
        </Box>

        <Divider sx={{ mb: 1.5 }} />

        <Section title="Личные данные">
          <Box display="grid" gridTemplateColumns="1fr 1fr 1fr" gap={1}>
            <Row label="Дата рождения" value={formatDate(person.dr)} />
            <Row label="Пол" value={sexLabel} />
            <Row label="СНИЛС" value={rawCard?.Person_Snils || ''} />
          </Box>
          <Row label="Телефон" value={rawCard?.Person_Phone || ''} />
          <Row label="Адрес" value={rawCard?.UAddress_AddressText || ''} />
        </Section>

        <Box display="grid" gridTemplateColumns="1fr 1fr" gap={2}>
          <Section title="Полис">
            <Row label="Тип" value={POLIS_LABELS[person.vpolis] || '—'} />
            <Row label="Номер" value={person.npolis || ''} />
            <Row label="Серия" value={rawCard?.Polis_Ser || ''} />
          </Section>
          {misAttachment && (
            <Section title="Текущее прикрепление ЕЦП">
              <Row label="МО" value={misAttachment.lpuNick} />
              <Row label="Участок" value={misAttachment.regionName} />
              <Row label="Описание" value={misAttachment.regionDescr} />
              <Row label="Врач" value={misAttachment.medPersonalFio} />
              <Row label="Дата" value={misAttachment.begDate} />
            </Section>
          )}
        </Box>
      </Paper>

      <Box display="flex" gap={1} mt={1.5}>
        <Button
          variant="contained"
          size="small"
          startIcon={insCheckLoading ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
          onClick={onCheckIns}
          disabled={insCheckLoading}
          sx={{ flex: 1 }}
        >
          {insCheckLoading ? 'Проверка...' : 'Проверить в ИАС'}
        </Button>
        <Button
          variant="outlined"
          size="small"
          startIcon={<EditIcon />}
          onClick={onChangeAttachment}
          sx={{ flex: 1 }}
        >
          Изменить прикрепление
        </Button>
      </Box>

      {onGenerateScd && (
        <Box mt={1.5} display="flex" gap={1}>
          <Button
            variant="outlined"
            size="small"
            startIcon={<DownloadIcon />}
            onClick={onGenerateScd}
            sx={{ flex: 1 }}
          >
            Сформировать SCD-запрос
          </Button>
          <Button
            variant="outlined"
            size="small"
            startIcon={<UploadIcon />}
            onClick={() => ascInputRef.current?.click()}
            sx={{ flex: 1 }}
          >
            Загрузить ответ ASC
          </Button>
          <input
            ref={ascInputRef}
            type="file"
            accept=".asc,.zip"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUploadAsc?.(f);
              e.target.value = '';
            }}
          />
        </Box>
      )}

      {insCheckError && (
        <Alert severity="error" sx={{ mt: 1.5, py: 0 }}>{insCheckError}</Alert>
      )}

      {insCheckResponse && (
        <Paper variant="outlined" sx={{ mt: 1.5, p: 1.5 }}>
          <Box display="flex" alignItems="center" gap={1} mb={1}>
            <Typography variant="subtitle2" fontWeight="bold" sx={{ color: insCheckResponse.ack === 0 ? 'success.main' : 'warning.main' }}>
              Результат ИАС
            </Typography>
            <Divider orientation="vertical" flexItem />
            <Alert severity={insCheckResponse.ack === 0 ? 'success' : 'warning'} sx={{ py: 0, flex: 1 }}>
              {insCheckResponse.ack === 0 ? 'Страховая принадлежность определена' : `ack=${insCheckResponse.ack}`}
            </Alert>
          </Box>

          {insCheckResponse.error_message ? (
            <Alert severity="error" sx={{ py: 0 }}>{insCheckResponse.error_message}</Alert>
          ) : (
            <Box display="grid" gridTemplateColumns="1fr 1fr" gap={1}>
              <Box>
                {insCheckResponse.insurance && (
                  <>
                    <Row label="СМО" value={`${insCheckResponse.insurance.smo ?? '—'}${insCheckResponse.insurance.smo && spsmoMap[insCheckResponse.insurance.smo] ? ` (${spsmoMap[insCheckResponse.insurance.smo]})` : ''}`} />
                    <Row label="Полис с" value={formatDate(insCheckResponse.insurance.dbeg)} />
                    <Row label="Полис по" value={formatDate(insCheckResponse.insurance.dend)} />
                  </>
                )}
              </Box>
              <Box>
                {insCheckResponse.attachment && (
                  <>
                    <Row label="МО" value={`${insCheckResponse.attachment.mo ?? '—'}${insCheckResponse.attachment.mo && spmoMap[insCheckResponse.attachment.mo] ? ` (${spmoMap[insCheckResponse.attachment.mo]})` : ''}`} />
                    <Row label="Подр." value={insCheckResponse.attachment.podr || '—'} />
                    <Row label="Прикреплён" value={formatDate(insCheckResponse.attachment.modt)} />
                  </>
                )}
              </Box>
            </Box>
          )}

          {insCheckResponse.ack !== 0 && insCheckResponse.errors?.length > 0 && (
            <Typography variant="body2" color="warning.main" sx={{ fontSize: '0.75rem', mt: 1 }}>
              {insCheckResponse.errors.map((e) => `[${e.errcode}] ${e.errtext}`).join('; ')}
            </Typography>
          )}

          {insCheckResponse.algs?.length > 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.75rem', mt: 0.5 }}>
              Алгоритмы: {insCheckResponse.algs.join(', ')}
            </Typography>
          )}
        </Paper>
      )}

      {insCheckResponse && insCheckResponse.ack === 0 && (
        <Box display="flex" gap={1} mt={1.5}>
          <Button
            variant="outlined"
            size="small"
            startIcon={syncLoading ? <CircularProgress size={16} /> : undefined}
            onClick={onSyncWithTfoms}
            disabled={syncLoading || syncSuccess}
          >
            {syncLoading ? 'Синхронизация...' : syncSuccess ? 'Синхронизировано' : 'Синхронизировать с ЕЦП'}
          </Button>
        </Box>
      )}

      {syncSuccess && (
        <Alert severity="success" sx={{ mt: 1, py: 0 }}>Данные успешно синхронизированы с ЕЦП</Alert>
      )}

      {syncError && (
        <Alert severity="error" sx={{ mt: 1, py: 0 }}>{syncError}</Alert>
      )}
    </>
  );
}
