"""Local operational incident history and optional desktop notifications."""
from __future__ import annotations
import base64
import json
import os
import subprocess
from datetime import datetime, timezone
from core.persistence import append_jsonl, atomic_write_bytes, file_lock
from core.research_paths import research_paths


def record_health_alerts(health: dict, data_root=None, *, desktop_notifications=False):
    root = research_paths(data_root)['root'] / 'operations'
    state_path = root / 'alert_state.json'
    with file_lock(state_path):
        previous = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        active = {row['key']:row for row in health.get('alerts',[])}
        events = []
        for key in sorted(set(previous) | set(active)):
            current, old = active.get(key), previous.get(key)
            # Keep unchanged incidents quiet; changed counts stay visible on the health page.
            if bool(current) == bool(old):
                continue
            event = {'observed_at_utc':datetime.now(timezone.utc).isoformat(),'key':key,
                     'transition':'OPENED' if current else 'RECOVERED',
                     'message':current['message'] if current else f'研究異常已恢復：{key}',
                     'severity':current['severity'] if current else 'INFO'}
            append_jsonl(root / 'alerts.jsonl',event)
            events.append(event)
        atomic_write_bytes(state_path,json.dumps(active,ensure_ascii=False,indent=2).encode('utf-8'))
    notification_errors = []
    pending_path = root / 'pending_notification.json'
    pending = json.loads(pending_path.read_text(encoding='utf-8')) if pending_path.exists() else {}
    queued_events = events or pending.get('events', [])
    attempts = 0 if events else int(pending.get('attempts', 0))
    attempted_notification = desktop_notifications and os.name == 'nt' and queued_events and attempts < 3
    if attempted_notification:
        try:
            _notify_desktop({'message':'\n'.join(event['message'] for event in queued_events)[:900]})
        except (OSError, subprocess.SubprocessError) as exc:
            notification_errors.append(str(exc))
        atomic_write_bytes(pending_path, json.dumps({'events':queued_events if notification_errors else [],
                            'attempts':attempts+1 if notification_errors else 0},ensure_ascii=False).encode('utf-8'))
    atomic_write_bytes(root / 'notification_receipt.json', json.dumps({
        'observed_at_utc':datetime.now(timezone.utc).isoformat(), 'requested':bool(attempted_notification),
        'helper_succeeded':bool(attempted_notification and not notification_errors),
        'pending_event_count':len(queued_events) if notification_errors or not attempted_notification else 0,
        'errors':notification_errors}, indent=2).encode('utf-8'))
    return {'events':events,'active_incident_count':len(active),'desktop_notification_errors':notification_errors}


def _notify_desktop(event):
    """A hidden helper presents a local tray balloon; no third-party transmission."""
    payload = base64.b64encode(json.dumps(event,ensure_ascii=False).encode('utf-8')).decode('ascii')
    script = f"""Add-Type -AssemblyName System.Windows.Forms
$notice = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Information
$icon.Visible = $true
$icon.ShowBalloonTip(5000, '瘋狗流研究資料提醒', [string]$notice.message, [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 6
$icon.Dispose()
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden',
                      '-EncodedCommand',encoded],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=12)
