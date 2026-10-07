import { useState, useEffect } from 'react';
import TextField from '@mui/material/TextField';
import Autocomplete from '@mui/material/Autocomplete';
import MenuItem from '@mui/material/MenuItem';
import IconButton from '@mui/material/IconButton';
import DeleteIcon from '@mui/icons-material/Delete';
import Alert from '@mui/material/Alert';
import { fetchSpDept } from '../api/spmo';
import type { AttachmentData, SpDeptEntry } from '../types';

interface Props {
  attachment: AttachmentData;
  index: number;
  onChange: (index: number, v: AttachmentData) => void;
  onRemove: (index: number) => void;
  canRemove: boolean;
  spmoMap: Record<number, string>;
}

const TYPES = [
  { value: 1, label: 'АПП' },
  { value: 3, label: 'Доврачебная в ФАП' },
];

const METHODS = [
  { value: 1, label: 'Территориально-участковый' },
  { value: 2, label: 'По заявлению' },
];

export default function AttachmentForm({
  attachment,
  index,
  onChange,
  onRemove,
  canRemove,
  spmoMap,
}: Props) {
  const [deptOptions, setDeptOptions] = useState<SpDeptEntry[]>([]);
  const [deptLoading, setDeptLoading] = useState(false);

  const [deptError, setDeptError] = useState<string | null>(null);

  useEffect(() => {
    setDeptLoading(true);
    setDeptError(null);
    fetchSpDept()
      .then(setDeptOptions)
      .catch((e) => {
        setDeptOptions([]);
        setDeptError(e?.response?.data?.detail || e?.message || 'Справочник подразделений недоступен');
      })
      .finally(() => setDeptLoading(false));
  }, []);

  const set = (field: keyof AttachmentData, value: any) =>
    onChange(index, { ...attachment, [field]: value });

  const selectedDept = deptOptions.find((d) => d.code === attachment.podr) || null;

  return (
    <>
      <TextField
        select
        label="Тип прикрепления"
        value={attachment.typeprk}
        onChange={(e) => set('typeprk', Number(e.target.value))}
        margin="normal"
        required
      >
        {TYPES.map((t) => (
          <MenuItem key={t.value} value={t.value}>
            {t.label}
          </MenuItem>
        ))}
      </TextField>
      {deptError && (
        <Alert severity="warning" sx={{ mt: 1 }}>{deptError}</Alert>
      )}
      <TextField
        fullWidth
        label="Код МО"
        type="number"
        value={attachment.mo || ''}
        onChange={(e) => {
          const mo = Number(e.target.value);
          set('mo', mo);
          set('podr', '');
        }}
        margin="normal"
        required
        helperText={spmoMap[attachment.mo] || ''}
      />
      <Autocomplete
        fullWidth
        options={deptOptions}
        loading={deptLoading}
        value={selectedDept}
        onChange={(_, newValue) => set('podr', newValue ? newValue.code : '')}
        // Пометка источника нужна, чтобы ФАП не путать с обычным участком:
        // коды приходят из разных выгрузок ИАС-4.
        getOptionLabel={(option) =>
          option.source ? `${option.code} — ${option.name} · ${option.source}` : `${option.code} — ${option.name}`
        }
        filterOptions={(options, state) => {
          const needle = state.inputValue.trim().toLowerCase();
          if (!needle) return options.slice(0, 200);
          return options
            .filter((o) => o.code.toLowerCase().includes(needle)
              || o.name.toLowerCase().includes(needle)
              || (o.ecpName || '').toLowerCase().includes(needle))
            .slice(0, 200);
        }}
        isOptionEqualToValue={(option, value) => option.code === value.code}
        renderInput={(params) => (
          <TextField
            {...params}
            label="Код участка/пункта (ФАП)"
            margin="normal"
            required
            placeholder="Поиск по коду или названию"
          />
        )}
        noOptionsText="Подразделения не найдены"
        loadingText="Загрузка подразделений..."
      />
      <TextField
        fullWidth
        label="Дата начала прикрепления"
        type="date"
        value={attachment.dbeg}
        onChange={(e) => set('dbeg', e.target.value)}
        margin="normal"
        required
        InputLabelProps={{ shrink: true }}
      />
      <TextField
        select
        label="Способ прикрепления"
        value={attachment.meth}
        onChange={(e) => set('meth', Number(e.target.value))}
        margin="normal"
        required
      >
        {METHODS.map((m) => (
          <MenuItem key={m.value} value={m.value}>
            {m.label}
          </MenuItem>
        ))}
      </TextField>
      {canRemove && (
        <IconButton
          color="error"
          onClick={() => onRemove(index)}
          sx={{ mt: 1 }}
        >
          <DeleteIcon />
        </IconButton>
      )}
    </>
  );
}
