import { useState, useEffect } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Box from '@mui/material/Box';
import type { SettingsData } from '../types';

interface Props {
  open: boolean;
  settings: SettingsData;
  onSave: (s: SettingsData) => Promise<string | null>;
  onClose: () => void;
}

export default function SettingsDialog({ open, settings, onSave, onClose }: Props) {
  const [user, setUser] = useState(settings.user);
  const [password, setPassword] = useState(settings.password);
  const [defaultMo, setDefaultMo] = useState(settings.defaultMo);
  const [misLpuId, setMisLpuId] = useState(settings.misLpuId);
  const [misLogin, setMisLogin] = useState(settings.misLogin);
  const [misPassword, setMisPassword] = useState(settings.misPassword);
  const [iasUrl, setIasUrl] = useState(settings.iasUrl);
  const [iasCheckUrl, setIasCheckUrl] = useState(settings.iasCheckUrl);
  const [ecpUrl, setEcpUrl] = useState(settings.ecpUrl);
  const [tfomsEncoding, setTfomsEncoding] = useState(settings.tfomsEncoding || 'cp1251');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Раньше поля инициализировались один раз при монтировании и больше не
  // синхронизировались: диалог мог показывать значения, которых уже нет в БД,
  // а «Отмена» не откатывала правки.
  useEffect(() => {
    if (!open) return;
    setUser(settings.user);
    setPassword(settings.password);
    setDefaultMo(settings.defaultMo);
    setMisLpuId(settings.misLpuId);
    setMisLogin(settings.misLogin);
    setMisPassword(settings.misPassword);
    setIasUrl(settings.iasUrl);
    setIasCheckUrl(settings.iasCheckUrl);
    setEcpUrl(settings.ecpUrl);
    setTfomsEncoding(settings.tfomsEncoding || 'cp1251');
    setError(null);
  }, [open, settings]);

  const handleClose = () => {
    setError(null);
    onClose();
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const failure = await onSave({
        user, password, defaultMo, misLpuId, misLogin, misPassword,
        iasUrl, iasCheckUrl, ecpUrl, tfomsEncoding,
      });
      if (failure) {
        setError(failure);
      } else {
        onClose();
      }
    } finally {
      setSaving(false);
    }
  };

  const status = settings.misStatus;
  const ecpReady = Boolean(status?.password_set);

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>Настройки</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Typography variant="subtitle2" color="text.secondary" sx={{ mt: 1, mb: 1 }}>
          ИАС-4
        </Typography>
        <TextField
          fullWidth
          label="Имя пользователя ИАС-4"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          margin="normal"
          required
        />
        <TextField
          fullWidth
          label="Пароль ИАС-4"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          margin="normal"
          required
        />
        <TextField
          fullWidth
          label="Код МО по умолчанию"
          value={defaultMo}
          onChange={(e) => setDefaultMo(e.target.value)}
          margin="normal"
          helperText="Например: 0893"
        />

        <Divider sx={{ my: 2 }} />

        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
          ЕЦП (внешняя МИС)
        </Typography>

        {status && (
          <Alert severity={ecpReady ? 'success' : 'warning'} sx={{ mb: 1 }}>
            <Box component="span" sx={{ display: 'block' }}>
              {ecpReady
                ? `Настроено: ${status.mis_login}`
                : 'Учётные данные ЕЦП не заданы'}
            </Box>
            {status.updated_at && (
              <Box component="span" sx={{ display: 'block', fontSize: '0.8em' }}>
                Обновлено: {new Date(status.updated_at).toLocaleString('ru-RU')}
              </Box>
            )}
          </Alert>
        )}

        <TextField
          fullWidth
          label="ID МО для ЕЦП (Lpu_id)"
          value={misLpuId}
          onChange={(e) => setMisLpuId(e.target.value)}
          margin="normal"
          helperText="По умолчанию: 13003795"
        />
        <TextField
          fullWidth
          label="Логин ЕЦП"
          value={misLogin}
          onChange={(e) => setMisLogin(e.target.value)}
          margin="normal"
          required
        />
        <TextField
          fullWidth
          label="Пароль ЕЦП"
          type="password"
          value={misPassword}
          onChange={(e) => setMisPassword(e.target.value)}
          margin="normal"
          required
        />
        <Typography variant="caption" color="text.secondary">
          Логин и пароль сохраняются на сервере и проверяются ЕЦП при сохранении.
          Указывайте оба поля: при пустом значении настройка будет отклонена.
        </Typography>

        <Divider sx={{ my: 2 }} />

        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
          Адреса сервисов
        </Typography>
        <TextField
          fullWidth
          label="Адрес ЕЦП"
          value={ecpUrl}
          onChange={(e) => setEcpUrl(e.target.value)}
          margin="normal"
          helperText="Сохраняется на шлюзе — он и обращается к ЕЦП"
        />
        <TextField
          fullWidth
          label="ИАС: прикрепление ЗЛ (SOAP)"
          value={iasUrl}
          onChange={(e) => setIasUrl(e.target.value)}
          margin="normal"
          helperText="Например: http://10.0.100.5/IASWeb/LoadPrk/LoadPrk.asmx"
        />
        <TextField
          fullWidth
          label="ИАС: проверка полиса (SOAP)"
          value={iasCheckUrl}
          onChange={(e) => setIasCheckUrl(e.target.value)}
          margin="normal"
          helperText="Например: http://10.0.100.5/IASWeb/InsCheck/InsCheck.asmx"
        />
        <TextField
          fullWidth
          label="Кодировка выгрузок ТФОМС"
          value={tfomsEncoding}
          onChange={(e) => setTfomsEncoding(e.target.value)}
          margin="normal"
          helperText="SPSMO.zip, SPMO.zip, SPFMODIVISION.zip обычно приходят в windows-1251"
        />
        <Typography variant="caption" color="text.secondary">
          Адреса можно менять на месте. Если поле оставить пустым, будет использовано
          значение из файла .env при первом запуске. Значения SOAPAction заданы
          протоколом ИАС-4 и не настраиваются.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={saving}>Отмена</Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}
          startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}>
          {saving ? 'Сохранение...' : 'Сохранить'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}