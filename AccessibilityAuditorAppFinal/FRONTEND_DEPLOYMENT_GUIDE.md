# Accessibility Auditor — Frontend Deployment Configuration

This source package has no production API key embedded in it. Before publishing,
edit `AccessibilityAuditorApp/appsettings.Production.json`.

## Required values

1. `AccessibilityBackend:BaseUrl`
   - Internal URL used by the IIS server to reach the GB10 FastAPI backend.
   - Include the scheme and port.
   - Example: `http://10.20.30.40:8091`
   - Prefer an internal HTTPS hostname when TTUHSC provides one.

2. `AccessibilityBackend:ApiKey`
   - A newly generated random key of at least 32 characters.
   - It must exactly match `BackendApiKey` in the GB10 `backendsettings.json`.
   - Do not reuse the key from the uploaded development ZIP.

3. `AllowedHosts`
   - The public hostname users enter in the browser, without `https://`.
   - Example: `accessibility-auditor.ttuhsc.edu`
   - Multiple hostnames are separated with semicolons.

4. `WebBasePath`
   - Use `/` for a dedicated hostname such as
     `https://accessibility-auditor.ttuhsc.edu/`.
   - Use `/AccessibilityAuditor` for a sub-application such as
     `https://apps.ttuhsc.edu/AccessibilityAuditor/`.

5. `TemporaryStorage:JobsRoot`
   - Writable Windows folder for transient files.
   - Default template: `C:\ProgramData\TTUHSC\AccessibilityAuditor\Temp\Jobs`
   - Grant Modify permission only to the IIS application-pool identity.

6. `ReverseProxy:KnownProxyIp`
   - Leave blank when IIS directly receives HTTPS.
   - Enter the exact F5/load-balancer/reverse-proxy IP only when that device
     terminates HTTPS and forwards the request to IIS.

## Optional values

- `AccessibilityBackend:RequestTimeoutMinutes`: frontend-to-GB10 request timeout.
  The included value is 30 minutes.
- `TemporaryStorage:MaximumJobAgeMinutes`: orphaned-folder expiration. Default 120.
- `TemporaryStorage:CleanupIntervalMinutes`: cleanup frequency. Default 15.

## Publish

From the `AccessibilityAuditorApp` project folder:

```powershell
dotnet restore
dotnet publish .\AccessibilityAuditorApp.csproj -c Release -o .\publish
```

Deploy only the contents of `publish` to IIS. The production server must have
the .NET 10 Hosting Bundle and IIS WebSocket Protocol installed.

## IIS permissions

Example application pool: `AccessibilityAuditorAppPool`

```powershell
New-Item -ItemType Directory -Path "C:\ProgramData\TTUHSC\AccessibilityAuditor\Temp\Jobs" -Force
icacls "C:\ProgramData\TTUHSC\AccessibilityAuditor\Temp\Jobs" /grant "IIS AppPool\AccessibilityAuditorAppPool:(OI)(CI)M"
icacls "C:\inetpub\AccessibilityAuditor\appsettings.Production.json" /grant "IIS AppPool\AccessibilityAuditorAppPool:R"
```

The application validates required Production settings at startup and will fail
with a clear configuration error if placeholders remain.
