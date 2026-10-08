{{- define "bitbucket-mcp.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "bitbucket-mcp.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "bitbucket-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bitbucket-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "bitbucket-mcp.labels" -}}
{{ include "bitbucket-mcp.selectorLabels" . }}
app.kubernetes.io/version: {{ (.Values.image.tag | default .Chart.AppVersion) | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Host as clients send it: lower-cased, a non-default port kept — the SDK compares Host exactly. */}}
{{- define "bitbucket-mcp.publicHost" -}}
{{- $url := required "publicUrl is required, e.g. https://mcp.example.com" .Values.publicUrl -}}
{{- (urlParse $url).host | lower | trimSuffix ":443" -}}
{{- end -}}

{{/* Host without port, as an Ingress rule and a TLS entry expect it. */}}
{{- define "bitbucket-mcp.publicHostname" -}}
{{- include "bitbucket-mcp.publicHost" . | splitList ":" | first -}}
{{- end -}}

{{- define "bitbucket-mcp.publicOrigin" -}}
{{- printf "https://%s" (include "bitbucket-mcp.publicHost" .) -}}
{{- end -}}

{{- define "bitbucket-mcp.backendConfigName" -}}
{{- printf "%s-backend" (include "bitbucket-mcp.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The env the chart derives from its values: one source for the Deployment and the guard below. */}}
{{- define "bitbucket-mcp.managedEnv" -}}
- name: BITBUCKET_RESOURCE_SERVER_URL
  value: {{ printf "%s/mcp" (include "bitbucket-mcp.publicOrigin" .) | quote }}
- name: BITBUCKET_ALLOWED_HOSTS
  value: {{ prepend .Values.extraAllowedHosts (include "bitbucket-mcp.publicHost" .) | join "," | quote }}
- name: BITBUCKET_ALLOWED_ORIGINS
  value: {{ prepend .Values.extraAllowedOrigins (include "bitbucket-mcp.publicOrigin" .) | join "," | quote }}
{{- with .Values.multiTenant }}
{{- if .readOnly }}
- name: BITBUCKET_MULTITENANT_READ_ONLY
  value: "1"
{{- end }}
{{- if .allowDestructive }}
- name: BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE
  value: "1"
{{- end }}
{{- with .allowedWorkspaces }}
- name: BITBUCKET_MULTITENANT_ALLOWED_WORKSPACES
  value: {{ join "," . | quote }}
{{- end }}
{{- if .issuerUrl }}
- name: BITBUCKET_OAUTH_ISSUER_URL
  value: {{ .issuerUrl | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{/* extraEnv must not redefine a derived variable: the duplicate would silently win or lose. */}}
{{- define "bitbucket-mcp.validateExtraEnv" -}}
{{- $managed := list -}}
{{- range (include "bitbucket-mcp.managedEnv" . | fromYamlArray) -}}
{{- $managed = append $managed .name -}}
{{- end -}}
{{- range .Values.extraEnv -}}
{{- if has .name $managed -}}
{{- fail (printf "extraEnv must not set %s: it is derived from publicUrl, extraAllowed* or multiTenant" .name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
