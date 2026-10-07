import { useState, useEffect, useCallback } from 'react';
import {
  Container, Tabs, Tab, Box, Typography, IconButton, CircularProgress,
  Snackbar, Alert,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import LoadPrkPage from './components/LoadPrkPage';
import InsCheckPage from './components/InsCheckPage';
import StatsPage from './components/StatsPage';
import SettingsDialog from './components/SettingsDialog';
import DictionariesPage from './components/DictionariesPage';
import RegionLinksPage from './components/RegionLinksPage';
import { fetchDict } from './api/spmo';
import { fetchSettings, saveSettings, updateMisCredentials, updateMisConfig } from './api/settings';
import type { SettingsData } from './types';

const defaultSettings: SettingsData = {
  user: '', password: '', defaultMo: '0893', misLpuId: '13003795',
  misLogin: '', misPassword: '',
  iasUrl: '', iasCheckUrl: '', ecpUrl: '', tfomsEncoding: 'cp1251',
};

function extractError(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ');
  return e?.message || fallback;
}

export default function App() {
  const [tab, setTab] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<SettingsData>(defaultSettings);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [notice, setNotice] = useState<{ severity: 'error' | 'success' | 'warning'; message: string } | null>(null);
  const [spmoMap, setSpmoMap] = useState<Record<number, string>>({});
  const [spsmoMap, setSpsmoMap] = useState<Record<number, string>>({});

  useEffect(() => {
    fetchSettings(true)
      .then(setSettings)
      .catch((e) => setNotice({
        severity: 'error',
        message: extractError(e, 'Не удалось загрузить настройки. Проверьте доступность сервера.'),
      }))
      .finally(() => setSettingsLoaded(true));
  }, []);

  // Актуальное состояние учётных данных ЕЦП со шлюза — источник правды.
  const refreshMisStatus = useCallback(async () => {
    try {
      const fresh = await fetchSettings(true);
      setSettings((prev) => ({ ...prev, misStatus: fresh.misStatus }));
    } catch {
      // Статус — справочный, молча оставляем предыдущее значение.
    }
  }, []);

  // Возвращает текст ошибки, если сохранить не удалось. Диалог не закрывается при ошибке.
  const handleSaveSettings = useCallback(async (s: SettingsData): Promise<string | null> => {
    // Адрес ЕЦП живёт на шлюзе — шлём его туда до записи в локальную БД.
    const previousEcpUrl = settings.ecpUrl;
    const nextEcpUrl = (s.ecpUrl || '').trim().replace(/\/+$/, '');
    if (nextEcpUrl && nextEcpUrl !== previousEcpUrl) {
      try {
        const result = await updateMisConfig(nextEcpUrl);
        s = { ...s, ecpUrl: result?.data?.baseUrl || nextEcpUrl };
      } catch (e: any) {
        return extractError(e, 'Не удалось сохранить адрес ЕЦП');
      }
    }

    try {
      const saved = await saveSettings(s);
      setSettings((prev) => ({
        ...saved,
        user: saved.user || s.user,
        password: saved.password || s.password,
        misStatus: prev.misStatus,
      }));
    } catch (e: any) {
      return extractError(e, 'Не удалось сохранить настройки');
    }

    // Логин и пароль ЕЦП — либо оба, либо ни одного. Раньше проверка была
    // «логин ИЛИ пароль», и пустой логин молча затирал рабочие учётные данные.
    const misLogin = s.misLogin.trim();
    const misPassword = s.misPassword;
    if (misLogin || misPassword) {
      try {
        await updateMisCredentials(misLogin, misPassword);
      } catch (e: any) {
        return extractError(e, 'Не удалось сохранить учётные данные ЕЦП');
      }
    }

    await refreshMisStatus();
    setNotice({ severity: 'success', message: 'Настройки сохранены' });
    return null;
  }, [refreshMisStatus, settings.ecpUrl]);

  useEffect(() => {
    fetchDict()
      .then((dict) => {
        const spmo: Record<number, string> = {};
        for (const item of dict.spmo) {
          spmo[item.code] = item.name;
        }
        setSpmoMap(spmo);

        const spsmo: Record<number, string> = {};
        for (const item of dict.spsmo) {
          spsmo[item.code] = item.name;
        }
        setSpsmoMap(spsmo);
      })
      .catch(() => {});
  }, []);

  if (!settingsLoaded) {
    return (
      <Container maxWidth="md" sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Container>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box display="flex" alignItems="center" mb={1}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          ИАС-4: Работа с прикреплениями
        </Typography>
        <IconButton onClick={() => setSettingsOpen(true)} title="Настройки">
          <SettingsIcon />
        </IconButton>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Прикрепление ЗЛ" />
        <Tab label="Проверка полиса" />
        <Tab label="Справочники" />
        <Tab label="Сопоставление участков" />
        <Tab label="Статистика" />
      </Tabs>

      {tab === 0 && <LoadPrkPage settings={settings} spmoMap={spmoMap} spsmoMap={spsmoMap} />}
      {tab === 1 && <InsCheckPage settings={settings} spmoMap={spmoMap} spsmoMap={spsmoMap} />}
      {tab === 2 && <DictionariesPage defaultLpuId={settings.misLpuId} />}
      {tab === 3 && <RegionLinksPage lpuId={settings.misLpuId} />}
      {tab === 4 && <StatsPage spmoMap={spmoMap} />}

      <SettingsDialog
        open={settingsOpen}
        settings={settings}
        onSave={handleSaveSettings}
        onClose={() => setSettingsOpen(false)}
      />

      <Snackbar
        open={notice !== null}
        autoHideDuration={notice?.severity === 'error' ? 12000 : 4000}
        onClose={() => setNotice(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity={notice?.severity || 'info'}
          onClose={() => setNotice(null)}
          variant="filled"
        >
          {notice?.message}
        </Alert>
      </Snackbar>
    </Container>
  );
}