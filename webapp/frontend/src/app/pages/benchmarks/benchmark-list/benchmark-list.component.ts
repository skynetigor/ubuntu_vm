import { Component, OnInit, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { TableModule } from 'primeng/table';
import { ButtonModule } from 'primeng/button';
import { ToastModule } from 'primeng/toast';
import { MessageService } from 'primeng/api';
import { ApiService } from '../../../core/api.service';

@Component({
  selector: 'app-benchmark-list',
  standalone: true,
  imports: [DatePipe, RouterLink, TableModule, ButtonModule, ToastModule],
  providers: [MessageService],
  template: `
    <p-toast />
    <div class="p-4">
      <div class="flex align-items-center justify-content-between mb-4">
        <h2 class="m-0">Benchmark Reports</h2>
        <div class="flex gap-2">
          <p-button label="Compare" icon="pi pi-chart-line" [disabled]="selected().length !== 2"
                    (onClick)="compare()" />
          <a pButton routerLink="/workflows" icon="pi pi-arrow-left" label="Workflows" [text]="true"></a>
        </div>
      </div>

      <p-table [value]="reports()" [(selection)]="selectedRows" dataKey="id" selectionMode="multiple"
               [loading]="loading()" [paginator]="true" [rows]="20"
               [totalRecords]="total()" [lazy]="true" (onLazyLoad)="onPage($event)"
               (selectionChange)="selected.set($event)"
               styleClass="p-datatable-sm" [rowHover]="true" (onRowClick)="open($event)">
        <ng-template pTemplate="header">
          <tr>
            <th style="width:3rem"><p-tableHeaderCheckbox /></th>
            <th pSortableColumn="@timestamp">Date <p-sortIcon field="@timestamp" /></th>
            <th>Project</th>
            <th>Target</th>
            <th pSortableColumn="throughput.completed">Completed <p-sortIcon field="throughput.completed" /></th>
            <th pSortableColumn="throughput.avg_rps">Avg RPS <p-sortIcon field="throughput.avg_rps" /></th>
            <th>Lag p95 (s)</th>
          </tr>
        </ng-template>
        <ng-template pTemplate="body" let-r>
          <tr class="cursor-pointer">
            <td><p-tableCheckbox [value]="r" /></td>
            <td class="text-sm">{{ r['@timestamp'] | date:'short' }}</td>
            <td class="font-mono text-sm">{{ r.project }}</td>
            <td class="text-sm" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" [title]="r.target">{{ r.target }}</td>
            <td>{{ r['throughput.completed'] ?? r.throughput?.completed ?? '—' }}</td>
            <td>{{ r['throughput.avg_rps'] ?? r.throughput?.avg_rps ?? '—' }}</td>
            <td>{{ r['scheduling_lag.p95_s'] ?? r.scheduling_lag?.p95_s ?? '—' }}</td>
          </tr>
        </ng-template>
        <ng-template pTemplate="empty">
          <tr><td colspan="7" class="text-center text-color-secondary p-4">No reports yet</td></tr>
        </ng-template>
      </p-table>
    </div>
  `,
})
export class BenchmarkListComponent implements OnInit {
  reports = signal<any[]>([]);
  total = signal(0);
  loading = signal(true);
  selected = signal<any[]>([]);
  selectedRows: any[] = [];

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit() { this.load(); }

  load(page = 1, size = 20) {
    this.loading.set(true);
    this.api.getBenchmarks({ size, page }).subscribe({
      next: (res) => { this.reports.set(res.results); this.total.set(res.total); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  onPage(e: any) { this.load((e.first / e.rows) + 1, e.rows); }

  open(e: any) { this.router.navigate(['/benchmarks', e.data.id]); }

  compare() {
    const [a, b] = this.selected();
    this.router.navigate(['/benchmarks/compare'], { queryParams: { a: a.id, b: b.id } });
  }
}
