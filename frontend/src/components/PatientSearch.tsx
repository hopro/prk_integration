import React, { useState, useCallback, useRef } from 'react';
import {
  Box, TextField, Button, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Alert,
  CircularProgress, IconButton, InputAdornment
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import { MisPatient } from '../types';
import { searchPatients, getPersonCard } from '../api/mis';

interface Props {
  onPatientSelected: (patient: MisPatient) => void;
  onManualEntry: () => void;
}

function normalizePolis(s: string): string {
  return s.replace(/\D/g, '');
}

function formatBirthDayForApi(birthDay: string): string {
  const clean = birthDay.replace(/\D/g, '');
  if (clean.length === 8) {
    return `${clean.slice(0, 2)}.${clean.slice(2, 4)}.${clean.slice(4, 8)}`;
  }
  return birthDay;
}

function toIsoDate(ddDotMmYyyy: string): string {
  const clean = ddDotMmYyyy.replace(/\D/g, '');
  if (clean.length === 8) {
    return `${clean.slice(4, 8)}-${clean.slice(2, 4)}-${clean.slice(0, 2)}`;
  }
  return '';
}

function fromIsoDate(iso: string): string {
  const clean = iso.replace(/\D/g, '');
  if (clean.length === 8) {
    return `${clean.slice(6, 8)}.${clean.slice(4, 6)}.${clean.slice(0, 4)}`;
  }
  return iso;
}

function formatSex(sexId: string | number | undefined): string {
  const id = String(sexId);
  if (id === '1') return 'М';
  if (id === '2') return 'Ж';
  return '';
}

export default function PatientSearch({ onPatientSelected, onManualEntry }: Props) {
  const [query, setQuery] = useState('');
  const [surName, setSurName] = useState('');
  const [firName, setFirName] = useState('');
  const [secName, setSecName] = useState('');
  const [birthDay, setBirthDay] = useState('');
  const [snils, setSnils] = useState('');
  const [polisNum, setPolisNum] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<MisPatient[]>([]);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const dateInputRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  }, [query, surName, firName, secName, birthDay, snils, polisNum]);

  const buildParams = (overrides: Record<string, string> = {}): Record<string, string> => {
    const sn = normalizePolis(snils);
    const pn = normalizePolis(polisNum);

    let sName = surName.trim();
    let fName = firName.trim();
    let oName = secName.trim();
    let bDay = birthDay.trim();

    if (!sName && !fName && !oName && !bDay && query.trim()) {
      const dateMatch = query.match(/(\d{2}\.\d{2}\.\d{4}|\d{8})/);
      if (dateMatch) bDay = dateMatch[1];
      const namePart = query.replace(dateMatch?.[0] || '', '').trim();
      const parts = namePart.split(/\s+/).filter(Boolean);
      if (parts.length === 1 && parts[0].length <= 3) {
        const chars = parts[0].split('');
        sName = chars[0] || '';
        fName = chars[1] || '';
        oName = chars[2] || '';
      } else {
        sName = parts[0] || '';
        fName = parts[1] || '';
        oName = parts[2] || '';
      }
    }

    const params: Record<string, string> = {
      Server_id: '1',
      limit: '30',
      offset: '0',
      doubleRegime: 'false',
      mode: 'PersonSearch',
      ...overrides,
      Double_ids: '[]',
    };

    if (sName) params.PersonSurName_SurName = sName.toUpperCase();
    if (fName) params.PersonFirName_FirName = fName.toUpperCase();
    if (oName) params.PersonSecName_SecName = oName.toUpperCase();
    if (bDay) params.PersonBirthDay_BirthDay = formatBirthDayForApi(bDay);
    if (sn) params.Person_Snils = sn;
    if (pn) params.Polis_Num = pn;

    return params;
  };

  const handleSearch = async (overrides?: Record<string, string>) => {
    if (!query.trim() && !surName.trim() && !firName.trim() && !secName.trim() && !birthDay.trim() && !snils.trim() && !polisNum.trim()) {
      setError('Заполните хотя бы одно поле для поиска');
      return;
    }

    setLoading(true);
    setError(null);
    setResults([]);
    setSearched(true);
    setSelectedId(null);

    try {
      const params = buildParams(overrides || {});
      const response = await searchPatients(params);

      if (response.success) {
        const raw = response.data;
        let list: any[] = [];
        if (Array.isArray(raw)) {
          list = raw;
        } else if (raw && typeof raw === 'object') {
          list = raw.data || raw.rows || raw.items || [];
          if (!Array.isArray(list)) list = [];
        }
        setResults(list);
      } else {
        setError(response.error?.message || 'Ошибка поиска');
      }
    } catch (e: any) {
      const msg = e?.response?.data?.error?.message || e?.response?.data?.detail || e?.message || 'Ошибка поиска пациентов';
      setError(typeof msg === 'string' ? msg : 'Ошибка поиска');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectPatient = async (patient: MisPatient) => {
    setSelectedId(patient.Person_id);
    setLoading(true);
    setError(null);

    try {
      const response = await getPersonCard({
        Person_id: patient.Person_id,
        Server_id: patient.Server_id,
        mode: 'PersonInformationPanel',
        additionalFields: '[]',
      });

      if (response.success) {
        const raw = response.data;
        const card = Array.isArray(raw) ? raw[0] : (raw?.data ? (Array.isArray(raw.data) ? raw.data[0] : raw.data) : raw);
        onPatientSelected({
          ...patient,
          ...card,
          Person_id: patient.Person_id,
          Server_id: patient.Server_id,
        });
      } else {
        setError(response.error?.message || 'Не удалось получить данные пациента');
      }
    } catch (e: any) {
      const msg = e?.response?.data?.error?.message || e?.message || 'Ошибка получения данных';
      setError(typeof msg === 'string' ? msg : 'Ошибка получения данных');
    } finally {
      setLoading(false);
      setSelectedId(null);
    }
  };

  const patientToString = (p: MisPatient) => {
    const fio = [p.PersonSurName_SurName, p.PersonFirName_FirName, p.PersonSecName_SecName]
      .filter(Boolean).join(' ');
    return fio || `Пациент ID: ${p.Person_id}`;
  };

  const handleBirthDayChange = (value: string) => {
    let cleaned = value.replace(/[^\d]/g, '');
    if (cleaned.length > 8) cleaned = cleaned.slice(0, 8);
    let formatted = cleaned;
    if (cleaned.length > 4) {
      formatted = `${cleaned.slice(0, 2)}.${cleaned.slice(2, 4)}.${cleaned.slice(4)}`;
    } else if (cleaned.length > 2) {
      formatted = `${cleaned.slice(0, 2)}.${cleaned.slice(2)}`;
    }
    setBirthDay(formatted);
  };

  const handleCalendarClick = () => {
    dateInputRef.current?.showPicker();
  };

  const handleNativeDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.value) {
      setBirthDay(fromIsoDate(e.target.value));
    }
  };

  return (
    <Box>
      <Box display="flex" gap={1.5} alignItems="center">
        <TextField
          label="Поиск пациента (ФИО, дата рождения, СНИЛС)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          size="small"
          fullWidth
          placeholder="Иванов Иван Иванович 01.01.1990"
        />
        <Button
          variant="contained"
          startIcon={loading ? <CircularProgress size={16} /> : <SearchIcon />}
          onClick={() => handleSearch()}
          disabled={loading}
          sx={{ minWidth: 100 }}
        >
          Найти
        </Button>
      </Box>

      <Box display="grid" gridTemplateColumns="1fr 1fr 1fr 170px" gap={1.5} alignItems="center" sx={{ mt: 1.5 }}>
        <TextField
          label="Фамилия"
          value={surName}
          onChange={(e) => setSurName(e.target.value)}
          size="small"
          onKeyDown={handleKeyDown}
        />
        <TextField
          label="Имя"
          value={firName}
          onChange={(e) => setFirName(e.target.value)}
          size="small"
          onKeyDown={handleKeyDown}
        />
        <TextField
          label="Отчество"
          value={secName}
          onChange={(e) => setSecName(e.target.value)}
          size="small"
          onKeyDown={handleKeyDown}
        />
        <TextField
          label="Дата рождения"
          value={birthDay}
          onChange={(e) => handleBirthDayChange(e.target.value)}
          onKeyDown={handleKeyDown}
          size="small"
          placeholder="06.06.1985"
          InputProps={{
            endAdornment: (
              <InputAdornment position="end">
                <input
                  ref={dateInputRef}
                  type="date"
                  value={toIsoDate(birthDay)}
                  onChange={handleNativeDateChange}
                  style={{ position: 'absolute', opacity: 0, width: 0, height: 0, pointerEvents: 'none' }}
                />
                <IconButton size="small" edge="end" onClick={handleCalendarClick}>
                  <CalendarMonthIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          }}
        />
      </Box>

      <Box display="grid" gridTemplateColumns="1fr 1fr" gap={1.5} alignItems="center" sx={{ mt: 1.5 }}>
        <TextField
          label="СНИЛС"
          value={snils}
          onChange={(e) => setSnils(e.target.value)}
          placeholder="123-456-789 00"
          size="small"
          onKeyDown={handleKeyDown}
        />
        <TextField
          label="Номер полиса"
          value={polisNum}
          onChange={(e) => setPolisNum(e.target.value)}
          size="small"
          onKeyDown={handleKeyDown}
        />
      </Box>

      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

      {searched && !loading && results.length === 0 && !error && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Пациент не найден.{' '}
          <Button size="small" onClick={onManualEntry} startIcon={<PersonAddIcon />}>
            Ввести данные вручную
          </Button>
        </Alert>
      )}

      {results.length > 0 && (
        <Paper sx={{ mt: 2, maxHeight: 400, overflow: 'auto' }}>
          <TableContainer>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>ФИО</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Дата рождения</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Пол</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Действие</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {results.map((p, idx) => {
                  const sex = formatSex(p.Sex_id);
                  return (
                    <TableRow
                      key={p.Person_id || idx}
                      hover
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell>{patientToString(p)}</TableCell>
                      <TableCell>{p.PersonBirthDay_BirthDay || ''}</TableCell>
                      <TableCell>{sex}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => handleSelectPatient(p)}
                          disabled={selectedId === p.Person_id}
                          endIcon={selectedId === p.Person_id ? <CircularProgress size={14} /> : undefined}
                        >
                          {selectedId === p.Person_id ? 'Загрузка...' : 'Выбрать →'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      <Box sx={{ mt: 2 }}>
        <Button
          variant="outlined"
          startIcon={<PersonAddIcon />}
          onClick={onManualEntry}
          fullWidth
        >
          Ввести данные пациента вручную
        </Button>
      </Box>
    </Box>
  );
}
