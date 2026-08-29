# Daiane Oakes Admin Panel Monitoring

The Daiane Oakes Admin Panel is the first monitored production system connected to VOLT CORE.

## Target flow

Admin Panel -> POST /api/v1/watch/events -> priority classification -> event history -> P1/P2/P3 voice escalation.

## Event levels

- CRITICAL -> P1 -> call
- ERROR -> P2 -> call
- WARNING -> P3 -> call
- INFO -> P4 -> digest only

## Required client integration

Use the existing VOLT CORE API client credentials and send JSON events with:

```json
{
  "system": "daiane-oakes-admin-panel",
  "level": "ERROR",
  "message": "Human-readable monitoring event"
}
```

## Safety

Monitoring must be best-effort and must never block a user action in the Admin Panel. Failures while reporting to VOLT CORE must be caught and logged locally.
