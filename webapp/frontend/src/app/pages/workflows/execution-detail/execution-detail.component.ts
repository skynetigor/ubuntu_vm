import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { DrawerModule } from 'primeng/drawer';
import { ButtonModule } from 'primeng/button';
import { TreeModule } from 'primeng/tree';
import { TreeNode } from 'primeng/api';
import { PanelModule } from 'primeng/panel';
import { StatusBadgeComponent } from '../../../shared/status-badge/status-badge.component';
import { DurationPipe } from '../../../shared/duration.pipe';
import { ApiService } from '../../../core/api.service';

@Component({
  selector: 'app-execution-detail',
  standalone: true,
  imports: [DatePipe, DrawerModule, ButtonModule, TreeModule, PanelModule, StatusBadgeComponent, DurationPipe],
  template: `
    <p-drawer [(visible)]="visible" (visibleChange)="onClose($event)"
              header="Execution Detail" position="right" [style]="{width:'480px'}">
      @if (execution(); as ex) {
        <div class="flex flex-column gap-3">
          <div class="flex flex-column gap-1">
            <div class="flex gap-2 align-items-center">
              <app-status-badge [status]="ex.status" />
              <span class="font-mono text-xs text-color-secondary">{{ ex.id }}</span>
            </div>
            <small class="text-color-secondary">Started: {{ ex.startedAt | date:'medium' }}</small>
            <small class="text-color-secondary">Duration: {{ ex.duration | duration }}</small>
          </div>

          @if (stepTree().length) {
            <p-tree [value]="stepTree()" styleClass="w-full text-sm">
              <ng-template pTemplate="default" let-node>
                <div class="flex align-items-center gap-2">
                  <app-status-badge [status]="node.data?.status" />
                  <span>{{ node.label }}</span>
                  <span class="text-color-secondary text-xs ml-auto">{{ node.data?.duration | duration }}</span>
                </div>
              </ng-template>
            </p-tree>
          } @else {
            <p class="text-color-secondary text-sm">No step data available.</p>
          }
        </div>
      } @else {
        <p class="text-color-secondary">Loading…</p>
      }
    </p-drawer>
  `,
})
export class ExecutionDetailComponent implements OnInit {
  visible = true;
  execution = signal<any>(null);
  stepTree = signal<TreeNode[]>([]);

  constructor(private route: ActivatedRoute, private router: Router, private api: ApiService) {}

  ngOnInit() {
    this.route.params.subscribe(p => {
      this.api.getExecution(p['eid']).subscribe(ex => {
        this.execution.set(ex);
        this.stepTree.set(this.buildTree(ex.steps ?? []));
      });
    });
  }

  onClose(open: boolean) {
    if (!open) this.router.navigate(['../..'], { relativeTo: this.route });
  }

  private buildTree(steps: any[]): TreeNode[] {
    return steps.map(s => ({
      label: s.name ?? s.stepId,
      data: { status: s.status, duration: s.duration },
      children: s.steps ? this.buildTree(s.steps) : [],
      expanded: true,
    }));
  }
}
