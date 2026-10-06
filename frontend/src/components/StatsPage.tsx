import { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, TextField, Button, Collapse, Card, CardContent, Grid, TablePagination,
  Alert, Chip, CircularProgress, IconButton, Stack,
} from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import FilterListIcon from '@mui/icons-material/FilterList';
import { fetchHistory, fetchStats } from '../api/prk';
import type { PrkHistoryItem, PrkStats } from '../types';

const TYPE_LABELS: Record<number, string> = { 1: 'АПП', 3: 'Доврачебная в ФАП' };
const METHOD_LABELS: Record<number, string> = { 1: 'Территориально-участковый', 2: 'По заявлению' };

function fmtDate(dateStr: string): string {
  if (!dateStr) return '';
  const [d, m, y] = dateStr.substring(0, 10).split('-');
  if (d && m && y) return `${d}.${m}.${y}`;
  return dateStr;
}

function fmtDateTime(dateStr: string): string {
  if (!dateStr) return '';
  const parts = dateStr.split(' ');
  if (parts.length >= 2) return `${fmtDate(parts[0])} ${parts[1].substring(0, 5)}`;
  return dateStr;
}

interface RowProps {
  item: PrkHistoryItem;
  spmoMap: Record<number, string>;
}

function HistoryRow({ item, spmoMap }: RowProps) {
  const [open, setOpen] = useState(false);

  const statusColor = item.success ? 'success' : 'error';
  const statusText = item.success ? 'Успешно' : (item.error_message ? 'Ошибка' : 'Отказ');
  // ИАС-4 и ЕЦП — разные этапы: запись может уйти в ИАС-4 и не отправиться в ЕЦП.
  const ecpText = item.misSave == null
    ? 'ЕЦП: не отправлялось'
    : (item.misSave.success ? 'ЕЦП: отправлено' : `ЕЦП: ${item.misSave.error || 'ошибка'}`);

  return (
    <>
      <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <TableCell sx={{ width: 40 }}>
          <IconButton size="small" onClick={() => setOpen(!open)}>
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell>{item.id}</TableCell>
        <TableCell>{fmtDateTime(item.created_at)}</TableCell>
        <TableCell>{item.fam} {item.im} {item.ot}</TableCell>
        <TableCell>{item.attachments.map((a) => TYPE_LABELS[a.typeprk] || a.typeprk).join(', ')}</TableCell>
        <TableCell>{item.attachments.map((a) => `${a.mo} ${spmoMap[a.mo] || ''}`).join(', ')}</TableCell>
        <TableCell>
          <Stack spacing={0.5} alignItems="flex-start">
            <Chip label={statusText} color={statusColor} size="small" variant="outlined" />
            <Chip
              label={item.misSave?.success ? 'ЕЦП' : 'ЕЦП не отправлено'}
              color={item.misSave == null ? 'default' : (item.misSave.success ? 'success' : 'warning')}
              size="small"
              variant="outlined"
            />
          </Stack>
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={7} sx={{ py: 0 }}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'grey.50' }}>
              <Typography variant="subtitle2" gutterBottom>Данные пациента</Typography>
              <Typography variant="body2">ФИО: {item.fam} {item.im} {item.ot}</Typography>
              <Typography variant="body2">Дата рождения: {fmtDate(item.dr)}</Typography>
              <Typography variant="body2">Номер полиса: {item.npolis}</Typography>

              <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>Прикрепления</Typography>
              {item.attachments.map((a, i) => (
                <Box key={i} sx={{ ml: 2, mb: 1 }}>
                  <Typography variant="body2" color="text.secondary">Прикрепление {i + 1}</Typography>
                  <Typography variant="body2">Тип: {TYPE_LABELS[a.typeprk] || a.typeprk}</Typography>
                  <Typography variant="body2">МО: {a.mo} — {spmoMap[a.mo] || ''}</Typography>
                  <Typography variant="body2">Участок: {a.podr}</Typography>
                  <Typography variant="body2">Дата начала: {fmtDate(a.dbeg)}</Typography>
                  <Typography variant="body2">Способ: {METHOD_LABELS[a.meth] || a.meth}</Typography>
                </Box>
              ))}

              {item.timeoper && (
                <Typography variant="body2" sx={{ mt: 1 }}>
                  Время обработки: {item.timeoper}
                </Typography>
              )}

              {item.errors && item.errors.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="subtitle2" color="error">Ошибки:</Typography>
                  {item.errors.map((err, i) => (
                    <Typography key={i} variant="body2" color="error">
                      [{err.errcode}] {err.errname}{err.comment ? ` — ${err.comment}` : ''}
                    </Typography>
                  ))}
                </Box>
              )}

              {item.error_message && (
                <Alert severity="error" sx={{ mt: 1 }}>
                  {item.error_message}
                </Alert>
              )}

              {item.misSave != null && (
                <Alert severity={item.misSave.success ? 'success' : 'error'} sx={{ mt: 1 }}>
                  Отправка в ЕЦП: {item.misSave.success ? 'успешно' : (item.misSave.error || 'ошибка')}
                </Alert>
              )}
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

