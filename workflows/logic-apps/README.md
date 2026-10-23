# Logic Apps Standard workflows

Visual, low-code schedules that trigger the backend's job API over the VNet
(the n8n equivalent). The job logic itself lives in Python
(`services/backend/src/hcwave/jobs`), so the same jobs also run as Kubernetes
CronJobs on any cloud (`scheduler.engine: k8s_cronjob`).

| Workflow | Schedule (IST) | Backend job |
|---|---|---|
| reminders | every 15 min | `reminders` |
| feedback-requests | every 15 min | `feedback` |
| ticket-escalation | every 30 min | `tickets-escalate` |
| report-alerts | every 5 min | `his-reports` |
| visit-sync | every 15 min | `his-visits` |
| schedule-sync | daily 05:30 | `his-doctors` |
| daily-briefing | daily 08:00 | `briefing` |
| maintenance | hourly | `maintenance` |

App settings required (set by Bicep): `HCWAVE_INTERNAL_URL` (internal load
balancer URL of the API, port 8001), `HCWAVE_INTERNAL_AUDIENCE`,
`HCWAVE_LOGICAPP_IDENTITY_ID` (resource ID of the user-assigned identity).

Deploy: `scripts/deploy-workflows.sh` zips this folder and runs
`az logicapp deployment source config-zip`.

Extending: add Office 365 Outlook / SQL / Teams connectors in the designer for
hospital-specific notifications – they call the same backend endpoints.
