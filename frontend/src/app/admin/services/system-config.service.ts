import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { 
  SystemConfig, 
  CreateSystemConfigDTO, 
  UpdateSystemConfigDTO,
  BulkUpdateConfigDTO,
  DefaultSystemConfig
} from '../models/system-config.models';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class SystemConfigService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/admin/system-configs`;

  // Obtener todas las configuraciones
  getAll(): Observable<SystemConfig[]> {
    return this.http.get<SystemConfig[]>(this.apiUrl);
  }

  getAllDefault(): Observable<DefaultSystemConfig[]> {
    return this.http.get<DefaultSystemConfig[]>(`${this.apiUrl}/default/`);
  }

  // Obtener configuración por ID
  getById(id: number): Observable<SystemConfig> {
    return this.http.get<SystemConfig>(`${this.apiUrl}/${id}`);
  }

  // Obtener configuración por clave
  getByKey(key: string): Observable<string> {
    return this.http.get(`${this.apiUrl}/key/${key}/`, { responseType: 'text' });
  }

  // Crear nueva configuración
  create(config: CreateSystemConfigDTO): Observable<SystemConfig> {
    return this.http.post<SystemConfig>(this.apiUrl + '/create/', config);
  }

  // Actualizar configuración
  update(id: number, config: UpdateSystemConfigDTO): Observable<SystemConfig> {
    return this.http.put<SystemConfig>(`${this.apiUrl}/${id}/update/`, config);
  }

  // Eliminar configuración
  delete(id: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/${id}/delete/`);
  }

}