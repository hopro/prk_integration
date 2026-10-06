import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import type { InsCheckResponse } from '../types';

interface Props {
  response: InsCheckResponse;
  spmoMap: Record<number, string>;
  spsmoMap: Record<number, string>;
  spdeptMap: Record<string, string>;
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const parts = dateStr.split('-');
  if (parts.length !== 3) return dateStr;
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

export default function InsCheckResult({ response, spmoMap, spsmoMap, spdeptMap }: Props) {
  const { error_message, errors, ack, insurance, attachment, algs } = response;

  if (error_message) {
    return (
      <Alert severity="error">
        <AlertTitle>Ошибка</AlertTitle>
        {error_message}
      </Alert>
    );
  }

  const isSuccess = ack === 0;

  return (
    <>
      <Alert severity={isSuccess ? 'success' : 'warning'}>
        <AlertTitle>
          {isSuccess ? 'Страховая принадлежность определена' : `Ошибка обработки (ack=${ack})`}
        </AlertTitle>
        {algs.length > 0 && (
          <Typography variant="body2">
            Алгоритмы поиска: {algs.join(', ')}
          </Typography>
        )}
      </Alert>

      {errors.length > 0 && (
        <TableContainer component={Paper} sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Код</TableCell>
                <TableCell>Ошибка</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {errors.map((err, i) => (
                <TableRow key={i}>
                  <TableCell>{err.errcode}</TableCell>
                  <TableCell>{err.errtext}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Paper sx={{ mt: 2, p: 2 }}>
        <Typography variant="subtitle1" gutterBottom><b>Результат проверки</b></Typography>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell>СМО</TableCell>
              <TableCell>{insurance?.smo ?? '—'}{insurance?.smo && spsmoMap[insurance.smo] ? ` (${spsmoMap[insurance.smo]})` : ''}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>МО</TableCell>
              <TableCell>{attachment?.mo ?? '—'}{attachment?.mo && spmoMap[attachment.mo] ? ` (${spmoMap[attachment.mo]})` : ''}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Подразделение</TableCell>
              <TableCell>{attachment?.podr || '—'}{attachment?.podr && spdeptMap[attachment.podr] ? ` (${spdeptMap[attachment.podr]})` : ''}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Дата начала действия полиса</TableCell>
              <TableCell>{formatDate(insurance?.dbeg)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>Дата прикрепления</TableCell>
              <TableCell>{formatDate(attachment?.modt)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Paper>
    </>
  );
}
