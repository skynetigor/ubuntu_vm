import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { CardModule } from 'primeng/card';
import { ChartModule } from 'primeng/chart';
import { TableModule } from 'primeng/table';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';
import { ApiService } from '../../../core/api.service';

interface MetricRow { label: string; a: string | number; b: string | number; delta: number | null; better: 'a' | 'b' | null; }

@Component({
  selector: 'app-benchmark-compare',
  standalone: true,
  imports: [DatePipe, RouterLink, CardModule, ChartModule, TableModule, ButtonModule, TagModule],
  template: `
    <div class="p-4">
      <div class="flex align-items-center gap-3 mb-4">
        <a pButton routerLink="/benchmarks" icon="pi pi-arrow-left" [text]="true"></a>
        <h2 class="m-0">Compare Reports</h2>
      </div>

      @if (pair(); as p) {
        <!-- Headers -->
        <div class="grid mb-4">
          <div class="col-5">
            <p-card>
              <p class="font-bold m-0">A — {{ p.a.project }}</p>
              <p class="text-color-secondary text-sm m-0">{{ p.a['@timestamp'] | date:'medium' }}</p>
              <p class="font-mono text-xs m-0 mt-1 text-color-secondary">{{ p.a.commit }}</p>
            </p-card>
          </div>
          <div class="col-2 flex align-items-center justify-content-center text-color-secondary font-bold">vs</div>
          <div class="col-5">
            <p-card>
              <p class="font-bold m-0">B — {{ p.b.project }}</p>
              <p class="text-color-secondary text-sm m-0">{{ p.b['@timestamp'] | date:'medium' }}</p>
              <p class="font-mono text-xs m-0 mt-1 text-color-secondary">{{ p.b.commit }}</p>
            </p-card>
          </div>
        </div>

        <!-- Metric table -->
        <p-card styleClass="mb-4">
          <p-table [value]="rows(p)" styleClass="p-datatable-sm">
            <ng-template pTemplate="header">
              <tr><th>Metric</th><th>A</th><th>Δ%</th><th>B</th></tr>
            </ng-template>
            <ng-template pTemplate="body" let-r>
              <tr>
                <td class="font-medium">{{ r.label }}</td>
                <td [class]="r.better === 'a' ? 'font-bold text-green-500' : ''">{{ r.a }}</td>
                <td>
                  @if (r.delta !== null) {
                    <p-tag [value]="(r.delta > 0 ? '+' : '') + r.delta + '%'"
                           [severity]="deltaSeverity(r)" />
                  } @else { — }
                </td>
                <td [class]="r.better === 'b' ? 'font-bold text-green-500' : ''">{{ r.b }}</td>
              </tr>
            </ng-template>
          </p-table>
        </p-card>

        <!-- Overlaid throughput chart -->
        @if (chartData(p); as data) {
          <p-card header="Throughput over time">
            <p-chart type="line" [data]="data" [options]="chartOpts" />
          </p-card>
        }
      } @else {
        <p class="text-color-secondary">Loading…</p>
      }
    </div>
  `,
})
export class BenchmarkCompareComponent implements OnInit {
  pair = signal<any>(null);
  chartOpts = { responsive: true };

  constructor(private route: ActivatedRoute, private api: ApiService) {}

  ngOnInit() {
    this.route.queryParams.subscribe(q => {
      if (q['a'] && q['b']) {
        this.api.compareBenchmarks(q['a'], q['b']).subscribe(p => this.pair.set(p));
      }
    });
  }

  rows(p: any): MetricRow[] {
    const def = (r: any, path: string) => path.split('.').reduce((o, k) => o?.[k], r) ?? null;
    const pct = (a: number | null, b: number | null) => a && b ? Math.round(((b - a) / a) * 100) : null;
    const metrics: { label: string; path: string; higherIsBetter: boolean }[] = [
      { label: 'Completed', path: 'throughput.completed', higherIsBetter: true },
      { label: 'Failed', path: 'throughput.failed', higherIsBetter: false },
      { label: 'Avg RPS', path: 'throughput.avg_rps', higherIsBetter: true },
      { label: 'Peak RPS 30s', path: 'throughput.peak_rps_30s', higherIsBetter: true },
      { label: 'Wall time (s)', path: 'total_wall_time_s', higherIsBetter: false },
      { label: 'Lag p50 (s)', path: 'scheduling_lag.p50_s', higherIsBetter: false },
      { label: 'Lag p95 (s)', path: 'scheduling_lag.p95_s', higherIsBetter: false },
      { label: 'Lag p99 (s)', path: 'scheduling_lag.p99_s', higherIsBetter: false },
      { label: 'E2E p50 (s)', path: 'e2e_latency.p50_s', higherIsBetter: false },
      { label: 'E2E p95 (s)', path: 'e2e_latency.p95_s', higherIsBetter: false },
      { label: 'E2E p99 (s)', path: 'e2e_latency.p99_s', higherIsBetter: false },
    ];
    return metrics.map(m => {
      const a = def(p.a, m.path);
      const b = def(p.b, m.path);
      const delta = pct(a, b);
      const better: 'a' | 'b' | null = a == null || b == null ? null
        : m.higherIsBetter ? (a >= b ? 'a' : 'b') : (a <= b ? 'a' : 'b');
      return { label: m.label, a: a ?? '—', b: b ?? '—', delta, better };
    });
  }

  deltaSeverity(r: MetricRow): 'success' | 'danger' | 'secondary' {
    if (r.delta === null || r.delta === 0) return 'secondary';
    return r.better === 'b' ? 'success' : 'danger';
  }

  chartData(p: any) {
    const bA: any[] = p.a.throughput?.over_time ?? [];
    const bB: any[] = p.b.throughput?.over_time ?? [];
    if (!bA.length && !bB.length) return null;
    const labels = bA.length >= bB.length ? bA.map((b: any) => b.window_start) : bB.map((b: any) => b.window_start);
    return {
      labels,
      datasets: [
        { label: `A — ${p.a.project}`, data: bA.map((b: any) => b.rps), borderColor: '#6366f1', fill: false, tension: 0.3 },
        { label: `B — ${p.b.project}`, data: bB.map((b: any) => b.rps), borderColor: '#f59e0b', fill: false, tension: 0.3 },
      ],
    };
  }
}
