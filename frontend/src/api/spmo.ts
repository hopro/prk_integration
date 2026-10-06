import axios from 'axios';
import type { SpmoEntry, SpDeptEntry } from '../types';

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

export interface DictResponse {
  spmo: SpmoEntry[];
  spsmo: SpmoEntry[];
}

export async function fetchDict(): Promise<DictResponse> {
  const response = await client.get<DictResponse>('/dict');
  return response.data;
}

/**
 * Подразделения ЛПУ. Код (`SpDeptEntry.code`) — значение, которое ИАС-4
 * ожидает в поле podr. Источник — справочник подразделений ИАС-4 (SPDEPT),
 * а не участки ЕЦП: у ЕЦП своя нумерация, и её коды ИАС-4 отвергает.
 */
export async function fetchSpDept(mo?: number | string): Promise<SpDeptEntry[]> {
  const response = await client.get<{ spdept: SpDeptEntry[]; hint?: string }>('/dict/spdept', {
    params: mo ? { mo } : {},
  });
  if (!response.data.spdept.length) {
    throw new Error(response.data.hint || 'Справочник подразделений ИАС-4 не загружен');
  }
  return response.data.spdept;
}
