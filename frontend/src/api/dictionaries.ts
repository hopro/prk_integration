import axios from 'axios';
import type {
  DictionaryItem,
  DictionaryLoadLog,
  DictionaryRow,
  DictionarySources,
  RegionLinkRow,
  RegionLinksMatrix,
  RegionLinkSuggestion,
} from '../types';

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

/**
 * Страница справочника. Выдаём порциями: полная выгрузка в таблицу браузера
 * мешает, а ответ несёт общее число записей для счётчика и пагинации.
 */
export async function fetchEntriesPage(
  kind: string,
  options: { scope?: string; search?: string; limit?: number; offset?: number } = {},
): Promise<{ items: DictionaryRow[]; total: number; truncated: boolean }> {
  const response = await client.get<{
    items: DictionaryRow[];
    total: number;
    truncated: boolean;
  }>('/entries', {
    params: { kind, limit: options.limit ?? 200, offset: options.offset ?? 0, ...options },
  });
  return response.data;
}

export async function fetchEntries(
  kind: string,
  scope = '',
  search = '',
  limit = 200,
): Promise<DictionaryRow[]> {
  return (await fetchEntriesPage(kind, { scope, search, limit })).items;
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

// ------------------------------------------ сопоставление подразделений и участков

export async function fetchRegionLinks(
  lpuId: string,
  includeForbidden = false,
): Promise<RegionLinksMatrix> {
  const response = await client.get<RegionLinksMatrix>('/region-links', {
    params: { lpuId, includeForbidden },
  });
  return response.data;
}

export async function saveRegionLink(
  podr: string,
  regionId: string,
  lpuId = '',
): Promise<{ linked: boolean; regionId: string }> {
  const response = await client.post<{ linked: boolean; regionId: string }>('/region-links', {
    podr,
    regionId,
    lpuId,
  });
  return response.data;
}

/** Полностью убирает привязку: код снова попадёт в автоподбор. */
export async function forgetRegionLink(podr: string, lpuId = ''): Promise<{ removed: boolean }> {
  const response = await client.post<{ removed: boolean }>('/region-links/forget', { podr, lpuId });
  return response.data;
}

export async function fetchRegionLinkSuggestions(
  lpuId: string,
): Promise<{ items: RegionLinkSuggestion[]; total: number }> {
  const response = await client.get<{ items: RegionLinkSuggestion[]; total: number }>(
    '/region-links/suggest',
    { params: { lpuId } },
  );
  return response.data;
}

export async function applyRegionLinkSuggestions(
  links: RegionLinkSuggestion[],
  lpuId = '',
): Promise<{ applied: number; rejected: number }> {
  const response = await client.post<{ applied: number; rejected: number }>(
    '/region-links/apply',
    { links, lpuId },
  );
  return response.data;
}
