import axios from 'axios';
import type { MisUnifiedResponse } from '../types';

const client = axios.create({
  baseURL: '/api/mis',
  timeout: 60000,
});

export async function searchPatients(params: Record<string, any>): Promise<MisUnifiedResponse> {
  const response = await client.post<MisUnifiedResponse>('/search-patients', { params });
  return response.data;
}

export async function getPersonCard(params: Record<string, any>): Promise<MisUnifiedResponse> {
  const response = await client.post<MisUnifiedResponse>('/get-person-card', { params });
  return response.data;
}

export async function getRegionsId(params: Record<string, any>): Promise<MisUnifiedResponse> {
  const response = await client.post<MisUnifiedResponse>('/get-regions-id', { params });
  return response.data;
}

export async function savePersonCard(data: Record<string, any>): Promise<MisUnifiedResponse> {
  const response = await client.post<MisUnifiedResponse>('/save-person-card', data);
  return response.data;
}
