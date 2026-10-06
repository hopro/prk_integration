import axios from 'axios';
import type { LoadPrkRequest, LoadPrkResponse, PrkHistoryResponse, PrkStats } from '../types';

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

export async function sendLoadPrk(data: LoadPrkRequest): Promise<LoadPrkResponse> {
  const response = await client.post<LoadPrkResponse>('/prk/load', data);
  return response.data;
}

export async function fetchHistory(params: {
  page?: number;
  limit?: number;
  date_from?: string;
  date_to?: string;
  fam?: string;
  mo?: number;
}): Promise<PrkHistoryResponse> {
  const response = await client.get<PrkHistoryResponse>('/prk/history', { params });
  return response.data;
}

export async function fetchStats(): Promise<PrkStats> {
  const response = await client.get<PrkStats>('/prk/stats');
  return response.data;
}

export async function downloadScd(data: {
  fam: string;
  im: string;
  ot: string;
  dr: string;
  w: number;
  vpolis: number;
  npolis: string;
  snils?: string;
}): Promise<void> {
  const response = await client.post('/prk/generate-scd', data, {
    responseType: 'blob',
  });
  const disposition = response.headers['content-disposition'];
  let filename = 'QuerySCD.SCD';
  if (disposition) {
    const match = disposition.match(/filename="?(.+?)"?$/);
    if (match) filename = match[1];
  }
  const url = URL.createObjectURL(new Blob([response.data]));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function parseAsc(file: File): Promise<any> {
  const form = new FormData();
  form.append('file', file);
  const response = await client.post('/prk/parse-asc', form);
  return response.data;
}
