import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterOutlet } from '@angular/router';
import { DatePipe, SlicePipe } from '@angular/common';
import { TableModule } from 'primeng/table';
import { ButtonModule } from 'primeng/button';
import { ToastModule } from 'primeng/toast';
import { MessageService } from 'primeng/api';
import { StatusBadgeComponent } from '../../../shared/status-badge/status-badge.component';
import { RunDialogComponent } from '../../../shared/run-dialog/run-dialog.component';
import { DurationPipe } from '../../../shared/duration.pipe';
import { ApiService } from '../../../core/api.service';

const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'error']);

@Component({
  selector: 'app-workflow-detail',
  standalone: true,
  imports: [RouterOutlet, DatePipe, SlicePipe, TableModule, ButtonModule, ToastModule, StatusBadgeComponent, RunDialogComponent, DurationPipe],
  providers: [MessageService],
  template: `
    <p-toast />
    <div class="p-4">
      @if (workflow(); as wf) {
        <div class="flex align-items-center justify-content-between mb-4">
          <div>
            <h2 class="m-0">{{ wf.name }}</h2>
            @if (wf.description) { <p class="text-color-secondary mt-1 mb-0 text-sm">{{ wf.description }}</p> }
          </div>
          <p-button label="Run" icon="pi pi-play" (onClick)="showRun = true" />
        </div>

        <p-table [value]="executions()" [loading]="tableLoading()" [paginator]="true" [rows]="20"
                 [totalRecords]="total()" [lazy]="true" (onLazyLoad)="onPage($event)"
                 styleClass="p-datatable-sm">
          <ng-template pTemplate="header">
            <tr>
              <th>Status</th><th>Execution ID</th><th>Started</th><th>Duration</th><th>Type</th>
            </tr>
          </ng-template>
          <ng-template pTemplate="body" let-ex>
            <tr class="cursor-pointer" (click)="openExecution(ex)">
              <td><app-status-badge [status]="ex.status" /></td>
              <td class="font-mono text-xs">{{ ex.id | slice:0:12 }}…</td>
              <td>{{ ex.startedAt | date:'short' }}</td>
              <td>{{ ex.duration | duration }}</td>
              <td>{{ ex.executionType ?? '—' }}</td>
            </tr>
          </ng-template>
          <ng-template pTemplate="empty"><tr><td colspan="5" class="text-center text-color-secondary p-4">No executions yet</td></tr></ng-template>
        </p-table>
      }
    </div>

    <app-run-dialog
      [(visible)]="showRun"
      [workflowId]="workflowId()"
      [workflowName]="workflow()?.name ?? ''"
      [schema]="runSchema()"
      (started)="onStarted($event)" />

    <router-outlet />
  `,
})
export class WorkflowDetailComponent implements OnInit, OnDestroy {
  workflowId = signal('');
  workflow = signal<any>(null);
  executions = signal<any[]>([]);
  total = signal(0);
  tableLoading = signal(true);
  showRun = false;

  private pollTimer: any;
  private page = 1;

  constructor(private route: ActivatedRoute, private router: Router, private api: ApiService, private toast: MessageService) {}

  ngOnInit() {
    this.route.params.subscribe(p => {
      this.workflowId.set(p['id']);
      this.api.getWorkflow(p['id']).subscribe(res => this.workflow.set(res));
      this.loadExecutions();
    });
  }

  ngOnDestroy() { clearInterval(this.pollTimer); }

  runSchema() {
    return this.workflow()?.triggers?.[0]?.inputs ?? {};
  }

  loadExecutions(page = 1) {
    this.page = page;
    this.tableLoading.set(true);
    this.api.getExecutions(this.workflowId(), { size: 20, page }).subscribe({
      next: (res) => {
        this.executions.set(res.results ?? res.data ?? []);
        this.total.set(res.total ?? 0);
        this.tableLoading.set(false);
        this.schedulePolling();
      },
      error: () => this.tableLoading.set(false),
    });
  }

  onPage(e: any) { this.loadExecutions((e.first / e.rows) + 1); }

  schedulePolling() {
    clearInterval(this.pollTimer);
    const hasActive = this.executions().some(e => !TERMINAL.has(e.status));
    if (hasActive) {
      this.pollTimer = setInterval(() => this.loadExecutions(this.page), 5000);
    }
  }

  openExecution(ex: any) {
    this.router.navigate(['executions', ex.id], { relativeTo: this.route });
  }

  onStarted(res: any) {
    this.toast.add({ severity: 'success', summary: 'Started', detail: `Execution ${res?.data?.executionId ?? ''}` });
    setTimeout(() => this.loadExecutions(1), 1000);
  }
}
