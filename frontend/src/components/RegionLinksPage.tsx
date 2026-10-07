import { useCallback, useEffect, useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import SaveIcon from '@mui/icons-material/Save';
import SearchIcon from '@mui/icons-material/Search';
import TuneIcon from '@mui/icons-material/Tune';

import {
  applyRegionLinkSuggestions,
  fetchRegionLinkSuggestions,
  fetchRegionLinks,
  forgetRegionLink,
  saveRegionLink,
} from '../api/dictionaries';
import type { FreeRegion, RegionLinkRow, RegionLinkSuggestion } from '../types';

type Filter = 'all' | 'unresolved' | 'manual' | 'free';

/** Цвет метки способа сопоставления: важно видеть глазом, где решение принято вручную. */
function HowChip({ row }: { row: RegionLinkRow }) {
  if (row.how === 'вручную') return <Chip size="small" color="primary" label="вручную" />;
  if (row.how === 'автоматически') return <Chip size="small" variant="outlined" label="автоматически" />;
  if (row.how === 'отвязано вручную') {
    return <Chip size="small" variant="outlined" color="warning" label="отвязано" />;
  }
  if (row.how === 'участок не найден в ЕЦП') {
    return <Chip size="small" color="error" label="участок исчез из ЕЦП" />;
  }
  return <Chip size="small" variant="outlined" color="default" label="не привязано" />;
}

/** Строка таблицы: код подразделения ИАС-4 слева, участок ЕЦП справа. */
function LinkRow({
  row,
  regions,
  busy,
  onPick,
  onUnlink,
  onForget,
}: {
  row: RegionLinkRow;
  regions: FreeRegion[];
  busy: boolean;
  onPick: (podr: string, regionId: string) => void;
  onUnlink: (podr: string) => void;
  onForget: (podr: string) => void;
}) {
  // В выпадающем списке показываем все участки, а не только свободные:
  // занятый участок может понадобиться переназначить этому подразделению.
  const options = regions;
  const value = row.regionId
    ? (options.find((r) => r.regionId === row.regionId) || {
        regionId: row.regionId,
        name: row.regionName || row.regionId,
        descr: '',
        linkedBy: '',
      })
    : null;

  return (
    <TableRow hover>
      <TableCell sx={{ width: 110, fontFamily: 'monospace' }}>{row.podr}</TableCell>
      <TableCell>
        {row.name || '—'}
        {/* По умолчанию закрытых подразделений в таблице нет: ИАС-4 их не
            примет. Метка нужна, когда их открыли галочкой. */}
        {!row.actual && (
          <Typography variant="caption" color="warning.main" sx={{ display: 'block' }}>
            закрыто, ИАС-4 не примет{row.validUntil ? ` (до ${row.validUntil})` : ''}
          </Typography>
        )}
        {row.canAttach === false && (
          <Typography variant="caption" color="warning.main" sx={{ display: 'block' }}>
            прикрепление запрещено в справочнике
          </Typography>
        )}
      </TableCell>
      <TableCell>
        {/* Подразделение или ФАП — приходят из разных выгрузок ИАС-4. */}
        <Chip
          size="small"
          variant={row.origin === 'ФАП' ? 'outlined' : 'filled'}
          label={row.origin || '—'}
        />
      </TableCell>
      <TableCell sx={{ width: 340 }}>
        <Autocomplete
          size="small"
          options={options}
          value={value}
          loading={busy}
          disabled={busy}
          isOptionEqualToValue={(a, b) => a.regionId === b.regionId}
          // Идентификатор участка в интерфейсе не показываем: он не несёт
          // смысла для человека, а нужен только при отправке в ЕЦП.
          getOptionLabel={(o) => (o.descr ? `${o.name} — ${o.descr}` : o.name)}
          renderOption={(props, option) => (
            <li {...props} key={option.regionId}>
              <Box>
                <Typography variant="body2">{option.name}</Typography>
                {/* Описание участка из ЕЦП: по нему видно, что это за
                    подразделение, когда имя само по себе является кодом. */}
                {option.descr && option.descr !== option.name && (
                  <Typography variant="caption" color="text.secondary">
                    {option.descr}
                  </Typography>
                )}
                {option.linkedBy && (
                  <Typography variant="caption" color="text.secondary">
                    подходит для кода {option.linkedBy}
                  </Typography>
                )}
              </Box>
            </li>
          )}
          renderInput={(params) => (
            <TextField {...params} placeholder="участок ЕЦП: имя и описание" />
          )}
          onChange={(_event, option) => onPick(row.podr, option?.regionId || '')}
        />
      </TableCell>
      <TableCell sx={{ width: 190 }}>
        <HowChip row={row} />
      </TableCell>
      <TableCell sx={{ width: 90 }}>
        <Stack direction="row" spacing={0}>
          {row.source === 'unlinked' && (
            <Tooltip title="Вернуть в автоматический подбор">
              <IconButton size="small" disabled={busy} onClick={() => onForget(row.podr)}>
                <RestartAltIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          {row.regionId && (
            <Tooltip title="Отвязать и запретить автоподбор">
              <IconButton size="small" disabled={busy} onClick={() => onUnlink(row.podr)}>
                <LinkOffIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Stack>
      </TableCell>
    </TableRow>
  );
}

export default function RegionLinksPage({ lpuId }: { lpuId: string }) {
  const [matrix, setMatrix] = useState<{
    rows: RegionLinkRow[];
    freeRegions: FreeRegion[];
    summary: Record<string, number>;
    hint?: string;
    /** Код медицинской организации, подразделения которой показаны. */
    mo?: string;
    regionsLoaded?: boolean;
    iasLoaded?: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  // По умолчанию показываем только то, к чему ИАС-4 примет прикрепление.
  const [includeUnavailable, setIncludeUnavailable] = useState(false);
  const [busy, setBusy] = useState<string>('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [suggestions, setSuggestions] = useState<RegionLinkSuggestion[] | null>(null);
  const [notice, setNotice] = useState<string>('');
  const [error, setError] = useState<string>('');

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setMatrix(await fetchRegionLinks(lpuId, includeUnavailable));
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Не удалось загрузить сопоставление');
    } finally {
      setLoading(false);
    }
  }, [lpuId, includeUnavailable]);

  useEffect(() => {
    reload();
  }, [reload]);

  const rows = matrix?.rows || [];
  const freeRegions = matrix?.freeRegions || [];

  // Свободные участки показываем в общем списке: привязать можно и к занятому.
  const allRegions: FreeRegion[] = useMemo(
    () => [
      ...freeRegions,
      ...rows
        .filter((r) => r.regionId)
        .map((r) => ({
          regionId: r.regionId,
          name: r.regionName,
          descr: r.regionDescr || '',
          linkedBy: '',
        })),
    ],
    [freeRegions, rows],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (needle && !(row.podr.includes(needle) || (row.name || '').toLowerCase().includes(needle)
        || (row.regionName || '').toLowerCase().includes(needle))) {
        return false;
      }
      if (filter === 'unresolved') return !row.linked && !row.source;
      if (filter === 'manual') return row.source === 'manual' || row.source === 'auto';
      return true;
    });
  }, [rows, search, filter]);

  const act = async (podr: string, fn: () => Promise<void>) => {
    setBusy(podr);
    setError('');
    try {
      await fn();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Не удалось сохранить');
    } finally {
      setBusy('');
    }
  };

  const pick = (podr: string, regionId: string) =>
    act(podr, async () => {
      await saveRegionLink(podr, regionId, lpuId);
      await reload();
    });

  const unlink = (podr: string) =>
    act(podr, async () => {
      await saveRegionLink(podr, '', lpuId);
      await reload();
    });

  const forget = (podr: string) =>
    act(podr, async () => {
      await forgetRegionLink(podr, lpuId);
      await reload();
    });

  const runSuggest = async () => {
    setBusy('suggest');
    setError('');
    try {
      const result = await fetchRegionLinkSuggestions(lpuId);
      setSuggestions(result.items);
      setNotice(
        result.items.length
          ? `Автоматический подбор нашёл ${result.items.length} соответствий. Проверьте и примените.`
          : 'Автоматический подбор ничего не нашёл: у этих кодов нет привязки, а названия участков ЕЦП с кодами не совпадают. Привяжите вручную.',
      );
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Не удалось получить предложения');
    } finally {
      setBusy('');
    }
  };

  const applySuggestions = async () => {
    if (!suggestions?.length) return;
    setBusy('apply');
    setError('');
    try {
      const result = await applyRegionLinkSuggestions(suggestions, lpuId);
      setSuggestions(null);
      setNotice(
        `Применено ${result.applied} привязок.` +
          (result.rejected ? ` Отклонено ${result.rejected}: участок не найден в ЕЦП.` : ''),
      );
      await reload();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Не удалось применить');
    } finally {
      setBusy('');
    }
  };

  const s = matrix?.summary || {};
  const counts: Array<[Filter, string, number]> = [
    ['all', 'все', s.ias || 0],
    ['unresolved', 'не привязано', s.unresolved || 0],
    ['manual', 'привязано', (s.linked || 0)],
    ['free', 'свободные участки', s.regionsFree || 0],
  ];

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Сопоставление участков
      </Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Слева коды подразделения из справочника ИАС-4 (<code>SPDEPT.xml</code>) для МО{' '}
        {matrix?.mo || 'из настроек'}, справа — участки ЕЦП: <code>LpuRegion_Name</code> и{' '}
        <code>LpuRegion_Descr</code>. Код подразделения уходит в поле <code>podr</code>, а
        участок ЕЦП нужен, чтобы сохранить карту пациента. Нумерация у них разная, поэтому
        каждому подразделению нужно указать свой участок. Здесь это делается один раз и
        действует постоянно.
      </Typography>

      {matrix?.hint && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {matrix.hint}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      {matrix && s.ias > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap alignItems="center">
            <Box>
              <Typography variant="caption" color="text.secondary">
                Подразделений ИАС-4
              </Typography>
              <Typography variant="h6">{s.ias}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Привязано
              </Typography>
              <Typography variant="h6" color="success.main">
                {s.linked}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Не привязано
              </Typography>
              <Typography variant="h6" color={s.unresolved ? 'warning.main' : 'text.primary'}>
                {s.unresolved}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Из них ФАПов
              </Typography>
              <Typography variant="h6">{s.faps ?? 0}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Участков ЕЦП занято
              </Typography>
              <Typography variant="h6">
                {s.regionsUsed}
                <Typography component="span" variant="caption" color="text.secondary">
                  {' '}
                  из {s.regions}, свободно {s.regionsFree}
                </Typography>
              </Typography>
            </Box>
            <Box sx={{ flexGrow: 1 }} />
            <Button
              startIcon={busy === 'suggest' ? <CircularProgress size={16} /> : <TuneIcon />}
              onClick={runSuggest}
              disabled={busy !== ''}
            >
              Подобрать автоматически
            </Button>
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={includeUnavailable}
                  onChange={(e) => setIncludeUnavailable(e.target.checked)}
                  disabled={busy !== ''}
                />
              }
              label={
                <Typography variant="caption">
                  показать недоступные
                  {s.hiddenUnavailable ? ` (${s.hiddenUnavailable})` : ''}
                </Typography>
              }
            />
          </Stack>

          {suggestions && suggestions.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Предложения автоподбора ({suggestions.length})
              </Typography>
              <TableContainer sx={{ maxHeight: 260, mb: 1, border: '1px solid #ddd', borderRadius: 1 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Код ИАС-4</TableCell>
                      <TableCell>Название</TableCell>
                      <TableCell>Участок ЕЦП</TableCell>
                      <TableCell>Способ</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {suggestions.map((item) => (
                      <TableRow key={item.podr}>
                        <TableCell sx={{ fontFamily: 'monospace' }}>{item.podr}</TableCell>
                        <TableCell>{item.name}</TableCell>
                        <TableCell>
                          {item.region_id} · {item.region_name}
                        </TableCell>
                        <TableCell>{item.how}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              <Stack direction="row" spacing={1}>
                <Button
                  variant="contained"
                  startIcon={busy === 'apply' ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                  onClick={applySuggestions}
                  disabled={busy !== ''}
                >
                  Применить
                </Button>
                <Button onClick={() => setSuggestions(null)} disabled={busy !== ''}>
                  Отмена
                </Button>
              </Stack>
            </Box>
          )}
        </Paper>
      )}

      {loading ? (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      ) : (
        <>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              size="small"
              placeholder="Поиск по коду или названию"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{ startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1 }} /> }}
              sx={{ minWidth: 280 }}
            />
            {counts.map(([key, label, count]) => (
              <Chip
                key={key}
                label={`${label}: ${count}`}
                color={filter === key ? 'primary' : 'default'}
                variant={filter === key ? 'filled' : 'outlined'}
                onClick={() => setFilter(key)}
              />
            ))}
          </Stack>

          {filter === 'free' ? (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Участок ЕЦП</TableCell>
                    <TableCell sx={{ width: 240 }}>Описание (LpuRegion_Descr)</TableCell>
                    <TableCell sx={{ width: 200 }}>Подходит для кода</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {freeRegions.map((region) => (
                    <TableRow key={region.regionId} hover>
                      <TableCell sx={{ fontFamily: 'monospace' }}>{region.name}</TableCell>
                      <TableCell>{region.descr}</TableCell>
                      <TableCell>
                        {region.linkedBy ? (
                          <Chip size="small" variant="outlined" label={region.linkedBy} />
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            нет подходящего кода
                          </Typography>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!freeRegions.length && (
                    <TableRow>
                      <TableCell colSpan={3}>
                        <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                          Все участки ЕЦП заняты.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 100 }}>Код ИАС-4</TableCell>
                    <TableCell>Название подразделения</TableCell>
                    <TableCell sx={{ width: 110 }}>Источник</TableCell>
                    <TableCell>Участок ЕЦП</TableCell>
                    <TableCell sx={{ width: 190 }}>Способ</TableCell>
                    <TableCell sx={{ width: 90 }} />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visible.map((row) => (
                    <LinkRow
                      key={row.podr}
                      row={row}
                      regions={allRegions}
                      busy={busy === row.podr}
                      onPick={pick}
                      onUnlink={unlink}
                      onForget={forget}
                    />
                  ))}
                  {!visible.length && (
                    <TableRow>
                      <TableCell colSpan={6}>
                        <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
                          {rows.length
                            ? 'Ничего не найдено'
                            : 'Справочник подразделений ИАС-4 не загружен — загрузите SPDEPT.xml на вкладке «Справочники».'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {rows.length > 0 && filter !== 'free' && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              Показано {visible.length} из {rows.length}. Отвязка оставляет пометку: автоподбор
              больше не предложит этот код. Кнопка «Вернуть в автоматический подбор» снимает пометку.
            </Typography>
          )}
        </>
      )}
    </Box>
  );
}