import axios from 'axios';
import type { DictionaryItem, DictionaryLoadLog, DictionaryRow, DictionarySources } from '../types';

const client = axios.create({
  baseURL: '/api/dictionaries',
  // Загрузка участков из ЕЦП идёт через шлюз и может занять время.
  timeout: 120000,
});

export async function fetchDictionaryStatus(): Promise<DictionaryItem[]> {
  const response = await client.get<{ items: DictionaryItem[] }>('/status');
  return response.data.items;
}

export async function fetchDictionaryLog(): Promise<DictionaryLoadLog[]> {
  const response = await client.get<{ items: DictionaryLoadLog[] }>('/log');
  return response.data.items;
}

export async function fetchDictionarySources(): Promise<DictionarySources> {
  const response = await client.get<DictionarySources>('/sources');
  return response.data;
}

export async function loadDictionary(
  kind: string,
  scope = '',
): Promise<{ rows: number; source: string; scope: string }> {
  const response = await client.post<{ rows: number; source: string; scope: string }>('/load', {
    kind,
    scope,
  });
  return response.data;
}

export async function fetchRegions(lpuId: string): Promise<{ items: DictionaryRow[]; lpuId: string }> {
  const response = await client.get<{ items: DictionaryRow[]; lpuId: string }>('/regions', {
    params: { lpuId },
  });
  return response.data;
}

/**
 * Участки для выбора при работе с пациентом: сначала локальный кэш
 * (вкладка «Справочники»), при его пустоте — живой запрос к ЕЦП.
 */
export async function fetchRegionsForPatient(
  lpuId: string,
  liveFetch: (lpuId: string) => Promise<any[]>,
): Promise<{ regions: DictionaryRow[]; source: 'cache' | 'ecp' }> {
  try {
    const cached = (await fetchRegions(lpuId)).items;
    if (cached.length) return { regions: cached, source: 'cache' };
  } catch {
    // Кэш недоступен — идём в ЕЦП.
  }
  const live = await liveFetch(lpuId);
  return { regions: (live || []) as DictionaryRow[], source: 'ecp' };
}

export async function fetchEntries(
  kind: string,
  scope = '',
  search = '',
  limit = 0,
): Promise<DictionaryRow[]> {
  const response = await client.get<{ items: DictionaryRow[] }>('/entries', {
    params: { kind, scope, search, limit },
  });
  return response.data.items;
}

/**
 * Загрузка XML-выгрузки ТФОМС файлом. Только zip/xml: CSV-импорт справочников
 * в системе отсутствует, участки ЛПУ приходят исключительно из ЕЦП.
 */
export async function uploadDictionaryXml(
  kind: string,
  file: File,
): Promise<{ kind: string; rows: number; source: string; entry?: string }> {
  const form = new FormData();
  form.append('kind', kind);
  form.append('file', file);
  const response = await client.post<{ kind: string; rows: number; source: string; entry?: string }>(
    '/upload',
    form,
  );
  return response.data;
}