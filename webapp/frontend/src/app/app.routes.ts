import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: '', redirectTo: '/workflows', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'workflows',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/workflows/workflows-layout/workflows-layout.component').then(m => m.WorkflowsLayoutComponent),
    children: [
      {
        path: ':id',
        loadComponent: () => import('./pages/workflows/workflow-detail/workflow-detail.component').then(m => m.WorkflowDetailComponent),
        children: [
          {
            path: 'executions/:eid',
            loadComponent: () => import('./pages/workflows/execution-detail/execution-detail.component').then(m => m.ExecutionDetailComponent),
          },
        ],
      },
    ],
  },
  {
    path: 'deployments',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/deployments/deployments.component').then(m => m.DeploymentsComponent),
  },
  {
    path: 'benchmarks',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/benchmarks/benchmark-list/benchmark-list.component').then(m => m.BenchmarkListComponent),
  },
  {
    path: 'benchmarks/compare',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/benchmarks/benchmark-compare/benchmark-compare.component').then(m => m.BenchmarkCompareComponent),
  },
  {
    path: 'benchmarks/:id',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/benchmarks/benchmark-detail/benchmark-detail.component').then(m => m.BenchmarkDetailComponent),
  },
  { path: '**', redirectTo: '/workflows' },
];