interface Props {
  spmoMap: Record<number, string>;
}

export default function StatsPage({ spmoMap }: Props) {
  const [stats, setStats] = useState<PrkStats | null>(null);
  const [items, setItems] = useState<PrkHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage] = useState(20);
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterFam, setFilterFam] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [historyResp, statsResp] = await Promise.all([
        fetchHistory({
          page: page + 1,
          limit: rowsPerPage,
          date_from: filterDateFrom || undefined,
          date_to: filterDateTo || undefined,
          fam: filterFam || undefined,
        }),
        fetchStats(),
      ]);
      setItems(historyResp.items);
      setTotal(historyResp.total);
      setStats(statsResp);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, filterDateFrom, filterDateTo, filterFam]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleChangePage = (_: unknown, newPage: number) => {
    setPage(newPage);
  };

  const handleSearch = () => {
    setPage(0);
    loadData();
  };

  return (
    <>
      <Box display="flex" alignItems="center" mb={2} gap={1}>
        <Typography variant="h6">Статистика прикреплений</Typography>
        <IconButton onClick={() => setShowFilters(!showFilters)} title="Фильтры">
          <FilterListIcon color={showFilters ? 'primary' : 'inherit'} />
        </IconButton>
        <Box flexGrow={1} />
        <Button variant="outlined" size="small" onClick={loadData} disabled={loading}>
          {loading ? <CircularProgress size={20} /> : 'Обновить'}
        </Button>
      </Box>

      {stats && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={4}>
            <Card>
              <CardContent>
                <Typography variant="h4" align="center">{stats.total}</Typography>
                <Typography variant="body2" color="text.secondary" align="center">Всего отправлено</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={4}>
            <Card sx={{ bgcolor: '#e8f5e9' }}>
              <CardContent>
                <Typography variant="h4" align="center" color="success.main">{stats.success}</Typography>
                <Typography variant="body2" color="text.secondary" align="center">Успешно</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={4}>
            <Card sx={{ bgcolor: '#ffebee' }}>
              <CardContent>
                <Typography variant="h4" align="center" color="error.main">{stats.failed}</Typography>
                <Typography variant="body2" color="text.secondary" align="center">С ошибками</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6}>
            <Card sx={{ bgcolor: stats.ecpSuccess ? '#e8f5e9' : 'grey.100' }}>
              <CardContent>
                <Typography variant="h4" align="center" color={stats.ecpSuccess ? 'success.main' : 'text.disabled'}>
                  {stats.ecpSuccess}
                </Typography>
                <Typography variant="body2" color="text.secondary" align="center">
                  Отправлено в ЕЦП (из {stats.ecpAttempted})
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6}>
            <Card sx={{ bgcolor: stats.ecpFailed ? '#fff8e1' : 'grey.100' }}>
              <CardContent>
                <Typography variant="h4" align="center" color={stats.ecpFailed ? 'warning.main' : 'text.disabled'}>
                  {stats.ecpFailed}
                </Typography>
                <Typography variant="body2" color="text.secondary" align="center">
                  Не отправлено в ЕЦП
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      <Collapse in={showFilters}>
        <Paper sx={{ p: 2, mb: 2 }}>
          <Grid container spacing={2} alignItems="flex-end">
            <Grid item xs={3}>
              <TextField
                fullWidth
                label="Дата с"
                type="date"
                size="small"
                value={filterDateFrom}
                onChange={(e) => setFilterDateFrom(e.target.value)}
                InputLabelProps={{ shrink: true }}
              />
            </Grid>
            <Grid item xs={3}>
              <TextField
                fullWidth
                label="Дата по"
                type="date"
                size="small"
                value={filterDateTo}
                onChange={(e) => setFilterDateTo(e.target.value)}
                InputLabelProps={{ shrink: true }}
              />
            </Grid>
            <Grid item xs={3}>
              <TextField
                fullWidth
                label="ФИО (часть)"
                size="small"
                value={filterFam}
                onChange={(e) => setFilterFam(e.target.value)}
              />
            </Grid>
            <Grid item xs={2}>
              <Button variant="contained" onClick={handleSearch} fullWidth>Поиск</Button>
            </Grid>
          </Grid>
        </Paper>
      </Collapse>

      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 40 }} />
                <TableCell>ID</TableCell>
                <TableCell>Дата</TableCell>
                <TableCell>Пациент</TableCell>
                <TableCell>Тип</TableCell>
                <TableCell>МО</TableCell>
                <TableCell>Статус</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={7} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 4 }}>
                      Нет записей
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {items.map((item) => (
                <HistoryRow key={item.id} item={item} spmoMap={spmoMap} />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={handleChangePage}
          rowsPerPage={rowsPerPage}
          rowsPerPageOptions={[20]}
          labelRowsPerPage=""
        />
      </Paper>
    </>
  );
}
