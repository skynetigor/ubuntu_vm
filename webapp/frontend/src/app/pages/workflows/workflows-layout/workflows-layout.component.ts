import { Component, OnInit, signal } from '@angular/core';
import { Router, RouterLink, RouterOutlet, RouterLinkActive } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { DrawerModule } from 'primeng/drawer';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';
import { ApiService } from '../../../core/api.service';
import { AuthService } from '../../../core/auth.service';

@Component({
  selector: 'app-workflows-layout',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, DrawerModule, ButtonModule, InputTextModule, TagModule],
  template: `
    <div class="flex h-screen">
      <!-- Sidebar -->
      <aside class="flex flex-column surface-section border-right-1 surface-border" style="width:280px;min-width:280px">
        <div class="p-3 border-bottom-1 surface-border flex align-items-center justify-content-between">
          <span class="font-bold text-lg">Workflows</span>
          <div class="flex gap-2">
            <a pButton routerLink="/deployments" icon="pi pi-server" [text]="true" size="small" title="Deployments"></a>
            <a pButton routerLink="/benchmarks" icon="pi pi-chart-bar" [text]="true" size="small" title="Benchmarks"></a>
            <p-button icon="pi pi-sign-out" [text]="true" size="small" (onClick)="auth.logout()" title="Sign out" />
          </div>
        </div>
        <div class="p-2">
          <input pInputText [(ngModel)]="search" placeholder="Search…" class="w-full" />
        </div>
        <div class="overflow-y-auto flex-1">
          @for (wf of filtered(); track wf.id) {
            <a [routerLink]="['/workflows', wf.id]" routerLinkActive="surface-100"
               class="flex align-items-center gap-2 px-3 py-2 cursor-pointer hover:surface-100 no-underline text-color border-none">
              <span class="flex-1 text-sm font-medium">{{ wf.name }}</span>
              <p-tag [value]="triggerType(wf)" severity="secondary" styleClass="text-xs" />
              <p-tag [value]="wf.enabled ? 'on' : 'off'" [severity]="wf.enabled ? 'success' : 'danger'" styleClass="text-xs" />
            </a>
          }
          @if (loading()) {
            <div class="p-3 text-sm text-color-secondary">Loading…</div>
          }
        </div>
      </aside>

      <!-- Main -->
      <main class="flex-1 overflow-auto">
        <router-outlet />
      </main>
    </div>
  `,
})
export class WorkflowsLayoutComponent implements OnInit {
  workflows = signal<any[]>([]);
  loading = signal(true);
  search = '';

  constructor(public auth: AuthService, private api: ApiService, private router: Router) {}

  ngOnInit() {
    this.api.getWorkflows().subscribe({
      next: (res) => { this.workflows.set(res.data ?? res.results ?? res); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  filtered() {
    const q = this.search.toLowerCase();
    return q ? this.workflows().filter(w => w.name?.toLowerCase().includes(q)) : this.workflows();
  }

  triggerType(wf: any): string {
    const t = wf.definition?.triggers?.[0]?.type;
    return t === 'manual' ? 'manual' : t === 'scheduled' ? 'cron' : t ?? '?';
  }
}
