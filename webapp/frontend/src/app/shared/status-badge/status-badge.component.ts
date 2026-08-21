import { Component, Input } from '@angular/core';
import { TagModule } from 'primeng/tag';

type Severity = 'success' | 'info' | 'warn' | 'danger' | 'secondary' | 'contrast';

const SEVERITY_MAP: Record<string, Severity> = {
  completed: 'success',
  running: 'info',
  pending: 'info',
  failed: 'danger',
  error: 'danger',
  cancelled: 'secondary',
  timed_out: 'secondary',
};

@Component({
  selector: 'app-status-badge',
  standalone: true,
  imports: [TagModule],
  template: `<p-tag [value]="status" [severity]="severity" />`,
})
export class StatusBadgeComponent {
  @Input() status = '';
  get severity(): Severity { return SEVERITY_MAP[this.status] ?? 'secondary'; }
}
