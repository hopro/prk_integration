import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Grid from '@mui/material/Grid';
import type { InsCheckRequest } from '../types';

interface Props {
  data: InsCheckRequest;
  onChange: (v: InsCheckRequest) => void;
}

const POLIS_TYPES = [
  { value: 1, label: 'Полис старого образца' },
  { value: 2, label: 'Временное свидетельство' },
  { value: 3, label: 'Полис единого образца' },
];

export default function InsCheckForm({ data, onChange }: Props) {
  const set = (field: keyof InsCheckRequest, value: any) =>
    onChange({ ...data, [field]: value });

  return (
    <Grid container spacing={2}>
      <Grid item xs={4}>
        <TextField
          fullWidth
          select
          label="Тип полиса"
          value={data.vpolis ?? ''}
          onChange={(e) => set('vpolis', e.target.value === '' ? null : Number(e.target.value))}
          margin="normal"
          size="small"
        >
          <MenuItem value="">Не указан</MenuItem>
          {POLIS_TYPES.map((p) => (
            <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
          ))}
        </TextField>
      </Grid>
      <Grid item xs={8}>
        <TextField
          fullWidth
          label="Номер полиса"
          value={data.npolis}
          onChange={(e) => set('npolis', e.target.value)}
          margin="normal"
          size="small"
        />
      </Grid>
    </Grid>
  );
}
