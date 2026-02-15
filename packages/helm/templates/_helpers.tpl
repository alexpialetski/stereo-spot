{{/*
Common labels
*/}}
{{- define "stereo-spot.labels" -}}
app.kubernetes.io/name: stereo-spot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .Chart.Name }}
{{- end -}}

{{- define "stereo-spot.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
