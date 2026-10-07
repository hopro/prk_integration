import { useCallback, useEffect, useState } from 'react';
import {
  Box, Paper, Typography, Button, Alert, CircularProgress,
  Table, TableHead, TableBody, TableRow, TableCell, TextField, Divider,
  Dialog, DialogTitle, DialogContent, DialogActions, Stack, Chip,
  TablePagination,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import CloudSyncIcon from '@mui/icons-material/CloudSync';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import VisibilityIcon from '@mui/icons-material/Visibility';
import type { DictionaryItem, DictionaryLoadLog, DictionaryRow, DictionarySources } from '../types';
import {
  fetchDictionaryStatus, fetchDictionaryLog, fetchDictionarySources, loadDictionary,
  fetchRegions, fetchEntriesPage, uploadDictionaryXml,
} from '../api/dictionaries';

interface Props {
  defaultLpuId: string;
}

type Kind = DictionaryItem['kind'];

const KIND_LABELS: Record<Kind, string> = {
  regions: 'Участки ЛПУ',
  spmo: 'Медицинские организации',
  spsmo: 'Страховые компании',
  spdept: 'Подразделения МО (справочник ИАС-4)',
};

/**
 * Как загружается справочник:
 *   ecp   — только из ЕЦП, участки принадлежат конкретному ЛПУ;
 *   tfoms — из XML-выгрузки в каталоге ./tfoms.
 */
const KIND_SOURCE: Record<Kind, 'ecp' | 'tfoms'> = {
  regions: 'ecp',
  spmo: 'tfoms',
  spsmo: 'tfoms',
  spdept: 'tfoms',
};

/** Справочники из XML-выгрузок, включая подразделения ИАС-4. */
const TFOMS_KINDS: Kind[] = ['spdept', 'spmo', 'spsmo'];

export default function DictionariesPage({ defaultLpuId }: Props) {
  const [items, setItems] = useState<DictionaryItem[]>([]);
  const [sources, setSources] = useState<DictionarySources | null>(null);
  const [log, setLog] = useState<DictionaryLoadLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [lpuId, setLpuId] = useState(defaultLpuId || '13003795');

  const [viewKind, setViewKind] = useState<Kind | null>(null);
  const [rows, setRows] = useState<DictionaryRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [uploadTarget, setUploadTarget] = useState<Kind | null>(null);

  // Просмотр справочников постраничный: СПФМО — общероссийский список больше
  // чем на 150 тысяч строк, и выгрузка его целиком вешает вкладку на минуты.
  const PAGE = 200;
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [status, history, files] = await Promise.all([
        fetchDictionaryStatus(), fetchDictionaryLog(), fetchDictionarySources(),
      ]);
      setItems(status);
      setLog(history);
      setSources(files);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось получить состояние справочников');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { setLpuId(defaultLpuId || '13003795'); }, [defaultLpuId]);

  const readPage = useCallback(async (kind: Kind, opts: {
    scope?: string;
    search?: string;
    page?: number;
  } = {}) => {
    const pageNo = opts.page || 0;
    setRowsLoading(true);
    try {
      if (kind === 'regions') {
        const data = (await fetchRegions(opts.scope || lpuId)).items;
        setRows(data);
        setTotal(data.length);
        return;
      }
      const data = await fetchEntriesPage(kind, {
        scope: opts.scope || '',
        search: opts.search || '',
        limit: PAGE,
        offset: pageNo * PAGE,
      });
      setRows(data.items);
      setTotal(data.total);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось прочитать справочник');
    } finally {
      setRowsLoading(false);
    }
  }, [lpuId]);

  const openRows = useCallback(async (kind: Kind, scope: string) => {
    setViewKind(kind);
    setSearch('');
    setPage(0);
    await readPage(kind, { scope });
  }, [readPage]);

  const handleLoad = async (kind: Kind, scope: string) => {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const result = await loadDictionary(kind, scope);
      setNotice(
        `${KIND_LABELS[kind]}: записей ${result.rows.toLocaleString('ru-RU')} — ${result.source}`,
      );
      await reload();
      if (viewKind === kind) await openRows(kind, scope);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось обновить справочник');
      await reload();
    } finally {
      setBusy(null);
    }
  };

  const applySearch = async () => {
    if (!viewKind || viewKind === 'regions') return;
    setPage(0);
    await readPage(viewKind, { search });
  };

  const changePage = (_event: unknown, value: number) => {
    setPage(value);
    if (viewKind) readPage(viewKind, { search, page: value });
  };

  const handleUpload = async (file: File) => {
    if (!uploadTarget) return;
    setBusy(uploadTarget);
    setError(null);
    try {
      const result = await uploadDictionaryXml(uploadTarget, file);
      const uploaded = result.kind as Kind;
      setNotice(
        `${KIND_LABELS[uploaded]}: записей ${result.rows.toLocaleString('ru-RU')} — ${result.source}`,
      );
      setUploadTarget(null);
      await reload();
      await openRows(uploaded, '');
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось загрузить выгрузку');
      setUploadTarget(null);
    } finally {
      setBusy(null);
    }
  };

  const fileOf = (kind: Kind) => sources?.found.find((f) => f.kind === kind);
  const hasFile = (kind: Kind) => Boolean(fileOf(kind));

  /**
   * Карточка справочника. Кнопки загрузки ровно одна на вид источника:
   * участки ЛПУ — только из ЕЦП, справочники ТФОМС — только XML-выгрузка.
   */
  const renderCard = (kind: Kind, scope: string, rows: number, loadedAt: string | null) => {
    const source = KIND_SOURCE[kind];
    const isEcp = source === 'ecp';
    const file = fileOf(kind);
    return (
      <Paper key={`${kind}:${scope}`} variant="outlined" sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Box>
          <Typography variant="subtitle2">{KIND_LABELS[kind]}</Typography>
          <Typography variant="caption" color="text.secondary">
            {isEcp ? `Lpu_id ${scope}` : (file ? file.file : 'выгрузка не найдена')}
          </Typography>
        </Box>
        <Box>
          <Typography variant="h6" color={rows ? 'text.primary' : 'text.disabled'}>
            {rows ? rows.toLocaleString('ru-RU') : '—'}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {rows ? `записей · ${isEcp ? 'из ЕЦП' : 'из XML-выгрузки'}` : 'не загружен'}
            {loadedAt ? ` · ${new Date(loadedAt.replace(' ', 'T')).toLocaleString('ru-RU')}` : ''}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {isEcp ? (
            <Button
              size="small"
              variant="contained"
              startIcon={busy === kind ? <CircularProgress size={14} color="inherit" /> : <CloudSyncIcon />}
              disabled={busy !== null}
              onClick={() => handleLoad(kind, scope)}
            >
              Обновить из ЕЦП
            </Button>
          ) : (
            <>
              <Button
                size="small"
                variant="contained"
                startIcon={busy === kind ? <CircularProgress size={14} color="inherit" /> : <CloudSyncIcon />}
                disabled={busy !== null || !file}
                onClick={() => handleLoad(kind, scope)}
              >
                Обновить из XML
              </Button>
              <Button
                size="small"
                startIcon={<UploadFileIcon />}
                disabled={busy !== null}
                onClick={() => setUploadTarget(kind)}
              >
                Загрузить XML
              </Button>
            </>
          )}
          <Button
            size="small"
            startIcon={<VisibilityIcon />}
            disabled={rows === 0}
            onClick={() => openRows(kind, scope)}
          >
            Показать
          </Button>
        </Stack>
        {!isEcp && !file && (
          <Typography variant="caption" color="error">
            Файл не найден в каталоге {sources?.directory}
          </Typography>
        )}
      </Paper>
    );
  };

  const regionsItem = items.find((i) => i.kind === 'regions');
  const regionsLoaded = regionsItem?.scope === lpuId;

  return (
    <>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}

      <Paper sx={{ p: 2, mb: 2 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
          <Typography variant="subtitle1" fontWeight="bold">Справочники</Typography>
          <Button size="small" startIcon={<RefreshIcon />} onClick={reload} disabled={loading}>
            Обновить
          </Button>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Справочники хранятся локально и используются при работе с пациентами.
          Участки ЛПУ обновляются только из ЕЦП; справочники ТФОМС — только из XML-выгрузок.
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, mt: 2, flexWrap: 'wrap' }}>
          <TextField
            label="Lpu_id для участков ЕЦП"
            value={lpuId}
            onChange={(e) => setLpuId(e.target.value)}
            size="small"
            helperText="Обычно совпадает с ID МО для ЕЦП в настройках"
          />
        </Box>
      </Paper>

      {loading && !items.length ? (
        <Box display="flex" justifyContent="center" sx={{ py: 4 }}><CircularProgress /></Box>
      ) : (
        <>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Участки ЛПУ — только из ЕЦП</Typography>
          <Box display="grid" gridTemplateColumns={{ xs: '1fr', md: 'repeat(2, 1fr)' }} gap={2} sx={{ mb: 3 }}>
            {renderCard(
              'regions',
              lpuId,
              regionsLoaded ? regionsItem?.rows || 0 : 0,
              regionsLoaded ? regionsItem?.loadedAt || null : null,
            )}
          </Box>

          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Справочники ТФОМС — только XML-выгрузки
          </Typography>
          <Box display="grid" gridTemplateColumns={{ xs: '1fr', md: 'repeat(3, 1fr)' }} gap={2} sx={{ mb: 3 }}>
            {TFOMS_KINDS.map((kind) => {
              const entry = items.find((i) => i.kind === kind);
              return renderCard(kind, '', entry?.rows || 0, entry?.loadedAt || null);
            })}
          </Box>
        </>
      )}

      <Divider sx={{ my: 2 }} />
      <Typography variant="subtitle2" sx={{ mb: 1 }}>История загрузок</Typography>
      {!log.length ? (
        <Typography variant="body2" color="text.secondary">Загрузок пока не было.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Когда</TableCell>
              <TableCell>Справочник</TableCell>
              <TableCell>Область</TableCell>
              <TableCell align="right">Записей</TableCell>
              <TableCell>Результат</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {log.map((row, index) => (
              <TableRow key={index}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {row.created_at ? new Date(row.created_at.replace(' ', 'T')).toLocaleString('ru-RU') : ''}
                </TableCell>
                <TableCell>{KIND_LABELS[row.kind as Kind] || row.kind}</TableCell>
                <TableCell>{row.scope || '—'}</TableCell>
                <TableCell align="right">{row.rows_loaded}</TableCell>
                <TableCell>
                  {row.status === 'ok' ? (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip size="small" color="success" label="ок" />
                      {row.message && (
                        <Typography variant="caption" color="text.secondary">{row.message}</Typography>
                      )}
                    </Stack>
                  ) : (
                    <Chip size="small" color="error" label={row.message || 'ошибка'} />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={viewKind !== null} onClose={() => setViewKind(null)} maxWidth="md" fullWidth>
        <DialogTitle>
          {viewKind ? KIND_LABELS[viewKind] : ''}
          {viewKind === 'regions' ? ' · ' + lpuId : ''}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
            <TextField
              size="small"
              fullWidth
              placeholder="Поиск по коду или названию"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') applySearch(); }}
              disabled={viewKind === 'regions'}
            />
            <Button variant="outlined" onClick={applySearch} disabled={rowsLoading || viewKind === 'regions'}>
              Найти
            </Button>
          </Box>

          {rowsLoading ? (
            <Box display="flex" justifyContent="center" sx={{ py: 3 }}><CircularProgress /></Box>
          ) : !rows.length ? (
            <Typography color="text.secondary">Справочник пуст — обновите его из источника.</Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{viewKind === 'regions' ? 'Код участка' : 'Код'}</TableCell>
                  <TableCell>Наименование</TableCell>
                  {viewKind === 'regions' ? (
                    <>
                      <TableCell>Описание</TableCell>
                      <TableCell>Врач</TableCell>
                    </>
                  ) : (
                    <TableCell>Дополнительно</TableCell>
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row, index) => (
                  <TableRow key={index}>
                    <TableCell>{row.region_id || row.code}</TableCell>
                    <TableCell>{row.name}</TableCell>
                    {viewKind === 'regions' ? (
                      <>
                        <TableCell>{row.descr}</TableCell>
                        <TableCell>{row.med_personal_fio}</TableCell>
                      </>
                    ) : (
                      <TableCell>{row.extra}</TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {viewKind && viewKind !== 'regions' && total > PAGE && (
            <TablePagination
              component="div"
              count={total}
              page={page}
              onPageChange={changePage}
              rowsPerPage={PAGE}
              rowsPerPageOptions={[PAGE]}
              labelRowsPerPage="Записей на странице"
              labelDisplayedRows={({ from, to, count }) => `${from}\u2013${to} из ${count}`}
              sx={{ mt: 1 }}
            />
          )}
          {viewKind && viewKind !== 'regions' && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              Показано {rows.length} из {total.toLocaleString('ru-RU')} записей. Справочник
              большой, поэтому выдаётся постранично: ищите по названию или отберите вид
              подразделения.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setViewKind(null)}>Закрыть</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={uploadTarget !== null} onClose={() => setUploadTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Загрузка XML-выгрузки ТФОМС</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {uploadTarget ? KIND_LABELS[uploadTarget] : ''}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Поддерживаются zip с xml или сам xml в кодировке windows-1251.
            Участки ЛПУ из файла не загружаются — они обновляются только из ЕЦП.
          </Typography>
          <Box mt={2}>
            <Button
              variant="outlined"
              fullWidth
              startIcon={busy === uploadTarget ? <CircularProgress size={14} /> : <UploadFileIcon />}
              component="label"
              disabled={busy !== null}
            >
              Выбрать файл
              <input
                type="file"
                hidden
                accept=".zip,.xml,application/zip,text/xml"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (file) handleUpload(file);
                }}
              />
            </Button>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadTarget(null)}>Закрыть</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}