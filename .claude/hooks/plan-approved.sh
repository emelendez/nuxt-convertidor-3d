#!/bin/bash
# Se dispara con PostToolUse[matcher=ExitPlanMode]: solo corre cuando el
# usuario ha APROBADO el plan (si lo deniega, ExitPlanMode no llega a
# ejecutarse y este hook nunca se dispara). No intenta leer el plan desde
# tool_input (ExitPlanMode no lo lleva: lo lee del fichero de plan). Solo
# avisa a Claude via additionalContext; toda la logica con criterio vive en
# la skill plan-to-issue-flow.

if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
  CONTEXT="El plan acaba de ser aprobado, pero 'gh' (GitHub CLI) no esta disponible o no esta autenticado en esta maquina. Antes de crear la issue de seguimiento, avisa al usuario de que instale/autentique gh (winget install --id GitHub.cli; gh auth login) o, si lo prefiere, continua con la implementacion del plan sin crear la issue."
else
  CONTEXT="El plan acaba de ser aprobado por el usuario. Sigue las instrucciones de la skill 'plan-to-issue-flow' (.claude/skills/plan-to-issue-flow/SKILL.md) antes de empezar a implementarlo: crea la issue de GitHub correspondiente a este plan (titulo, cuerpo, autoasignacion a emelendez y labels), y recuerda seguir tambien sus pasos 2 y 3 (comentario de resumen al terminar y verificar; confirmacion antes de hacer push) mas adelante en esta misma conversacion."
fi

python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": sys.argv[1]}}))
' "$CONTEXT" 2>/dev/null || {
  ESCAPED=$(printf '%s' "$CONTEXT" | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "%s"}}' "$ESCAPED"
}

exit 0