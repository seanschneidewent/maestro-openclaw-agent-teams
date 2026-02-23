# Fleet Command Center

## Availability

Command Center routes are mounted only when Fleet is enabled.

- `/command-center`
- `/api/command-center/*`
- `/ws/command-center`

In Solo profile, these endpoints return:

```json
{"error":"Fleet mode not enabled","next_step":"Run maestro fleet enable"}
```
