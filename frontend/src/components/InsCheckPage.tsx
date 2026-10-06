import { useState, useCallback } from 'react';
import {
  Button, Box, CircularProgress, Alert, Paper, Typography,
} from '@mui/material';
import InsCheckForm from './InsCheckForm';
import InsCheckResult from './InsCheckResult';
import { sendInsCheck } from '../api/check';
import { fetchSpDept } from '../api/spmo';
import type { InsCheckRequest, InsCheckResponse, SettingsData } from '../types';

interface Props {
  settings: SettingsData;
  spmoMap: Record<number, string>;
  spsmoMap: Record<number, string>;
}

const generateNrec = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 32);
  }
  const arr = new Uint8Array(16);
  for (let i = 0; i < 16; i++) arr[i] = Math.floor(Math.random() * 256);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
};

function getCurrentMonthDates() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const date1 = `${year}-${month}-01`;
  const date2 = `${year}-${month}-${day}`;
  return { date1, date2 };
}

function makeDefaultCheck(settings: SettingsData): InsCheckRequest {
  const { date1, date2 } = getCurrentMonthDates();
  return {
    login: { user: '', password: '' },
    nrec: generateNrec(),
    date1,
    date2,
    type_org: 1,
    code_org: Number(settings.defaultMo) || 0,
    fam: '',
    im: '',
    ot: '',
    w: null,
    dr: null,
    vpolis: 3,
    npolis: '',
    doctype: null,
    docser: '',
    docnum: '',
    snils: '',
    mr: '',
  };
}

export default function InsCheckPage({ settings, spmoMap, spsmoMap }: Props) {
  const [data, setData] = useState<InsCheckRequest>(() => makeDefaultCheck(settings));
  const [response, setResponse] = useState<InsCheckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spdeptMap, setSpdeptMap] = useState<Record<string, string>>({});

  const loadSpdept = useCallback(async () => {
    try {
      const list = await fetchSpDept();
      const map: Record<string, string> = {};
      for (const item of list) {
        map[item.code] = item.name;
      }
      setSpdeptMap(map);
    } catch {
      setSpdeptMap({});
    }
  }, []);

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setResponse(null);
    setSpdeptMap({});
    try {
      const result = await sendInsCheck({
        ...data,
        login: { user: settings.user, password: settings.password },
      });
      setResponse(result);
      if (result.attachment?.mo) {
        loadSpdept();
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : e?.message || 'Ошибка отправки запроса';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const canSubmit = data.npolis.trim() !== '';

  const handleReset = () => {
    setData(makeDefaultCheck(settings));
    setResponse(null);
    setError(null);
    setSpdeptMap({});
  };

  return (
    <>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>Параметры поиска</Typography>
        <InsCheckForm data={data} onChange={setData} />

        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
        {loading && (
          <Box display="flex" justifyContent="center" mt={2}><CircularProgress /></Box>
        )}

        <Box display="flex" justifyContent="flex-end" mt={2} gap={1}>
          <Button
            variant="outlined"
            onClick={handleReset}
            disabled={loading}
          >
            Сбросить
          </Button>
          <Button
            variant="contained"
            color="success"
            onClick={handleSubmit}
            disabled={!canSubmit || loading}
          >
            {loading ? 'Поиск...' : 'Найти'}
          </Button>
        </Box>
      </Paper>

      {response && (
        <Paper sx={{ p: 3, mt: 2 }}>
          <InsCheckResult response={response} spmoMap={spmoMap} spsmoMap={spsmoMap} spdeptMap={spdeptMap} />
        </Paper>
      )}
    </>
  );
}
