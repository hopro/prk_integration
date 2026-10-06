import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Alert from '@mui/material/Alert';
import type { PersonData, AttachmentData } from '../types';

const SEX_LABELS: Record<string, string> = { М: 'Мужской', Ж: 'Женский' };
const POLIS_LABELS: Record<number, string> = {
  1: 'Полис старого образца',
  2: 'Временное свидетельство',
  3: 'Полис единого образца',
};
const TYPE_LABELS: Record<number, string> = {
  1: 'АПП',
  3: 'Доврачебная в ФАП',
};
const METHOD_LABELS: Record<number, string> = {
  1: 'Территориально-участковый',
  2: 'По заявлению',
};

function fmtDate(dateStr: string): string {
  if (!dateStr) return '';
  const [y, m, d] = dateStr.split('-');
  if (y && m && d) return `${d}.${m}.${y}`;
  return dateStr;
}

interface Props {
  open: boolean;
  person: PersonData;
  attachments: AttachmentData[];
  spmoMap: Record<number, string>;
  onConfirm: () => void;
  onClose: () => void;
}

export default function ConfirmDialog({
  open,
  person,
  attachments,
  spmoMap,
  onConfirm,
  onClose,
}: Props) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Подтверждение отправки</DialogTitle>
      <DialogContent>
        <Typography variant="h6" gutterBottom sx={{ mt: 1 }}>
          Данные пациента
        </Typography>
        <Box sx={{ ml: 2, mb: 2 }}>
          <Typography variant="body1">
            <b>ФИО:</b> {person.fam} {person.im} {person.ot}
          </Typography>
          <Typography variant="body1">
            <b>Дата рождения:</b> {fmtDate(person.dr)}
          </Typography>
          <Typography variant="body1">
            <b>Пол:</b> {SEX_LABELS[person.pol] || person.pol}
          </Typography>
          <Typography variant="body1">
            <b>Тип полиса:</b> {POLIS_LABELS[person.vpolis] || person.vpolis}
          </Typography>
          <Typography variant="body1">
            <b>Номер полиса:</b> {person.npolis}
          </Typography>
        </Box>

        <Divider sx={{ my: 2 }} />

        <Typography variant="h6" gutterBottom>
          Прикрепления
        </Typography>
        {attachments.map((a, i) => (
          <Box key={i} sx={{ ml: 2, mb: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Прикрепление {i + 1}
            </Typography>
            <Typography variant="body1">
              <b>Тип:</b> {TYPE_LABELS[a.typeprk] || a.typeprk}
            </Typography>
            <Typography variant="body1">
              <b>МО:</b> {a.mo} — {spmoMap[a.mo] || ''}
            </Typography>
            <Typography variant="body1">
              <b>Участок/пункт:</b> {a.podr}
            </Typography>
            <Typography variant="body1">
              <b>Дата начала:</b> {fmtDate(a.dbeg)}
            </Typography>
            <Typography variant="body1">
              <b>Способ:</b> {METHOD_LABELS[a.meth] || a.meth}
            </Typography>
          </Box>
        ))}

        <Alert severity="error" sx={{ mt: 3, '& .MuiAlert-message': { width: '100%' } }}>
          <Typography variant="h5" fontWeight="bold" align="center">
            ⚠ ВЫ УВЕРЕНЫ?
          </Typography>
          <Typography variant="h6" align="center">
            Данное действие НЕЛЬЗЯ отменить
          </Typography>
        </Alert>
        <Typography variant="body2" color="text.secondary" align="center" sx={{ mt: 2 }}>
          После подтверждения данные будут отправлены в ИАС-4 и ЕЦП
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Отмена</Button>
        <Button onClick={onConfirm} variant="contained" color="error">
          Подтвердить
        </Button>
      </DialogActions>
    </Dialog>
  );
}
