@echo off
powershell -Command "$p='elastic_dev_vm\id_ed25519'; $acl=Get-Acl $p; $acl.SetAccessRuleProtection($true,$false); $r=New-Object System.Security.AccessControl.FileSystemAccessRule([System.Security.Principal.WindowsIdentity]::GetCurrent().Name,'Read','Allow'); $acl.SetAccessRule($r); Set-Acl $p $acl" >nul
docker compose -f elastic_dev_vm/docker-compose.yml up -d --build
