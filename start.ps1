$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
& .venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv/Scripts/python.exe manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
if (!(Test-Path .demo-initialised)) {
  $demoSecret=Read-Host 'Choose a demonstration password (12+ characters)' -AsSecureString
  $env:DEMO_PASSWORD=[System.Net.NetworkCredential]::new('', $demoSecret).Password
  & .venv/Scripts/python.exe manage.py seed_demo
  if ($LASTEXITCODE -ne 0) { throw 'Demo setup failed' }
  Remove-Item Env:DEMO_PASSWORD
  Set-Content .demo-initialised 'Demo initialised'
}
& .venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
