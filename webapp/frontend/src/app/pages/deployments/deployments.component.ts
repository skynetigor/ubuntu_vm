import { Component, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TableModule } from 'primeng/table';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { ToastModule } from 'primeng/toast';
import { TagModule } from 'primeng/tag';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-deployments',
  standalone: true,
  imports: [DatePipe, RouterLink, TableModule, ButtonModule, DialogModule, ConfirmDialogModule, ToastModule, TagModule],
  providers: [ConfirmationService, MessageService],
  template: `
    <p-toast />
    <p-confirmDialog />

    <div class="p-4">
      <div class="flex align-items-center justify-content-between mb-4">
        <h2 class="m-0">Deployments</h2>
        <a pButton routerLink="/workflows" icon="pi pi-arrow-left" label="Workflows" [text]="true"></a>
      </div>

      <p-table [value]="deployments()" [loading]="loading()" styleClass="p-datatable-sm">
        <ng-template pTemplate="header">
          <tr>
            <th>Project</th><th>Target</th><th>Updated</th><th>Port</th><th style="width:180px">Actions</th>
          </tr>
        </ng-template>
        <ng-template pTemplate="body" let-d>
          <tr>
            <td class="font-mono text-sm">{{ d.container_name }}</td>
            <td class="text-sm" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" [title]="d.target">{{ d.target }}</td>
            <td class="text-sm">{{ d.updated_at | date:'short' }}</td>
            <td>{{ d.port }}</td>
            <td>
              <div class="flex gap-2">
                <a [href]="d.public_url || ('http://localhost:' + d.port)" target="_blank"
                   pButton icon="pi pi-external-link" size="small" [text]="true" title="Open Kibana"></a>
                <p-button icon="pi pi-key" size="small" [text]="true" title="Credentials" (onClick)="showCreds(d)" />
                <p-button icon="pi pi-trash" size="small" [text]="true" severity="danger" title="Delete" (onClick)="confirmDelete(d)" />
              </div>
            </td>
          </tr>
        </ng-template>
        <ng-template pTemplate="empty">
          <tr><td colspan="5" class="text-center text-color-secondary p-4">No deployments found</td></tr>
        </ng-template>
      </p-table>
    </div>

    <!-- Credentials dialog -->
    <p-dialog header="Credentials" [(visible)]="credsVisible" [modal]="true" [style]="{width:'360px'}">
      @if (creds(); as c) {
        <div class="flex flex-column gap-3 pt-2">
          <div class="flex flex-column gap-1">
            <label class="font-medium text-sm">Username</label>
            <div class="font-mono p-2 surface-100 border-round">{{ c.username }}</div>
          </div>
          <div class="flex flex-column gap-1">
            <label class="font-medium text-sm">Password</label>
            <div class="font-mono p-2 surface-100 border-round flex align-items-center justify-content-between">
              <span>{{ showPassword() ? c.password : '••••••••' }}</span>
              <p-button [icon]="showPassword() ? 'pi pi-eye-slash' : 'pi pi-eye'" [text]="true" size="small"
                        (onClick)="showPassword.set(!showPassword())" />
            </div>
          </div>
        </div>
      } @else {
        <p class="text-color-secondary">Loading…</p>
      }
    </p-dialog>
  `,
})
export class DeploymentsComponent implements OnInit {
  deployments = signal<any[]>([]);
  loading = signal(true);
  credsVisible = false;
  creds = signal<any>(null);
  showPassword = signal(false);

  constructor(private api: ApiService, private confirm: ConfirmationService, private toast: MessageService) {}

  ngOnInit() {
    this.api.getDeployments().subscribe({
      next: (data) => { this.deployments.set(data); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  showCreds(d: any) {
    this.creds.set(null);
    this.showPassword.set(false);
    this.credsVisible = true;
    this.api.getCredentials(d.id).subscribe({ next: (c) => this.creds.set(c) });
  }

  confirmDelete(d: any) {
    this.confirm.confirm({
      message: `Delete preview "${d.container_name}"? This will stop the container and remove all data.`,
      header: 'Confirm Delete',
      icon: 'pi pi-trash',
      accept: () => {
        this.api.deleteDeployment(d.id).subscribe({
          next: () => {
            this.deployments.update(list => list.filter(x => x.id !== d.id));
            this.toast.add({ severity: 'success', summary: 'Cleanup triggered', detail: d.container_name });
          },
          error: () => this.toast.add({ severity: 'error', summary: 'Failed', detail: 'Could not trigger cleanup' }),
        });
      },
    });
  }
}
