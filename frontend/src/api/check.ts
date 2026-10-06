import axios from 'axios';
import type { InsCheckRequest, InsCheckResponse } from '../types';

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

export async function sendInsCheck(data: InsCheckRequest): Promise<InsCheckResponse> {
  const response = await client.post<InsCheckResponse>('/ins-check/check', data);
  return response.data;
}
