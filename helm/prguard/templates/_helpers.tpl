{{- define "prguard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "prguard.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "prguard.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "prguard.labels" -}}
app.kubernetes.io/name: {{ include "prguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
