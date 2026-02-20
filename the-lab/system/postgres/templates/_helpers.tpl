{{/*
Sanitize a name for use as a PostgreSQL identifier (database name or role name).
Rules: lowercase, hyphens → underscores, strip anything not [a-z0-9_],
prefix with underscore if the result starts with a digit.

NOTE: regexReplaceAll signature is (regex, s, repl); the piped value becomes
the replacement (last arg), not the input. Use explicit variable assignment.
*/}}
{{- define "postgres.pgName" -}}
{{- $s := . | lower | replace "-" "_" -}}
{{- $s = regexReplaceAll "[^a-z0-9_]" $s "" -}}
{{- if regexMatch "^[0-9]" $s -}}{{- $s = printf "_%s" $s -}}{{- end -}}
{{- $s -}}
{{- end -}}

{{/*
Sanitize a name for use as a Kubernetes resource name.
Rules: lowercase, underscores → hyphens, strip anything not [a-z0-9-],
trim leading/trailing hyphens.
*/}}
{{- define "postgres.k8sName" -}}
{{- $s := . | lower | replace "_" "-" -}}
{{- $s = regexReplaceAll "[^a-z0-9-]" $s "" -}}
{{- trimAll "-" $s -}}
{{- end -}}
