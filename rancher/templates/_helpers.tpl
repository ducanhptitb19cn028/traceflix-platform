{{/* Common labels */}}
{{- define "traceflix.labels" -}}
app.kubernetes.io/part-of: traceflix
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* GPU scheduling block (nodeSelector / tolerations / runtimeClassName).
     Usage at pod-spec level:  {{- include "traceflix.gpuScheduling" . | nindent 6 }} */}}
{{- define "traceflix.gpuScheduling" -}}
{{- with .Values.gpu.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.gpu.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- if .Values.gpu.runtimeClassName }}
runtimeClassName: {{ .Values.gpu.runtimeClassName }}
{{- end }}
{{- end -}}

{{/* storageClassName line (omitted when "" so the cluster default is used) */}}
{{- define "traceflix.storageClass" -}}
{{- if .root.Values.storage.className }}
storageClassName: {{ .root.Values.storage.className }}
{{- end }}
{{- end -}}

{{/* A pod volume backed by a PVC normally, or an emptyDir when
     storage.ephemeral=true (no StorageClass needed; data is lost on pod restart).
     Usage: - {{ include "traceflix.pvVolume" (dict "name" "data" "claim" "prometheus-data" "root" $) }} */}}
{{- define "traceflix.pvVolume" -}}
{{- if .root.Values.storage.ephemeral -}}
{ name: {{ .name }}, emptyDir: {} }
{{- else -}}
{ name: {{ .name }}, persistentVolumeClaim: { claimName: {{ .claim }} } }
{{- end -}}
{{- end -}}
