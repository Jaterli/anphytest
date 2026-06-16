import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap, switchMap, of } from 'rxjs';
import { 
  TestInvitation, 
  CreateInvitationInput, 
  CheckInvitationResponse,
  AcceptInvitationResponse
} from '../models/invitation.models';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

@Injectable({
  providedIn: 'root'
})
export class InvitationService {
  private http = inject(HttpClient);
  private authService = inject(AuthService);  
  private apiUrl = `${environment.apiUrl}/invitations`;

  // Crear invitación
  createInvitation(data: CreateInvitationInput): Observable<any> {
    return this.http.post(`${this.apiUrl}/create/`, data);
  }

  // Obtener invitaciones del usuario
  getMyInvitations(): Observable<{invitations: TestInvitation[]}> {
    return this.http.get<{invitations: TestInvitation[]}>(`${this.apiUrl}/my-invitations/`);
  }

  // Verificar invitación
  checkInvitation(token: string): Observable<CheckInvitationResponse> {
    return this.http.get<CheckInvitationResponse>(`${this.apiUrl}/check-invitation?token=${token}`);
  }

  // Aceptar invitación
  acceptInvitation(token: string, asGuest?: boolean): Observable<AcceptInvitationResponse> {
    return this.http.post<AcceptInvitationResponse>(
      `${this.apiUrl}/accept-invitation?token=${token}`,
      { as_guest: asGuest || false }
    ).pipe(
      tap(response => {
        // Si la respuesta incluye un token, guardarlo y actualizar estado
        if (response.access_token) {
          console.log('Token recibido, guardando en localStorage');
          localStorage.setItem('access_token', response.access_token);
          
          // Forzar la actualización del estado de autenticación
          if (response.user) {
            // Actualizar directamente el estado del usuario
            this.authService['setUser'](response.user); // Usamos setUser internamente
          }
        }
      }),
      // Opcional: refrescar el estado de autenticación después de guardar el token
      switchMap(response => {
        if (response.access_token) {
          return this.authService.refreshAuth().pipe(
            tap(() => {}),
            switchMap(() => of(response))
          );
        }
        return of(response);
      })
    );
  }
}