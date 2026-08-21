import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { CardModule } from 'primeng/card';
import { ChartModule } from 'primeng/chart';
import { TableModule } from 'primeng/table';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';
import { ApiService } from '../../../core/api.service';

@Component({
  selector: 'app-benchmark-detail',
  standalone: true,
  imports: [DatePipe, RouterLink, CardModule, ChartModule, TableModule, ButtonModule, TagModule],
  template: `
    <div class="p-4">
      <div class="flex align-items-center gap-3 mb-4">
        <a pButton routerLink="/benchmarks" icon="pi pi-arrow-left" [text]="true"></a>
        <h2 class="m-0">{{ report()?.project ?? 'Report' }}</h2>
        <span class="text-color-secondary text-sm">{{ report()?.['@timestamp'] | date:'medium' }}</span>
      </div>

      @if (report(); as r) {
        <!-- Stat cards -->
        <div class="grid mb-4">
          @for (card of statCards(r); track card.label) {
            <div class="col-6 md:col-3 lg:col-2">
              <p-card [header]="card.label" styleClass="text-center">
                <span class="text-2xl font-bold">{{ card.value }}</span>
              </p-card>
            </div>
          }
        </div>

        <!-- Throughput chart -->
        @if (throughputData(r); as data) {
          <p-card header="Throughput over time (completions / 30 s)" styleClass="mb-4">
            <p-chart type="line" [data]="data" [options]="lineOpts" />
          </p-card>
        }

        <!-- Scheduling lag percentiles -->
        @if (lagData(r); as data) {
          <p-card header="Scheduling lag percentiles" styleClass="mb-4">
            <p-chart type="bar" [data]="data" [options]="barOpts" />
          </p-card>
        }

        <!-- Task Manager snapshot -->
        @if (r.task_manager) {
          <p-card header="Task Manager snapshot" styleClass="mb-4">
            <p-table [value]="tmRows(r)" styleClass="p-datatable-sm">
              <ng-template pTemplate="header"><tr><th>Status</th><th>Count</th></tr></ng-template>
              <ng-template pTemplate="body" let-row><tr><td>{{ row.status }}</td><td>{{ row.count }}</td></tr></ng-template>
            </p-table>
          </p-card>
        }
      } @else {
        <p class="text-color-secondary">Loading…</p>
      }
    </div>
  `,
})
export class BenchmarkDetailComponent implements OnInit {
  report = signal<any>(null);

  lineOpts = { responsive: true, plugins: { legend: { display: false } } };
  barOpts = { responsive: true, plugins: { legend: { display: false } } };

  constructor(private route: ActivatedRoute, private api: ApiService) {}

  ngOnInit() {
    this.route.params.subscribe(p => {
      this.api.getBenchmark(p['id']).subscribe(r => this.report.set(r));
    });
  }

  statCards(r: any) {
    const t = r.throughput ?? {};
    const lag = r.scheduling_lag ?? {};
    const e2e = r.e2e_latency ?? {};
    return [
      { label: 'Completed', value: t.completed ?? '—' },
      { label: 'Failed', value: t.failed ?? '—' },
      { label: 'Avg RPS', value: t.avg_rps ?? '—' },
      { label: 'Peak RPS 30s', value: t.peak_rps_30s ?? '—' },
      { label: 'Wall time', value: r.total_wall_time_s != null ? `${r.total_wall_time_s}s` : '—' },
      { label: 'Lag p50', value: lag.p50_s != null ? `${lag.p50_s}s` : '—' },
      { label: 'Lag p95', value: lag.p95_s != null ? `${lag.p95_s}s` : '—' },
      { label: 'Lag p99', value: lag.p99_s != null ? `${lag.p99_s}s` : '—' },
      { label: 'E2E p50', value: e2e.p50_s != null ? `${e2e.p50_s}s` : '—' },
      { label: 'E2E p95', value: e2e.p95_s != null ? `${e2e.p95_s}s` : '—' },
      { label: 'E2E p99', value: e2e.p99_s != null ? `${e2e.p99_s}s` : '—' },
    ];
  }

  throughputData(r: any) {
    const buckets: any[] = r.throughput?.over_time ?? [];
    if (!buckets.length) return null;
    return {
      labels: buckets.map(b => b.window_start),
      datasets: [{ label: 'RPS', data: buckets.map(b => b.rps), fill: false, tension: 0.3, borderColor: '#6366f1' }],
    };
  }

  lagData(r: any) {
    const lag = r.scheduling_lag;
    if (!lag) return null;
    const keys = ['p50_s', 'p75_s', 'p95_s', 'p99_s'];
    return {
      labels: ['p50', 'p75', 'p95', 'p99'],
      datasets: [{ label: 'Lag (s)', data: keys.map(k => lag[k] ?? 0), backgroundColor: '#6366f1' }],
    };
  }

  tmRows(r: any) {
    return Object.entries(r.task_manager ?? {}).map(([status, count]) => ({ status, count }));
  }
}
