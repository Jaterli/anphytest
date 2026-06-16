import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { InvitationsResponse, InvitationsFilter } from '../models/invitations-management.models';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class InvitationsManagementService {
  private apiUrl = `${environment.apiUrl}/invitations/admin`;

  constructor(private http: HttpClient) {}

  getInvitations(filters: InvitationsFilter): Observable<InvitationsResponse> {
    let params = new HttpParams()
      .set('page', filters.page.toString())
      .set('page_size', filters.page_size.toString())
      .set('sort_by', filters.sort_by)
      .set('sort_order', filters.sort_order);

    // Agregar filtros opcionales
    if (filters.search) {
      params = params.set('search', filters.search);
    }
    if (filters.status) {
      params = params.set('status', filters.status);
    }
    if (filters.is_used !== undefined) {
      params = params.set('is_used', filters.is_used.toString());
    }
    if (filters.is_guest !== undefined) {
      params = params.set('is_guest', filters.is_guest.toString());
    }
    if (filters.test_id) {
      params = params.set('test_id', filters.test_id.toString());
    }
    if (filters.invited_by) {
      params = params.set('invited_by', filters.invited_by.toString());
    }
    if (filters.start_date) {
      params = params.set('start_date', filters.start_date);
    }
    if (filters.end_date) {
      params = params.set('end_date', filters.end_date);
    }

    return this.http.get<InvitationsResponse>(this.apiUrl, { params });
  }

  deleteInvitation(id: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/${id}/delete/`);
  }

  deleteInvitationsBulk(ids: number[]): Observable<any> {
    return this.http.delete(`${this.apiUrl}/bulk-delete/`, {
      body: { ids }
    });
  }

  getInvitationStats(): Observable<any> {
    return this.http.get(`${this.apiUrl}/stats/`);
  }
}