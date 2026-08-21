import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  // Workflows
  getWorkflows() { return this.http.get<any>('/api/workflows'); }
  getWorkflow(id: string) { return this.http.get<any>(`/api/workflows/${id}`); }
  runWorkflow(id: string, inputs: Record<string, any>) {
    return this.http.post<any>(`/api/workflows/${id}/run`, { inputs });
  }
  getExecutions(workflowId: string, params: Record<string, any> = {}) {
    return this.http.get<any>(`/api/workflows/${workflowId}/executions`, { params: new HttpParams({ fromObject: params }) });
  }
  getExecution(executionId: string) { return this.http.get<any>(`/api/executions/${executionId}`); }

  // Deployments
  getDeployments() { return this.http.get<any[]>('/api/deployments'); }
  getCredentials(id: string) { return this.http.get<any>(`/api/deployments/${id}/credentials`); }
  deleteDeployment(id: string) { return this.http.delete<any>(`/api/deployments/${id}`); }

  // Benchmarks
  getBenchmarks(params: Record<string, any> = {}) {
    return this.http.get<any>('/api/benchmarks', { params: new HttpParams({ fromObject: params }) });
  }
  getBenchmark(id: string) { return this.http.get<any>(`/api/benchmarks/${id}`); }
  compareBenchmarks(a: string, b: string) {
    return this.http.get<any>('/api/benchmarks/compare', { params: new HttpParams({ fromObject: { a, b } }) });
  }
}
