import TextField from '@mui/material/TextField';
import type { LoginData } from '../types';

interface Props {
  login: LoginData;
  onChange: (v: LoginData) => void;
}

export default function LoginForm({ login, onChange }: Props) {
  return (
    <>
      <TextField
        fullWidth
        label="Имя пользователя"
        value={login.user}
        onChange={(e) => onChange({ ...login, user: e.target.value })}
        margin="normal"
        required
      />
      <TextField
        fullWidth
        label="Пароль"
        type="password"
        value={login.password}
        onChange={(e) => onChange({ ...login, password: e.target.value })}
        margin="normal"
        required
      />
    </>
  );
}
