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
import type { LoadPrkResponse } from '../types';

interface Props {
  response: LoadPrkResponse;
  spmoMap: Record<number, string>;
}

export default function ResultPanel({ response, spmoMap }: Props) {
  const { result, error_message, prk_list } = response;

  if (error_message) {
    return (
      <Alert severity="error">
        <AlertTitle>Ошибка</AlertTitle>
        {error_message}
      </Alert>
    );
  }

  if (!result) {
    return <Alert severity="warning">Нет данных о результате обработки</Alert>;
  }

  const isSuccess = result.ack === 0;

  return (
    <>
      <Alert severity={isSuccess ? 'success' : 'error'}>
        <AlertTitle>
          {isSuccess
            ? 'Прикрепление успешно загружено в РС ЕРЗ'
            : `Ошибка обработки (ack=${result.ack})`}
        </AlertTitle>
        {result.timeoper && (
          <Typography variant="body2">
            Дата и время обработки: {result.timeoper}
          </Typography>
        )}
      </Alert>

      {prk_list && prk_list.length > 0 && (
        <Paper sx={{ mt: 2, p: 2 }}>
          <Typography variant="subtitle1" gutterBottom><b>Прикрепления</b></Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Код МО</TableCell>
                <TableCell>Наименование МО</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {prk_list.map((prk, i) => (
                <TableRow key={i}>
                  <TableCell>{prk.mo}</TableCell>
                  <TableCell>{spmoMap[prk.mo] || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {result.errors.length > 0 && (
        <TableContainer component={Paper} sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Код</TableCell>
                <TableCell>Наименование</TableCell>
                <TableCell>Комментарий</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {result.errors.map((err, i) => (
                <TableRow key={i}>
                  <TableCell>{err.errcode}</TableCell>
                  <TableCell>{err.errname}</TableCell>
                  <TableCell>{err.comment}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {response.mis_save_result && (
        <Alert severity={response.mis_save_result.success !== false ? 'success' : 'warning'} sx={{ mt: 2 }}>
          <AlertTitle>
            Отправка в ЕЦП
          </AlertTitle>
          {response.mis_save_result.success !== false
            ? 'Данные успешно отправлены в ЕЦП'
            : `Ошибка: ${typeof response.mis_save_result.error === 'string' ? response.mis_save_result.error : JSON.stringify(response.mis_save_result.error)}`
          }
        </Alert>
      )}
    </>
  );
}
