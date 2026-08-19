<#
.SYNOPSIS
  Reclaim disk space from the ubuntu_vm dev environment and shrink the WSL2 vhdx.

.DESCRIPTION
  Runs in this order (order matters — Docker must be alive for the cleanup
  phase, and dead for the compaction phase):

    1. Prune the inner (DinD) daemon inside elastic-dev-vm  <- biggest win
    2. git gc the shared /opt/kibana_repo
    3. Optional -DeepClean: drop node_modules / dist / build caches
    4. Prune the outer daemon (images + build cache, NOT volumes)
    5. Shut down WSL
    6. Compact every WSL vhdx

  Deleting files inside WSL does not shrink the host vhdx on its own —
  step 6 is what actually returns space to your C: drive.

.PARAMETER DeepClean
  Also delete node_modules, dist, build/, .es and the yarn cache from
  /opt/kibana_repo, plus the matching stage markers. Frees the most space but
  forces a full re-bootstrap + re-compile (~30-60 min) on the next deploy.

.PARAMETER SetSparse
  Convert the vhdx files to sparse mode so they auto-shrink in future.
  Requires WSL 2.0+.

.PARAMETER SkipCompact
  Do the cleanup but leave the vhdx alone (skips the WSL shutdown, so
  Docker keeps running).

.PARAMETER DryRun
  Print every command without executing it.

.EXAMPLE
  .\wsl-reclaim.ps1 -DryRun
  .\wsl-reclaim.ps1
  .\wsl-reclaim.ps1 -DeepClean -SetSparse
#>

