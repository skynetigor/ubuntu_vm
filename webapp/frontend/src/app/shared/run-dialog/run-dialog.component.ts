import { Component, Input, Output, EventEmitter, signal, OnChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DialogModule } from 'primeng/dialog';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { InputNumberModule } from 'primeng/inputnumber';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { SelectModule } from 'primeng/select';
import { TextareaModule } from 'primeng/textarea';
import { ApiService } from '../../core/api.service';

interface FieldDef { key: string; label: string; type: string; enum?: string[]; required: boolean; default?: any; }

@Component({
  selector: 'app-run-dialog',
  standalone: true,
  imports: [FormsModule, DialogModule, ButtonModule, InputTextModule, InputNumberModule, ToggleSwitchModule, SelectModule, TextareaModule],
  template: `
    <p-dialog [header]="'Run: ' + workflowName" [(visible)]="visible" (visibleChange)="visibleChange.emit($event)"
              [modal]="true" [style]="{width:'480px'}" [draggable]="false">
      <form (ngSubmit)="submit()" id="run-form" class="flex flex-column gap-3 pt-2">
        @for (f of fields; track f.key) {
          <div class="flex flex-column gap-1">
            <label [for]="f.key" class="font-medium text-sm">
              {{ f.label }}<span class="text-red-400" *ngIf="f.required"> *</span>
            </label>
            @if (f.enum) {
              <p-select [inputId]="f.key" [(ngModel)]="values[f.key]" [name]="f.key"
                        [options]="f.enum" styleClass="w-full" />
            } @else if (f.type === 'integer' || f.type === 'number') {
              <p-inputnumber [inputId]="f.key" [(ngModel)]="values[f.key]" [name]="f.key" styleClass="w-full" />
            } @else if (f.type === 'boolean') {
              <p-toggleswitch [inputId]="f.key" [(ngModel)]="values[f.key]" [name]="f.key" />
            } @else if (f.type === 'array' || f.type === 'object') {
              <textarea pTextarea [id]="f.key" [(ngModel)]="values[f.key]" [name]="f.key"
                        rows="4" class="w-full font-mono text-sm" placeholder="JSON"></textarea>
            } @else {
              <input pInputText [id]="f.key" [(ngModel)]="values[f.key]" [name]="f.key" />
            }
          </div>
        }
        @if (error()) {
          <small class="text-red-400">{{ error() }}</small>
        }
      </form>
      <ng-template pTemplate="footer">
        <p-button label="Cancel" [text]="true" (onClick)="visibleChange.emit(false)" />
        <p-button label="Run" type="submit" form="run-form" [loading]="loading()" />
      </ng-template>
    </p-dialog>
  `,
})
export class RunDialogComponent implements OnChanges {
  @Input() workflowId = '';
  @Input() workflowName = '';
  @Input() visible = false;
  @Input() schema: any = {};
  @Output() visibleChange = new EventEmitter<boolean>();
  @Output() started = new EventEmitter<any>();

  fields: FieldDef[] = [];
  values: Record<string, any> = {};
  loading = signal(false);
  error = signal<string | null>(null);

  constructor(private api: ApiService) {}

  ngOnChanges() {
    const props = this.schema?.properties ?? {};
    const required: string[] = this.schema?.required ?? [];
    this.fields = Object.entries(props).map(([key, def]: [string, any]) => ({
      key, label: key, type: def.type ?? 'string', enum: def.enum, required: required.includes(key), default: def.default,
    }));
    this.values = Object.fromEntries(this.fields.map(f => [f.key, f.default ?? (f.type === 'boolean' ? false : f.type === 'array' || f.type === 'object' ? '' : '')]));
  }

  submit() {
    this.loading.set(true);
    this.error.set(null);
    const inputs: Record<string, any> = {};
    for (const f of this.fields) {
      let v = this.values[f.key];
      if (f.type === 'array' || f.type === 'object') {
        try { v = v ? JSON.parse(v) : undefined; } catch { this.error.set(`${f.label}: invalid JSON`); this.loading.set(false); return; }
      }
      if (v !== undefined && v !== '') inputs[f.key] = v;
    }
    this.api.runWorkflow(this.workflowId, inputs).subscribe({
      next: (res) => { this.loading.set(false); this.visibleChange.emit(false); this.started.emit(res); },
      error: (e) => { this.loading.set(false); this.error.set(e.error?.message ?? 'Run failed'); },
    });
  }
}
