{{/*
Common helpers for the hcwave chart.
*/}}

{{- define "hcwave.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hcwave.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "hcwave.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/part-of: hcwave
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels for one component (api, worker, staff-ui, job). */}}
{{- define "hcwave.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hcwave.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "hcwave.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}{{ .Values.serviceAccount.name }}{{- else -}}{{ default "default" .Values.serviceAccount.name }}{{- end -}}
{{- end -}}

{{/* Full image reference: [registry/]repository:tag */}}
{{- define "hcwave.image" -}}
{{- $registry := .root.Values.global.imageRegistry -}}
{{- if $registry -}}{{ printf "%s/%s:%s" $registry .image.repository .image.tag }}{{- else -}}{{ printf "%s:%s" .image.repository .image.tag }}{{- end -}}
{{- end -}}

{{/* Pod labels; opts pods into workload identity token injection. */}}
{{- define "hcwave.podLabels" -}}
{{ include "hcwave.selectorLabels" . }}
{{- if .root.Values.serviceAccount.workloadIdentity.enabled }}
azure.workload.identity/use: "true"
{{- end }}
{{- end -}}

{{/* Environment shared by every backend container. */}}
{{- define "hcwave.backendEnv" -}}
- name: HCWAVE_CONFIG_OVERLAY_DIR
  value: /app/config-overlay
{{- range $name, $value := .Values.env }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "hcwave.backendEnvFrom" -}}
- secretRef:
    name: {{ .Values.secrets.secretName }}
    optional: {{ eq .Values.secrets.provider "existing" | ternary false true }}
{{- end -}}

{{- define "hcwave.backendVolumes" -}}
- name: config-overlay
  configMap:
    name: {{ include "hcwave.fullname" . }}-config
- name: tmp
  emptyDir: {}
{{- if eq .Values.secrets.provider "azureKeyVault" }}
- name: keyvault
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: {{ include "hcwave.fullname" . }}-keyvault
{{- end }}
{{- end -}}

{{- define "hcwave.backendVolumeMounts" -}}
- name: config-overlay
  mountPath: /app/config-overlay
  readOnly: true
- name: tmp
  mountPath: /tmp
{{- if eq .Values.secrets.provider "azureKeyVault" }}
- name: keyvault
  mountPath: /mnt/secrets
  readOnly: true
{{- end }}
{{- end -}}

{{/* Spread replicas across availability zones and nodes. */}}
{{- define "hcwave.topologySpread" -}}
{{- if .root.Values.topologySpreadAcrossZones }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "hcwave.selectorLabels" . | nindent 8 }}
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "hcwave.selectorLabels" . | nindent 8 }}
{{- end }}
{{- end -}}

{{- define "hcwave.scheduling" -}}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
