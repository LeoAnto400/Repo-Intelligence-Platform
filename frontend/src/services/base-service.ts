import { AxiosInstance } from 'axios';
import { apiClient } from '@/lib/api-client';

export abstract class BaseService {
  protected client: AxiosInstance;

  constructor() {
    this.client = apiClient;
  }

  protected async get<T>(url: string, config = {}): Promise<T> {
    const response = await this.client.get<T>(url, config);
    return response.data;
  }

  protected async post<T>(url: string, data = {}, config = {}): Promise<T> {
    const response = await this.client.post<T>(url, data, config);
    return response.data;
  }

  protected async delete<T>(url: string, config = {}): Promise<T> {
    const response = await this.client.delete<T>(url, config);
    return response.data;
  }
}
