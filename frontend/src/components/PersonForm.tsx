import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import type { PersonData } from '../types';

interface Props {
  person: PersonData;
  onChange: (v: PersonData) => void;
}

const POLIS_TYPES = [
  { value: 1, label: 'Полис старого образца' },
  { value: 2, label: 'Временное свидетельство' },
  { value: 3, label: 'Полис единого образца' },
];

const SEX_TYPES = [
  { value: 'М', label: 'Мужской' },
  { value: 'Ж', label: 'Женский' },
];

export default function PersonForm({ person, onChange }: Props) {
  return (
    <>
      <TextField
        fullWidth
        label="Фамилия"
        value={person.fam}
        onChange={(e) => onChange({ ...person, fam: e.target.value })}
        margin="normal"
        required
      />
      <TextField
        fullWidth
        label="Имя"
        value={person.im}
        onChange={(e) => onChange({ ...person, im: e.target.value })}
        margin="normal"
        required
      />
      <TextField
        fullWidth
        label="Отчество"
        value={person.ot}
        onChange={(e) => onChange({ ...person, ot: e.target.value })}
        margin="normal"
      />
      <TextField
        fullWidth
        label="Дата рождения"
        type="date"
        value={person.dr}
        onChange={(e) => onChange({ ...person, dr: e.target.value })}
        margin="normal"
        required
        InputLabelProps={{ shrink: true }}
      />
      <TextField
        fullWidth
        select
        label="Пол"
        value={person.pol}
        onChange={(e) => onChange({ ...person, pol: e.target.value })}
        margin="normal"
        required
      >
        {SEX_TYPES.map((s) => (
          <MenuItem key={s.value} value={s.value}>
            {s.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        fullWidth
        select
        label="Тип полиса"
        value={person.vpolis}
        onChange={(e) => onChange({ ...person, vpolis: Number(e.target.value) })}
        margin="normal"
        required
      >
        {POLIS_TYPES.map((p) => (
          <MenuItem key={p.value} value={p.value}>
            {p.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        fullWidth
        label="Номер полиса"
        value={person.npolis}
        onChange={(e) => onChange({ ...person, npolis: e.target.value })}
        margin="normal"
        required
      />
    </>
  );
}
