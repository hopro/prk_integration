import axios from 'axios';
import type { MisCredentialsStatus, SettingsData } from '../types';

const client = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

const longClient = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

export async function fetchSettings(includeMisStatus = false): Promise<SettingsData> {
  const response = await client.get<SettingsData>('/settings', {
    params: { includeMisStatus },
  });
  return response.data;
}

export async function saveSettings(settings: SettingsData): Promise<SettingsData> {
  const response = await client.post<SettingsData>('/settings', settings);
  return response.data;
}

export async function updateMisCredentials(login: string, password: string) {
  const response = await client.put('/v1/auth/mis-credentials', { login, password });
  return response.data;
}

export async function fetchMisCredentialsStatus() {
  const response = await client.get<{ success: boolean; data: MisCredentialsStatus; error?: string }>(
    '/v1/auth/mis-credentials',
  );
  return response.data;
}

export async function updateMisConfig(baseUrl: string) {
  const response = await longClient.put('/v1/auth/mis-config', { baseUrl });
  return response.data;
}