import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { InputTextModule } from 'primeng/inputtext';
import { PasswordModule } from 'primeng/password';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { MessageModule } from 'primeng/message';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, InputTextModule, PasswordModule, ButtonModule, CardModule, MessageModule],
  template: `
    <div class="flex align-items-center justify-content-center h-screen surface-ground">
      <p-card header="Workflows UI" styleClass="w-25rem">
        <form (ngSubmit)="submit()" class="flex flex-column gap-3">
          <div class="flex flex-column gap-1">
            <label for="username">Username</label>
            <input pInputText id="username" [(ngModel)]="username" name="username" autocomplete="username" required />
          </div>
          <div class="flex flex-column gap-1">
            <label for="password">Password</label>
            <p-password id="password" [(ngModel)]="password" name="password" [feedback]="false" [toggleMask]="true" styleClass="w-full" inputStyleClass="w-full" required />
          </div>
          @if (error()) {
            <p-message severity="error" [text]="error()!" />
          }
          <p-button type="submit" label="Sign in" [loading]="loading()" styleClass="w-full" />
        </form>
      </p-card>
    </div>
  `,
})
export class LoginComponent {
  username = '';
  password = '';
  loading = signal(false);
  error = signal<string | null>(null);

  constructor(private auth: AuthService, private router: Router) {}

  submit() {
    if (!this.username || !this.password) return;
    this.loading.set(true);
    this.error.set(null);
    this.auth.login(this.username, this.password).subscribe({
      next: () => this.router.navigate(['/workflows']),
      error: (e) => {
        this.loading.set(false);
        this.error.set(e.status === 401 ? 'Invalid credentials' : 'Login failed — check connection');
      },
    });
  }
}
