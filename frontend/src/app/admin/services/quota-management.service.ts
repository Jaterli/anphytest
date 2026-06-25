// src/app/features/quota/services/quota-management.service.ts

import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { QuotaResponse, QuotaFilter, CreateQuotaInput, UpdateQuotaInput, UserQuota } from '../models/quota-management.models';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class QuotaManagementService {
  private apiUrl = `${environment.apiUrl}/admin/quotas`;

  constructor(private http: HttpClient) {}

  // Rutas de administración
  getQuotas(filters: QuotaFilter): Observable<QuotaResponse> {
    let params = new HttpParams()
      .set('page', filters.page.toString())
      .set('page_size', filters.page_size.toString())
      .set('sort_by', filters.sort_by)
      .set('sort_order', filters.sort_order);

    // Agregar filtros opcionales
    if (filters.search) {
      params = params.set('search', filters.search);
    }
    if (filters.user_id) {
      params = params.set('user_id', filters.user_id.toString());
    }
    if (filters.month_year) {
      params = params.set('month_year', filters.month_year);
    }
    if (filters.min_remaining !== undefined) {
      params = params.set('min_remaining', filters.min_remaining.toString());
    }
    if (filters.max_usage !== undefined) {
      params = params.set('max_usage', filters.max_usage.toString());
    }
    if (filters.min_requests !== undefined && filters.min_requests !== null) {
      params = params.set('min_requests', filters.min_requests.toString());
    }
    if (filters.max_requests !== undefined && filters.max_requests !== null) {
      params = params.set('max_requests', filters.max_requests.toString());
    }
    if (filters.quota_status) {
      params = params.set('quota_status', filters.quota_status);
    }
    if (filters.start_date) {
      params = params.set('start_date', filters.start_date);
    }
    if (filters.end_date) {
      params = params.set('end_date', filters.end_date);
    }

    return this.http.get<QuotaResponse>(`${this.apiUrl}`, { params });
  }

  // Obtener cuota por ID de usuario
  getUserQuota(userId: number, monthYear?: string): Observable<{ quota: UserQuota }> {
    let params = new HttpParams();
    if (monthYear) {
      params = params.set('month_year', monthYear);
    }
    return this.http.get<{ quota: UserQuota }>(`${this.apiUrl}/user/${userId}/`, { params });
  }

  // Crear cuota
  createQuota(data: CreateQuotaInput): Observable<{ quota: UserQuota; message: string }> {
    return this.http.post<{ quota: UserQuota; message: string }>(
      `${this.apiUrl}/admin/quotas/`,
      data
    );
  }

  // Actualizar cuota
  updateQuota(id: number, data: UpdateQuotaInput): Observable<{ quota: UserQuota; message: string }> {
    return this.http.put<{ quota: UserQuota; message: string }>(
      `${this.apiUrl}/${id}/update/`,
      data
    );
  }

  // Eliminar cuota
  deleteQuota(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.apiUrl}/${id}/delete/`);
  }

  // Eliminar múltiples cuotas
  deleteQuotasBulk(ids: number[]): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.apiUrl}/bulk-delete/`, {
      body: { ids }
    });
  }

  // Obtener meses disponibles para un usuario
  getUserQuotaMonths(userId: number): Observable<{ months: string[] }> {
    return this.http.get<{ months: string[] }>(`${this.apiUrl}/user/${userId}/months/`);
  }

  // Verificar si hay cuota disponible
  checkQuotaAvailability(userId: number): Observable<{ 
    available: boolean; 
    quota: UserQuota;
    message: string;
  }> {
    return this.http.get<{ available: boolean; quota: UserQuota; message: string }>(
      `${this.apiUrl}/me/check/`
    );
  }
}