#Requires -RunAsAdministrator
[CmdletBinding()]
param(
  [switch]$DeepClean,
  [switch]$SetSparse,
  [switch]$SkipCompact,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$VM = 'elastic-dev-vm'

function Say  ($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Info ($m) { Write-Host "    $m" -ForegroundColor Gray }
function Warn ($m) { Write-Host "    ! $m" -ForegroundColor Yellow }
function Ok   ($m) { Write-Host "    + $m" -ForegroundColor Green }

# Run a command, or just print it under -DryRun.
function Run($label, [scriptblock]$block) {
  if ($DryRun) { Warn "DRYRUN would run: $label"; return }
  Info $label
  try { & $block } catch { Warn "failed (continuing): $($_.Exception.Message)" }
}

# Run a bash command inside the dev-vm.
function InVm($label, $bash) {
  Run $label { docker exec $VM bash -lc $bash }
}

function Get-VhdxFiles {
  $paths = @()
  foreach ($root in @("$env:LOCALAPPDATA\Docker\wsl", "$env:LOCALAPPDATA\Packages")) {
    if (Test-Path $root) {
      $paths += Get-ChildItem -Path $root -Filter *.vhdx -Recurse -Depth 4 `
                  -File -ErrorAction SilentlyContinue
    }
  }
  $paths | Sort-Object -Property FullName -Unique
}

function Show-Vhdx($label) {
  Say "vhdx sizes ($label)"
  $files = Get-VhdxFiles
  if (-not $files) { Warn 'no vhdx found under the default locations'; return @{} }
  $map = @{}
  foreach ($f in $files) {
    $gb = [math]::Round($f.Length / 1GB, 2)
    $map[$f.FullName] = $f.Length
    Info ("{0,8} GB  {1}" -f $gb, $f.FullName)
  }
  $total = [math]::Round((($files | Measure-Object -Property Length -Sum).Sum) / 1GB, 2)
  Ok ("total: $total GB")
  $map
}

# ──────────────────────────────────────────────────────────────────────────────
Say 'Preflight'

if ($DryRun) { Warn 'DRY RUN — nothing will be modified' }

$dockerUp = $false
try { docker info *> $null; $dockerUp = ($LASTEXITCODE -eq 0) } catch { $dockerUp = $false }

if ($dockerUp) {
  Ok 'docker daemon reachable'
  $vmUp = (docker ps --filter "name=$VM" --format '{{.Names}}') -contains $VM
  if ($vmUp) { Ok "$VM is running" }
  else { Warn "$VM is not running — skipping inner-daemon cleanup (start it to reclaim the most space)" }
} else {
  Warn 'docker daemon not reachable — skipping all cleanup, going straight to compaction'
  $vmUp = $false
}

if ($DeepClean) {
  Warn 'DEEPCLEAN: node_modules/dist/build will be deleted; next deploy re-bootstraps (~30-60 min)'
}

# ──────────────────────────────────────────────────────────────────────────────
if ($dockerUp) {
  Say 'Usage before'
  Run 'outer: docker system df' { docker system df }
  if ($vmUp) { InVm 'inner: docker system df' 'docker system df' }
  if ($vmUp) { InVm 'inner: /opt breakdown' 'du -xh -d1 /opt 2>/dev/null | sort -h | tail -15' }
}

# ── 1. Inner (DinD) daemon — stale preview images, containers, volumes ────────
if ($vmUp) {
  Say 'Step 1/4  Prune inner DinD daemon'
  Info 'removes preview images/volumes not attached to a RUNNING container'
  InVm 'inner: prune' 'docker system prune -af --volumes'
}

# ── 2. Shared kibana repo housekeeping ───────────────────────────────────────
if ($vmUp) {
  Say 'Step 2/4  Compact /opt/kibana_repo git objects'
  Info 'shallow clones accumulate objects from every branch ever deployed'
  InVm 'git safe.directory' 'git config --global --add safe.directory /opt/kibana_repo || true'
  InVm 'git gc' 'cd /opt/kibana_repo && git gc --prune=now --quiet && du -sh .git'
}

# ── 3. Deep clean (opt-in) ───────────────────────────────────────────────────
if ($vmUp -and $DeepClean) {
  Say 'Step 3/4  Deep clean build artifacts'

  # dist is hard-linked into every /opt/deployments/<p>/kibana/dist (cp -al),
  # so the inodes only free once ALL links are gone. Report remaining links.
  InVm 'dist hard-link count' `
    'test -d /opt/kibana_repo/dist && find /opt/kibana_repo/dist -maxdepth 1 -printf "%n link(s) on %p\n" | head -3 || true'

  InVm 'remove node_modules + build caches' @'
cd /opt/kibana_repo || exit 0
du -sh node_modules dist build .es data 2>/dev/null || true
rm -rf node_modules dist build .es data
'@

  # Markers MUST go with the artifacts they describe, or the next deploy skips
  # the stage and then fails. All three live in $KIBANA_SRC=/opt/kibana_repo.
  InVm 'clear stage markers (.bootstrapcommit/.compilecommit)' `
    'rm -f /opt/kibana_repo/.bootstrapcommit /opt/kibana_repo/.compilecommit'

  InVm 'yarn cache clean' 'yarn cache clean 2>/dev/null || rm -rf /root/.cache/yarn /root/.yarn/berry/cache || true'
}
elseif ($vmUp) {
  Say 'Step 3/4  Deep clean SKIPPED (pass -DeepClean to enable)'
}

# ── 4. Outer daemon: images + build cache, never volumes ─────────────────────
if ($dockerUp) {
  Say 'Step 4/4  Prune outer daemon'
  Warn 'volumes are NOT pruned here: es_data holds your deployed-previews index'
  Run 'outer: image prune' { docker image prune -af }
  Run 'outer: builder prune' { docker builder prune -af }

  Say 'Usage after cleanup'
  Run 'outer: docker system df' { docker system df }
  if ($vmUp) { InVm 'inner: docker system df' 'docker system df' }
}

# ── 5+6. Shut down WSL and compact ───────────────────────────────────────────
if ($SkipCompact) {
  Say 'Compaction skipped (-SkipCompact)'
  Warn 'space was freed INSIDE wsl but the host vhdx has not shrunk'
  return
}

$before = Show-Vhdx 'before compaction'

Say 'Stopping Docker Desktop + WSL'
Run 'stop Docker Desktop' {
  Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 5
}
Run 'wsl --shutdown' { wsl --shutdown; Start-Sleep -Seconds 5 }

if ($SetSparse) {
  Say 'Enabling sparse vhdx (auto-shrink going forward)'
  # wsl.exe emits UTF-16LE; without this the distro names come back mangled.
  $prevEnc = [Console]::OutputEncoding
  try {
    [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
    $distros = (wsl --list -q) -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
  } finally { [Console]::OutputEncoding = $prevEnc }

  foreach ($d in $distros) {
    Run "set-sparse $d" { wsl --manage $d --set-sparse true }
  }
}

Say 'Compacting vhdx'
$useOptimize = [bool](Get-Command Optimize-VHD -ErrorAction SilentlyContinue)
if ($useOptimize) { Info 'using Optimize-VHD (Hyper-V module present)' }
else { Info 'Optimize-VHD unavailable — falling back to diskpart' }

foreach ($path in $before.Keys) {
  if ($useOptimize) {
    Run "Optimize-VHD $path" { Optimize-VHD -Path $path -Mode Full }
  } else {
    Run "diskpart compact $path" {
      $dp = @"
select vdisk file="$path"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
      $tmp = Join-Path $env:TEMP "compact-$([guid]::NewGuid()).txt"
      Set-Content -LiteralPath $tmp -Value $dp -Encoding Ascii
      try { diskpart /s $tmp } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
  }
}

$after = Show-Vhdx 'after compaction'

Say 'Result'
$sumBefore = ($before.Values | Measure-Object -Sum).Sum
$sumAfter  = ($after.Values  | Measure-Object -Sum).Sum
if ($sumBefore -and $sumAfter) {
  $savedGb = [math]::Round(($sumBefore - $sumAfter) / 1GB, 2)
  Ok ("reclaimed {0} GB  ({1} GB -> {2} GB)" -f `
      $savedGb, [math]::Round($sumBefore/1GB,2), [math]::Round($sumAfter/1GB,2))
}

Run 'restart Docker Desktop' {
  $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $exe) { Start-Process $exe; Ok 'Docker Desktop starting' }
  else { Warn "not found at $exe — start it manually" }
}
